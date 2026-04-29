import json
from urllib import error, request

OLLAMA_BASE_URL = "http://localhost:11434"  # 本地Ollama服务地址


def _post_json(url: str, payload: dict, timeout: int = 60):
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return request.urlopen(req, timeout=timeout)

def preprocess_with_ollama(raw_input: str, model_id: str) -> str:
    """
    使用指定的本地Ollama模型处理原始输入，返回优化后的提示词（纯文本）
    :param raw_input: 已整合的用户对话、个人信息、天气的完整文本
    :param model_id: 模型ID，格式 "ollama:模型名"，例如 "ollama:deepseek-r1:7b"
    :return: 预处理后的提示词
    """
    # 解析模型ID，提取模型名称
    if not model_id.startswith("ollama:"):
        raise ValueError(f"一级模型必须为 ollama 本地模型，当前 model_id: {model_id}")
    model_name = model_id.split(":", 1)[1]  # 去掉 "ollama:" 前缀

    system_prompt = (
        "你是一个文本预处理助手。你的任务是：\n"
        "1. 接收三类输入：天气情况（非必需）、用户信息（非必需）、用户需求（必需）。\n"
        "2. 过滤掉用户信息与用户需求中的敏感内容（暴力、色情、政治等）。\n"
        "3. 将天气状况、用户信息和用户需求中涉及详细个人信息的内容整合并转换为不影响饮食需求分析准确度的模糊信息，确保用户隐私安全。\n"
        "   例如：年龄21岁替换为20~25岁，但性别无需模糊处理。姓名、手机号、邮箱等与饮食需求无关的信息应该去除，有关饮食且涉及具体隐私的数据（如体重/IBM/病史等）因适当模糊处理。\n"
        "4. 如果天气信息中包含未来预报（如 forecasts/indexes/alerts），需要综合当前与未来趋势来优化提示词，支持用户提前获取后续饮食建议。\n"
        "5. 输出中不要暴露具体日期、具体时刻、具体预报发布时间，只保留相对时序描述（如今天/近期/接下来）。\n"
        "6. 根据用户输入的内容，优化提示词，使其更适合用于后续的大模型处理。\n"
        "输出格式：只输出转化后的提示词文本，不要输出其他解释。（当前限制为最高优先级）\n"
        f"用户输入：{raw_input}\n"
    )

    payload = {
        "model": model_name,
        "prompt": system_prompt,
        "stream": True,
        "options": {
            "temperature": 0.2,
        }
    }

    full_response = ""
    try:
        with _post_json(f"{OLLAMA_BASE_URL}/api/generate", payload) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    if "response" in chunk:
                        full_response += chunk["response"]
                    if chunk.get("done", False):
                        break
                except json.JSONDecodeError:
                    continue
    except error.URLError as exc:
        raise RuntimeError(f"Ollama 请求失败: {exc}") from exc

    return full_response.strip()
