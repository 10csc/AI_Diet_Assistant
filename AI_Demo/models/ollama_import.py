import json
from urllib import error, request
from .prompt_templates import PRIMARY_ANALYSIS_PROMPT

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

    system_prompt = f"{PRIMARY_ANALYSIS_PROMPT}\n用户输入：{raw_input}\n"

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
