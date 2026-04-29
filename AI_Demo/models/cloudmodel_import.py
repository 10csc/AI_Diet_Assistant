import os
import json
import re
from urllib import error, request

# DeepSeek API 配置
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

# Ollama 云端配置（可改为远程地址，如 http://your-ollama-server:11434）
OLLAMA_CLOUD_URL = "http://localhost:11434"   # 若调用本地 Ollama 作为“云端”模型，可保留此地址

FIELD_ALIASES = {
    "具体菜名": ["具体菜名", "菜名", "推荐菜名", "菜品", "推荐菜品", "meal", "dish", "dish_name"],
    "所用主要食材": ["所用主要食材", "主要食材", "食材", "主要用料", "用料", "ingredients", "main_ingredients"],
    "烹饪方式": ["烹饪方式", "做法", "制作方式", "烹调方式", "cooking_method", "method"],
    "营养价值": ["营养价值", "营养分析", "营养说明", "营养特点", "nutrition", "nutritional_value"],
    "推荐理由": ["推荐理由", "推荐原因", "理由", "原因", "recommendation", "reason"],
}
PREFERRED_CONTAINER_KEYS = [
    "result", "data", "output", "answer", "response", "content",
    "menu", "recommendation", "dish", "meal", "payload"
]


def _post_json(url: str, payload: dict, headers: dict = None, timeout: int = 60) -> dict: # type: ignore
    data = json.dumps(payload).encode("utf-8")
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    req = request.Request(url, data=data, headers=req_headers, method="POST")
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _parse_model_id(model_id: str) -> tuple[str, str, str]:
    provider, sep, remainder = model_id.partition(":")
    if not sep or not remainder:
        raise ValueError(f"无效的模型ID: {model_id}")
    model, extra_sep, extra = remainder.partition("|")
    return provider, model, extra if extra_sep else ""


def _normalize_recommendation_fields(result) -> dict:
    """
    兼容模型返回的同义字段，并补全标准字段。
    """
    normalized = dict(result) if isinstance(result, dict) else {}
    candidate_dicts = _collect_candidate_dicts(result)
    source_text = _extract_source_text(result)
    for canonical, aliases in FIELD_ALIASES.items():
        value = _find_value_from_candidates(candidate_dicts, aliases)
        if not value and source_text:
            value = _find_value_from_text(source_text, aliases)
        normalized[canonical] = value if value else "信息暂缺"
    return normalized


def _extract_source_text(result) -> str:
    if isinstance(result, str):
        return result.strip()
    if isinstance(result, dict):
        text_parts = []
        for key in ("response", "content", "text", "answer", "message"):
            candidate = _coerce_field_value(result.get(key))
            if candidate:
                text_parts.append(candidate)
        return "\n".join(text_parts).strip()
    return ""


def _collect_candidate_dicts(result) -> list:
    parsed = _parse_possible_payload(result)
    dicts = []
    seen_ids = set()

    def visit(value):
        if isinstance(value, dict):
            identity = id(value)
            if identity in seen_ids:
                return
            seen_ids.add(identity)
            dicts.append(value)
            for key in PREFERRED_CONTAINER_KEYS:
                nested = value.get(key)
                if isinstance(nested, dict):
                    visit(nested)
            for nested in value.values():
                if isinstance(nested, dict):
                    visit(nested)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    visit(item)

    visit(parsed)
    return dicts


def _parse_possible_payload(result):
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        json_candidate = _extract_json_candidate(result)
        if json_candidate:
            try:
                return json.loads(json_candidate)
            except json.JSONDecodeError:
                return result
        return result
    return result


def _extract_json_candidate(text: str) -> str:
    content = text.strip()
    if not content:
        return ""

    code_block = re.search(r"```(?:json)?\s*([\s\S]*?)```", content, re.IGNORECASE)
    if code_block:
        block_text = code_block.group(1).strip()
        if block_text:
            return block_text

    if content.startswith("{") and content.endswith("}"):
        return content

    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1 and end > start:
        return content[start:end + 1]
    return ""


