# llamacpp_import.py — 连接外部 llama-server 进行推理
# 使用方式：用户自行启动 llama-server，项目通过 HTTP API 调用
# 类似 Ollama 的工作模式：llamacpp_server=http://127.0.0.1:11435

import json
import os
import logging
from urllib import error, request

# 为小模型优化的精简版分析提示词
_LLAMACPP_PRIMARY_PROMPT = (
    "你是一级营养分析助手。分析用户输入，输出 JSON，不要解释。\n"
    '字段： "用户画像摘要","身体状态分析","心理状态分析",'
    '"需重点关注营养素","饮食限制","检索关键词","优化提示词"。\n'
    "其中“需重点关注营养素”“饮食限制”“检索关键词”必须是字符串数组，其余是中文字符串。\n"
    "要求：用户画像摘要必须模糊化隐私——将具体年龄改为年龄段（如20多岁、30多岁），"
    "具体身高体重改为体型描述（如偏瘦、标准、偏胖），不得出现精确数值；"
    "结合身体状况和饮食诉求分析；硬约束优先于口味。"
)

logger = logging.getLogger("diet_assistant")

# 可配置的 llama-server 地址（从环境变量读取，类似 OLLAMA_HOST）
LLAMACPP_SERVER_URL = os.environ.get(
    "LLAMACPP_SERVER_URL",
    "http://127.0.0.1:11435",  # 默认端口，与 Ollama 11434 错开
)


def _post_json(url: str, payload: dict, timeout: int = 120) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def preprocess_with_llamacpp(raw_input: str, model_id: str = "") -> str:
    """
    使用外部 llama-server 进行一级模型预处理。

    用户需提前启动 llama-server，例如：
        llama-server -m 模型路径 -ngl -1 --host 127.0.0.1 --port 11435

    服务地址可通过环境变量 LLAMACPP_SERVER_URL 配置，
    或在 model_id 中以 "llamacpp:http://..." 格式指定。

    :param raw_input: 已整合的用户输入文本
    :param model_id: 格式 "llamacpp" 或 "llamacpp:http://地址:端口"
    :returns: 模型输出的 JSON 文本
    """
    if not model_id.startswith("llamacpp"):
        raise ValueError(f"一级模型标识必须为 llamacpp，当前: {model_id}")

    # 从 model_id 解析服务器地址（可选）
    server_url = LLAMACPP_SERVER_URL
    parts = model_id.split(":", 1)
    if len(parts) > 1 and parts[1].strip().startswith("http"):
        server_url = parts[1].strip()

    # 手动构建 Qwen chat 模板格式
    chat_prompt = (
        f"<|im_start|>system\n{_LLAMACPP_PRIMARY_PROMPT}<|im_end|>\n"
        f"<|im_start|>user\n{raw_input}<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )

    payload = {
        "prompt": chat_prompt,
        "temperature": 0.2,
        "n_predict": 4096,
        "stop": ["<|endoftext|>"],
        "stream": False,
        "cache_prompt": True,
    }

    try:
        data = _post_json(
            f"{server_url}/completion",
            payload,
            timeout=300,
        )
        content = data.get("content", "").strip()
        # 去除 think 标签
        content = content.replace("<think>", "").replace("</think>", "")

        # 如果输出含多个 JSON，提取最后一个完整的 JSON
        if "{" in content and "}" in content:
            brace_depth = 0
            last_json_end = -1
            last_json_start = -1
            for i in range(len(content) - 1, -1, -1):
                if content[i] == "}":
                    if brace_depth == 0:
                        last_json_end = i + 1
                    brace_depth += 1
                elif content[i] == "{":
                    brace_depth -= 1
                    if brace_depth == 0 and last_json_end != -1:
                        last_json_start = i
                        break
            if last_json_start != -1 and last_json_end != -1:
                content = content[last_json_start:last_json_end]

        # 对 JSON 中的隐私字段做模糊化处理（兜底：即使模型未遵守也不泄露精确值）
        try:
            parsed = json.loads(content)
            profile = parsed.get("用户画像摘要", "")
            if profile:
                # 模糊化具体年龄：28岁 → 20多岁，35岁 → 30多岁
                import re as _re
                profile = _re.sub(r"(\d+)岁", lambda m: str(int(int(m.group(1)) / 10) * 10) + "多岁", profile)
                # 模糊化具体身高体重：175cm、70kg → 删除精确数值
                profile = _re.sub(r"身高\d+cm[，,;；]?\s*", "", profile)
                profile = _re.sub(r"体重\d+kg[，,;；]?\s*", "", profile)
                parsed["用户画像摘要"] = profile.strip().rstrip("，,;；")
                content = json.dumps(parsed, ensure_ascii=False)
        except (json.JSONDecodeError, KeyError, TypeError):
            pass  # 非 JSON 或缺少字段时不处理

        logger.debug(
            "llamacpp 原始输出长度=%d, JSON=%s",
            len(content), content[:200] if content else "空",
        )
        return content

    except error.URLError as exc:
        raise RuntimeError(
            f"llama.cpp 请求失败，请确认 llama-server 已启动并可访问 {server_url}\n"
            f"启动命令参考: llama-server -m 模型路径 -ngl -1 --host 127.0.0.1 --port 11435\n"
            f"详细错误: {exc}"
        ) from exc
