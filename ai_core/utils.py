"""
工具函数模块 —— 通用、可复用的辅助函数。

包含：输入净化、JSONL 日志、重试封装、JSON 提取、天气脱敏等。
"""

import json
import os
import re
import time
from datetime import datetime
from typing import Any, Optional


# ---- 输入净化 ----

def sanitize_user_input(text: str) -> str:
    """
    净化用户输入，防止 prompt injection 攻击。
    过滤常见注入模式，限制输入长度。
    """
    if not text:
        return text
    text = text[:2000]
    injection_patterns = [
        r'(?i)ignore\s+(all\s+)?(previous|prior|above|system)\s+(instructions?|prompts?|directives?)',
        r'(?i)forget\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?)',
        r'忽略(之前|上面|系统|所有)的?(指令|提示|prompt)',
        r'(?i)you\s+are\s+now\s+',
        r'(?i)act\s+as\s+(a|an)\s+',
        r'(?i)system\s*(prompt|message|instruction)\s*[:：]',
        r'(?i)new\s+instructions?\s*[:：]',
        r'(?i)\[system\].*\[/system\]',
        r'(?i)<system>.*</system>',
    ]
    for pattern in injection_patterns:
        text = re.sub(pattern, '[内容已过滤]', text)
    return text


# ---- JSONL 日志 ----

def save_to_jsonl(record: dict, log_dir: str) -> None:
    """
    保存一条记录到 JSONL 日志文件。
    会自动脱敏 model_id 中的 API Key。
    """
    def _mask_api_key(value: str) -> str:
        if not isinstance(value, str):
            return value
        return re.sub(r"\|(sk-[a-zA-Z0-9]+)$", r"|***", value)

    def _blur_log_text(value: str) -> str:
        if not isinstance(value, str):
            return value
        value = re.sub(r'(年龄["\'：: ]*|"age"["\'：: ]*)\d+', r'\1*', value)
        value = re.sub(r'(身高["\'：: ]*|"height"["\'：: ]*)\d+', r'\1*', value)
        value = re.sub(r'(体重["\'：: ]*|"weight"["\'：: ]*)\d+', r'\1*', value)
        return value

    for key in ("primary_model_id", "secondary_model_id"):
        if key in record:
            record[key] = _mask_api_key(record[key])
    for key in ("user_input", "personal_info"):
        if key in record:
            record[key] = _blur_log_text(record[key])

    today_str = datetime.now().strftime("%Y-%m-%d")
    file_path = os.path.join(log_dir, f"{today_str}.jsonl")
    record["timestamp"] = datetime.now().isoformat()
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---- 重试封装 ----

def call_with_retry(
    func,
    args,
    kwargs=None,
    max_retries: int = 2,
    base_delay: float = 1.0,
    logger=None,
):
    """
    带指数退避重试的通用调用封装。
    当被调用函数抛出异常时，按 1s → 2s → 4s 间隔重试。
    """
    if kwargs is None:
        kwargs = {}
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = base_delay * (2**attempt)
                if logger:
                    logger.warning(
                        "调用 %s.%s 失败（第 %d 次），%.1fs 后重试: %s",
                        func.__module__, func.__name__, attempt + 1, delay, exc,
                    )
                time.sleep(delay)
    if logger:
        logger.error(
            "调用 %s.%s 已重试 %d 次，全部失败: %s",
            func.__module__, func.__name__, max_retries, last_exc,
        )
    raise last_exc  # type: ignore


# ---- JSON 提取 ----

def extract_json_candidate(text: str) -> str:
    content = text.strip()
    if not content:
        return ""
    if content.startswith("{") and content.endswith("}"):
        return content
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1 and end > start:
        return content[start:end + 1]
    return ""


def to_string_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return []
        parts = candidate.replace("；", "，").replace("、", "，").split("，")
        return [part.strip() for part in parts if part.strip()]
    return []


def load_request_payload(request_file: str) -> dict:
    with open(request_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("request_file 内容必须为 JSON 对象")
    return data


def build_raw_input(
    user_input: str,
    personal_info: str = "",
    weather: str = "",
    conversation_context: str = "",
) -> str:
    """将多个可选部分组合成完整的原始输入文本"""
    parts = []
    if conversation_context:
        parts.append(f"历史对话上下文：{conversation_context}")
    if user_input:
        parts.append(f"用户对话框输入：{user_input}")
    if personal_info:
        parts.append(f"用户个人信息：{personal_info}")
    if weather:
        parts.append(f"天气数据：{weather}")
    return "\n".join(parts) if parts else ""


# ---- 天气脱敏 ----

def _relative_period_label(index: int) -> str:
    labels = ["近期", "接下来", "后续", "再后续"]
    return labels[index] if index < len(labels) else f"后续第{index + 1}阶段"


def sanitize_weather_payload(weather_text: str) -> str:
    """
    天气脱敏：保留趋势信息，去除具体日期时间。
    """
    if not weather_text:
        return weather_text
    try:
        weather_obj = json.loads(weather_text)
    except (TypeError, json.JSONDecodeError):
        return weather_text
    if not isinstance(weather_obj, dict):
        return weather_text

    now_obj = weather_obj.get("now")
    if isinstance(now_obj, dict):
        now_obj["uptime"] = "近期"

    forecasts = weather_obj.get("forecasts")
    if isinstance(forecasts, list):
        for idx, item in enumerate(forecasts):
            if not isinstance(item, dict):
                continue
            item.pop("date", None)
            item.pop("week", None)
            item["period"] = _relative_period_label(idx)

    return json.dumps(weather_obj, ensure_ascii=False, separators=(",", ":"))