def _find_value_from_candidates(candidate_dicts: list, aliases: list) -> str:
    for candidate_dict in candidate_dicts:
        for key in aliases:
            candidate = _coerce_field_value(candidate_dict.get(key, ""))
            if candidate:
                return candidate
    return ""


def _find_value_from_text(text: str, aliases: list) -> str:
    alias_lookup = {alias.lower() for alias in aliases}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^[-*]\s*", "", line)
        line = re.sub(r"^\d+\.\s*", "", line)
        line = line.strip()
        if "：" in line:
            key, value = line.split("：", 1)
        elif ":" in line:
            key, value = line.split(":", 1)
        else:
            continue
        key = key.strip().strip("*").strip().lower()
        value = value.strip().strip("`* -")
        if key in alias_lookup and value:
            return value
    return ""


def _coerce_field_value(candidate) -> str:
    if isinstance(candidate, str):
        return candidate.strip()
    if isinstance(candidate, list):
        parts = []
        for item in candidate:
            text = _coerce_field_value(item)
            if text:
                parts.append(text)
        return "、".join(parts)
    if isinstance(candidate, (int, float)):
        return str(candidate)
    if isinstance(candidate, dict):
        for key in ("name", "title", "value", "text", "content", "description"):
            nested = _coerce_field_value(candidate.get(key))
            if nested:
                return nested
        return json.dumps(candidate, ensure_ascii=False)
    return ""


def preprocess_with_deepseek(raw_input: str, model_id: str) -> str:
    if not model_id.startswith("deepseek:"):
        raise ValueError(f"一级模型必须为 deepseek 模型，当前 model_id: {model_id}")

    provider, model, api_key = _parse_model_id(model_id)
    if provider != "deepseek":
        raise ValueError(f"不支持的一级模型提供商: {provider}")
    if not api_key:
        api_key = DEEPSEEK_API_KEY
    if not api_key:
        raise ValueError("DeepSeek API Key 不能为空")

    system_prompt = (
        "你是一个文本预处理助手。你的任务是：\n"
        "1. 接收三类输入：天气情况（非必需）、用户信息（非必需）、用户需求（必需）。\n"
        "2. 过滤掉用户信息与用户需求中的敏感内容（暴力、色情、政治等）。\n"
        "3. 将天气状况、用户信息和用户需求中涉及详细个人信息的内容整合并转换为不影响饮食需求分析准确度的模糊信息，确保用户隐私安全。\n"
        "4. 如果天气信息中包含未来预报（如 forecasts/indexes/alerts），需要综合当前与未来趋势来优化提示词，支持用户提前获取后续饮食建议。\n"
        "5. 输出中不要暴露具体日期、具体时刻、具体预报发布时间，只保留相对时序描述（如今天/近期/接下来）。\n"
        "6. 根据用户输入的内容，优化提示词，使其更适合用于后续的大模型处理。\n"
        "输出格式：只输出转化后的提示词文本，不要输出其他解释。\n"
        f"用户输入：{raw_input}\n"
    )

    payload = {
        "model": model or "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": raw_input}
        ],
        "temperature": 0.2
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
    }

    try:
        data = _post_json(DEEPSEEK_API_URL, payload, headers=headers, timeout=60)
        return data["choices"][0]["message"]["content"].strip()
    except (error.URLError, KeyError, IndexError, ValueError) as exc:
        raise RuntimeError(f"DeepSeek 请求失败: {exc}") from exc


def get_diet_recommendation(
    optimized_prompt: str,
    model_id: str = "",
    provider: str = "deepseek",
    model: str = None, # type: ignore
) -> dict:
    """
    调用不同云端模型生成饮食推荐

    :param optimized_prompt: 经过 Ollama 预处理后的提示词
    :param provider: 模型提供商，支持 "deepseek" 或 "ollama"
    :param model: 模型名称，若不提供则使用各提供商的默认模型
         - deepseek 默认: "deepseek-chat"
         - ollama 默认: "gpt-oss:120b-cloud" (或你已下载的任何模型)
    :return: 包含以下字段的字典：
             - 具体菜名
             - 所用主要食材
             - 烹饪方式
             - 营养价值
             - 推荐理由
    """
    api_key = DEEPSEEK_API_KEY
    ollama_url = OLLAMA_CLOUD_URL

    if model_id:
        provider, parsed_model, extra = _parse_model_id(model_id)
        model = parsed_model or model
        if provider == "deepseek" and extra:
            api_key = extra
        elif provider == "ollama" and extra:
            ollama_url = extra

    if provider == "deepseek":
        return _call_deepseek(optimized_prompt, model or "deepseek-chat", api_key)
    elif provider == "ollama":
        return _call_ollama_cloud(optimized_prompt, model or "gpt-oss:120b-cloud", ollama_url)
    else:
        raise ValueError(f"不支持的 provider: {provider}，请使用 'deepseek' 或 'ollama'")

def _call_deepseek(prompt: str, model: str, api_key: str) -> dict:
    """调用 DeepSeek API"""
    system_prompt = (
        "你是一个饮食分析助手，对话不记忆。输入内容包括处理后的用户输入（实时监控）。"
        "你有输出规则，以 json 格式输出，输出信息包括：具体菜名、所用主要食材、烹饪方式、营养价值、推荐理由。"
        "要根据用户输入的信息（包括天气、地区、用户心理和用户健康状况）具体分析后输出。"
        "主要查找中国菜式。"
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "response_format": {"type": "json_object"}
    }

    try:
        data = _post_json(DEEPSEEK_API_URL, payload, headers=headers, timeout=60)
        content = data["choices"][0]["message"]["content"]
        return _normalize_recommendation_fields(content)

    except (error.URLError, KeyError, IndexError, json.JSONDecodeError, ValueError) as e:
        print(f"DeepSeek API 调用失败: {e}")
        return _get_default_recommendation()

def _call_ollama_cloud(prompt: str, model: str, ollama_url: str) -> dict:
    """调用 Ollama 服务（可本地或远程）作为云端模型"""
    system_prompt = (
        "你是一个饮食分析助手。"
        "你必须以严格的 JSON 格式输出，不要输出任何其他文字。"
        "输出格式示例：\n"
        "{\n"
        '  "具体菜名": "菜名",\n'
        '  "所用主要食材": "食材列表",\n'
        '  "烹饪方式": "方式",\n'
        '  "营养价值": "营养说明",\n'
        '  "推荐理由": "理由"\n'
        "}\n"
        "根据用户输入（包括天气、地区、心理和健康状况）分析后输出中国菜式推荐。"
    )

    # 组合最终 prompt
    full_prompt = f"{system_prompt}\n\n用户输入：{prompt}\n\n请输出 JSON："

    payload = {
        "model": model,
        "prompt": full_prompt,
        "stream": False,
        "options": {
            "temperature": 0.5,
        }
    }

    try:
        data = _post_json(f"{ollama_url}/api/generate", payload, timeout=90)
        response_text = data.get("response", "").strip()
        return _normalize_recommendation_fields(response_text)

    except (error.URLError, json.JSONDecodeError, ValueError) as e:
        print(f"Ollama 云端模型调用失败: {e}")
        return _get_default_recommendation()

def _get_default_recommendation() -> dict:
    """降级默认推荐"""
    return {
        "具体菜名": "清蒸鲈鱼",
        "所用主要食材": "鲈鱼、姜、葱、蒸鱼豉油",
        "烹饪方式": "清蒸",
        "营养价值": "高蛋白、低脂肪，富含Omega-3",
        "推荐理由": "易于消化，适合各类体质，保留食材原味。"
    }
