# ai_core/main.py
import argparse
import json
import sys
import os
import time
import logging
from datetime import datetime
from typing import Any, Optional
from models.ollama_import import preprocess_with_ollama
from models.cloudmodel_import import get_diet_recommendation, preprocess_with_deepseek
from models.llamacpp_import import preprocess_with_llamacpp
from rag import build_rag_context, build_secondary_prompt, format_local_analysis

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# ---- 日志配置（使用标准库，无需外部依赖） ----
logger = logging.getLogger("diet_assistant")
logger.setLevel(logging.INFO)

# 文件日志 — 统一记录到 service.log
_file_handler = logging.FileHandler(
    os.path.join(LOG_DIR, "service.log"),
    encoding="utf-8",
    delay=False,
)
_file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))
logger.addHandler(_file_handler)

# 控制台日志 — 输出到 stderr，不影响 stdout 的 JSON 结果
_console_handler = logging.StreamHandler(sys.stderr)
_console_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
))
logger.addHandler(_console_handler)


# 设置标准输出编码（兼容性处理）
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore
except Exception:
    import codecs
    if sys.stdout.encoding != 'UTF-8':
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer)
    if sys.stderr.encoding != 'UTF-8':
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer)


# ---- 一级模型预处理函数注册表（扩展模型供应商时只需在此添加） ----
PREPROCESSOR_MAP = {
    "ollama:": preprocess_with_ollama,
    "deepseek:": preprocess_with_deepseek,
    "llamacpp:": preprocess_with_llamacpp,
}

INTERRUPT_CODE_SPEECHLESS = "speechless"
INTERRUPT_IMAGE_URL = "/image/speechless.webp"


# ---- 工具函数 ----


def save_to_jsonl(record: dict) -> None:
    """
    保存一条记录到 JSONL 日志文件。
    会自动脱敏 model_id 中的 API Key（格式 provider:model|key → provider:model|***）。

    :param record: 包含所有待保存字段的字典（timestamp 由本函数自动补充）
    """
    import re

    def _mask_api_key(value: str) -> str:
        """脱敏 model_id 中的 API Key"""
        if not isinstance(value, str):
            return value
        return re.sub(r"\|(sk-[a-zA-Z0-9]+)$", r"|***", value)

    for key in ("primary_model_id", "secondary_model_id"):
        if key in record:
            record[key] = _mask_api_key(record[key])

    today_str = datetime.now().strftime("%Y-%m-%d")
    file_path = os.path.join(LOG_DIR, f"{today_str}.jsonl")
    record["timestamp"] = datetime.now().isoformat()
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


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


def load_request_payload(request_file: str) -> dict:
    with open(request_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("request_file 内容必须为 JSON 对象")
    return data


def _relative_period_label(index: int) -> str:
    labels = ["近期", "接下来", "后续", "再后续"]
    if index < len(labels):
        return labels[index]
    return f"后续第{index + 1}阶段"


def sanitize_weather_payload(weather_text: str) -> str:
    """
    天气脱敏：
    - 保留天气趋势能力（now/forecasts/indexes/alerts）
    - 去除具体日期和具体时间信息，避免暴露精确时刻
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


def _blur_personal_info(personal_info: str) -> str:
    """
    将 personal_info JSON 中的隐私字段替换为模糊化描述。
    - 具体年龄（28）→ 年龄段（20多岁）
    - 具体身高体重（175cm / 70kg）→ BMI 等级（偏瘦/正常/超重/肥胖）

    在验证通过后、构建模型输入前调用，确保模型不接触原始精确值。
    """
    import re as _re
    try:
        info = json.loads(personal_info) if isinstance(personal_info, str) else dict(personal_info)
    except (TypeError, json.JSONDecodeError):
        return personal_info
    if not isinstance(info, dict):
        return personal_info

    # 模糊化年龄（5 岁一个阶段）
    age_raw = info.get("age")
    age_val = _parse_int_value(age_raw)
    if age_val is not None and 1 <= age_val <= 120:
        start = (age_val // 5) * 5
        info["age_range"] = f"{start}-{start + 4}岁"
        info.pop("age", None)

    # 模糊化身高体重 → BMI 等级
    height_cm = _parse_float_value(info.get("height"))
    weight_kg = _parse_float_value(info.get("weight"))
    if height_cm and weight_kg and height_cm > 0:
        bmi = weight_kg / ((height_cm / 100) ** 2)
        if bmi < 18.5:
            bmi_label = "偏瘦"
        elif bmi < 24:
            bmi_label = "正常"
        elif bmi < 28:
            bmi_label = "超重"
        else:
            bmi_label = "肥胖"
        info["body_type"] = bmi_label
        info.pop("height", None)
        info.pop("weight", None)

    return json.dumps(info, ensure_ascii=False)


def resolve_request_args(args) -> dict:
    payload = load_request_payload(args.request_file) if args.request_file else {}

    resolved = {
        "user_input": payload.get("user_input", args.user_input),
        "personal_info": payload.get("personal_info", args.personal_info),
        "weather": payload.get("weather", args.weather),
        "primary_model_id": payload.get("primary_model_id", args.primary_model_id),
        "secondary_model_id": payload.get("secondary_model_id", args.secondary_model_id),
        "use_secondary": payload.get("use_secondary", args.use_secondary),
        "conversation_id": payload.get("conversation_id", ""),
        "conversation_title": payload.get("conversation_title", ""),
        "conversation_context": payload.get("conversation_context", ""),
        "recipe_profile": payload.get("recipe_profile", []),
    }

    if not resolved["user_input"]:
        raise ValueError("缺少 user_input")
    if not resolved["primary_model_id"]:
        raise ValueError("缺少 primary_model_id")

    resolved["weather"] = sanitize_weather_payload(resolved["weather"])
    resolved["use_secondary"] = bool(resolved["use_secondary"])
    return resolved


def _call_with_retry(
    func,
    args,
    kwargs=None,
    max_retries: int = 2,
    base_delay: float = 1.0,
):
    """
    带指数退避重试的通用调用封装。

    当被调用函数抛出异常时，按 1s → 2s → 4s 间隔重试。
    所有重试均失败后，抛出最后一次捕获的异常。

    :param func: 被调用的可调用对象
    :param args: 位置参数列表
    :param kwargs: 关键字参数字典
    :param max_retries: 最大重试次数（不含首次尝试），默认 2
    :param base_delay: 初始等待秒数，默认 1.0
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
                logger.warning(
                    "调用 %s.%s 失败（第 %d 次），%.1fs 后重试: %s",
                    func.__module__,
                    func.__name__,
                    attempt + 1,
                    delay,
                    exc,
                )
                time.sleep(delay)
    assert last_exc is not None
    logger.error(
        "调用 %s.%s 已重试 %d 次，全部失败: %s",
        func.__module__,
        func.__name__,
        max_retries,
        last_exc,
    )
    raise last_exc


def preprocess_input(raw_input: str, primary_model_id: str) -> str:
    """根据模型 ID 前缀查找对应的预处理函数并调用"""
    for prefix, func in PREPROCESSOR_MAP.items():
        if primary_model_id.startswith(prefix):
            logger.info(
                "使用一级模型: %s → %s.%s",
                primary_model_id,
                func.__module__,
                func.__name__,
            )
            return func(raw_input, model_id=primary_model_id)
    raise ValueError(f"不支持的一级模型: {primary_model_id}")


def _extract_json_candidate(text: str) -> str:
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


def _to_string_list(value) -> list[str]:
    if isinstance(value, list):
        result = []
        for item in value:
            text = str(item).strip()
            if text:
                result.append(text)
        return result
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return []
        parts = candidate.replace("；", "，").replace("、", "，").split("，")
        return [part.strip() for part in parts if part.strip()]
    return []


def _load_personal_info_object(personal_info_text: str) -> dict[str, Any]:
    if not personal_info_text:
        return {}
    try:
        payload = json.loads(personal_info_text)
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_float_value(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_int_value(value: Any) -> Optional[int]:
    parsed = _parse_float_value(value)
    if parsed is None:
        return None
    if parsed != int(parsed):
        return None
    return int(parsed)


def _normalize_gender_value(value: Any) -> str:
    text = str(value or "").strip().lower()
    gender_map = {
        "男": "男",
        "男性": "男",
        "male": "男",
        "m": "男",
        "女": "女",
        "女性": "女",
        "female": "女",
        "f": "女",
    }
    return gender_map.get(text, "")


def validate_personal_info_fields(personal_info_text: str) -> list[str]:
    profile = _load_personal_info_object(personal_info_text)
    invalid_fields: list[str] = []

    age_raw = profile.get("age")
    age_value = _parse_int_value(age_raw)
    if str(age_raw).strip():
        if age_value is None or not (1 <= age_value <= 120):
            invalid_fields.append("age")

    gender_raw = profile.get("gender")
    if str(gender_raw).strip():
        if not _normalize_gender_value(gender_raw):
            invalid_fields.append("gender")

    height_raw = profile.get("height")
    height_value = _parse_float_value(height_raw)
    if str(height_raw).strip():
        if height_value is None or not (50 <= height_value <= 260):
            invalid_fields.append("height")

    weight_raw = profile.get("weight")
    weight_value = _parse_float_value(weight_raw)
    if str(weight_raw).strip():
        if weight_value is None or not (10 <= weight_value <= 500):
            invalid_fields.append("weight")

    return invalid_fields


def build_interrupt_result(code: str, invalid_fields: Optional[list[str]] = None) -> dict[str, Any]:
    return {
        "interrupt_code": code,
        "interrupt_image": INTERRUPT_IMAGE_URL,
        "invalid_fields": invalid_fields or [],
        "local_output": "",
        "cloud_output": {
            "mode": "interrupt",
            "interrupt_code": code,
            "image_url": INTERRUPT_IMAGE_URL,
        },
    }


def parse_preprocess_result(raw_output: str) -> dict:
    if raw_output.strip().lower() == INTERRUPT_CODE_SPEECHLESS:
        return {"interrupt_code": INTERRUPT_CODE_SPEECHLESS}

    json_candidate = _extract_json_candidate(raw_output)
    if json_candidate:
        try:
            payload = json.loads(json_candidate)
            if isinstance(payload, dict) and str(payload.get("interrupt_code", "")).strip():
                return {"interrupt_code": str(payload.get("interrupt_code", "")).strip()}
        except json.JSONDecodeError:
            pass

    expected_keys = [
        "用户画像摘要",
        "身体状态分析",
        "心理状态分析",
        "需重点关注营养素",
        "饮食限制",
        "检索关键词",
        "优化提示词",
    ]
    parsed = {}
    if json_candidate:
        try:
            payload = json.loads(json_candidate)
            if isinstance(payload, dict):
                parsed = payload
        except json.JSONDecodeError:
            parsed = {}

    if not parsed:
        for line in raw_output.splitlines():
            if "：" in line:
                key, value = line.split("：", 1)
            elif ":" in line:
                key, value = line.split(":", 1)
            else:
                continue
            key = key.strip().strip("*")
            value = value.strip()
            if key in expected_keys and value:
                parsed[key] = value

    result = {}
    for key in expected_keys:
        value = parsed.get(key, [])
        if key in ("需重点关注营养素", "饮食限制", "检索关键词"):
            result[key] = _to_string_list(value)
        else:
            result[key] = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

    # ---- 隐私模糊化（对所有后端输出生效） ----
    import re as _re
    for _key in ("用户画像摘要", "身体状态分析", "优化提示词"):
        _val = result.get(_key, "")
        if isinstance(_val, str) and _val:
            # 模糊化具体年龄：28岁 → 20多岁
            _val = _re.sub(r"(\d+)岁", lambda m: str(int(int(m.group(1)) / 10) * 10) + "多岁", _val)
            # 模糊化具体身高体重
            _val = _re.sub(r"身高\d+\.?\d*cm[，,;；]?\s*", "", _val)
            _val = _re.sub(r"体重\d+\.?\d*kg[，,;；]?\s*", "", _val)
            result[_key] = _val.strip().rstrip("，,;；")

    if not result["优化提示词"]:
        result["优化提示词"] = raw_output.strip()
    if not result["用户画像摘要"]:
        result["用户画像摘要"] = "用户画像信息已结合输入进行模糊化整理。"
    if not result["身体状态分析"]:
        result["身体状态分析"] = "需结合个人信息、天气与当前诉求做综合饮食判断。"
    if not result["心理状态分析"]:
        result["心理状态分析"] = "未识别到明确情绪风险时，以稳定能量供给与可持续饮食体验为主。"
    return result


def main():
    parser = argparse.ArgumentParser(description="饮食推荐助手 - 支持两级模型调用")
    parser.add_argument("--request_file", type=str, default="", help="请求 JSON 文件路径")
    parser.add_argument("--user_input", type=str, default="", help="用户对话框输入（必需）")
    parser.add_argument(
        "--personal_info", type=str, default="", help="用户个人信息（可选，JSON或纯文本）"
    )
    parser.add_argument("--weather", type=str, default="", help="天气数据（可选，JSON或纯文本）")
    parser.add_argument(
        "--primary_model_id",
        type=str,
        default="",
        help="一级模型ID，格式：provider:model_name，例如 ollama:deepseek-r1:7b 或 llamacpp:all（llamacpp 支持 :gpu_layers 后缀）",
    )
    parser.add_argument(
        "--secondary_model_id",
        type=str,
        default="",
        help="二级模型ID，格式同primary_model_id，例如 deepseek:deepseek-chat",
    )
    parser.add_argument(
        "--use_secondary",
        action="store_true",
        help="是否使用二级模型进行饮食推荐，不加此参数则只返回一级模型预处理结果",
    )

    args = parser.parse_args()

    try:
        resolved = resolve_request_args(args)

        logger.info(
            "开始处理请求  primary_model=%s  use_secondary=%s",
            resolved["primary_model_id"],
            resolved["use_secondary"],
        )

        invalid_fields = validate_personal_info_fields(resolved["personal_info"])
        if invalid_fields:
            logger.warning("用户个人信息校验未通过，已截断一级模型调用: %s", ",".join(invalid_fields))
            interrupt_result = build_interrupt_result(INTERRUPT_CODE_SPEECHLESS, invalid_fields)
            save_to_jsonl(
                {
                    "user_input": resolved["user_input"],
                    "personal_info": resolved["personal_info"],
                    "weather": resolved["weather"],
                    "primary_model_id": resolved["primary_model_id"],
                    "secondary_model_id": resolved["secondary_model_id"],
                    "use_secondary": resolved["use_secondary"],
                    "conversation_id": resolved["conversation_id"],
                    "conversation_title": resolved["conversation_title"],
                    "conversation_context": resolved["conversation_context"],
                    "interrupt_code": INTERRUPT_CODE_SPEECHLESS,
                    "invalid_fields": invalid_fields,
                    "local_output": interrupt_result["local_output"],
                    "cloud_output": interrupt_result["cloud_output"],
                }
            )
            print(json.dumps(interrupt_result, ensure_ascii=False, indent=2))
            return

        # 模糊化年龄和身高体重（验证通过后、模型输入前）
        resolved["personal_info"] = _blur_personal_info(resolved["personal_info"])

        # 构建完整原始输入
        raw_input = build_raw_input(
            resolved["user_input"],
            resolved["personal_info"],
            resolved["weather"],
            resolved["conversation_context"],
        )

        # 步骤1：使用一级模型预处理（带自动重试）
        raw_preprocess_output = _call_with_retry(
            preprocess_input, [raw_input, resolved["primary_model_id"]]
        )
        preprocess_result = parse_preprocess_result(raw_preprocess_output)
        if preprocess_result.get("interrupt_code") == INTERRUPT_CODE_SPEECHLESS:
            logger.warning("一级模型判定输入无效，已截断后续流程")
            interrupt_result = build_interrupt_result(INTERRUPT_CODE_SPEECHLESS)
            save_to_jsonl(
                {
                    "user_input": resolved["user_input"],
                    "personal_info": resolved["personal_info"],
                    "weather": resolved["weather"],
                    "primary_model_id": resolved["primary_model_id"],
                    "secondary_model_id": resolved["secondary_model_id"],
                    "use_secondary": resolved["use_secondary"],
                    "conversation_id": resolved["conversation_id"],
                    "conversation_title": resolved["conversation_title"],
                    "conversation_context": resolved["conversation_context"],
                    "preprocess_raw_output": raw_preprocess_output,
                    "preprocess_result": preprocess_result,
                    "interrupt_code": INTERRUPT_CODE_SPEECHLESS,
                    "local_output": interrupt_result["local_output"],
                    "cloud_output": interrupt_result["cloud_output"],
                }
            )
            print(json.dumps(interrupt_result, ensure_ascii=False, indent=2))
            return
        rag_context = build_rag_context(
            resolved["user_input"],
            resolved["personal_info"],
            resolved["weather"],
            preprocess_result=preprocess_result,
        )
        local_output = format_local_analysis(preprocess_result, rag_context)
        secondary_prompt = build_secondary_prompt(
            resolved["user_input"],
            preprocess_result,
            rag_context,
        )

        # 将菜品偏好画像（赞/踩历史）附加到二级模型的提示词中
        recipe_profile = resolved.get("recipe_profile", [])
        if recipe_profile and isinstance(recipe_profile, list) and len(recipe_profile) > 0:
            profile_text = json.dumps(recipe_profile, ensure_ascii=False)
            secondary_prompt += (
                f"\n\n用户历史菜品反馈（用于了解用户口味偏好）：{profile_text}\n"
                "请参考用户的历史反馈调整推荐，避免推荐用户踩过的菜品，优先推荐用户赞过的类似菜品。"
            )

        if resolved["use_secondary"] and resolved["secondary_model_id"]:
            # 步骤2：使用二级模型生成饮食推荐（带自动重试）
            cloud_output = _call_with_retry(
                get_diet_recommendation,
                [secondary_prompt],
                {"model_id": resolved["secondary_model_id"]},
            )
        else:
            cloud_output = {"mode": "only_local", "optimized_prompt": local_output}

        logger.info("处理完成")

        # 保存历史日志
        save_to_jsonl(
            {
                "user_input": resolved["user_input"],
                "personal_info": resolved["personal_info"],
                "weather": resolved["weather"],
                "primary_model_id": resolved["primary_model_id"],
                "secondary_model_id": resolved["secondary_model_id"],
                "use_secondary": resolved["use_secondary"],
                "conversation_id": resolved["conversation_id"],
                "conversation_title": resolved["conversation_title"],
                "conversation_context": resolved["conversation_context"],
                "preprocess_raw_output": raw_preprocess_output,
                "preprocess_result": preprocess_result,
                "rag_context": rag_context,
                "local_output": local_output,
                "cloud_output": cloud_output,
            }
        )

        result = {"local_output": local_output, "cloud_output": cloud_output}
        print(json.dumps(result, ensure_ascii=False, indent=2))

    except Exception as exc:
        logger.exception("请求处理异常")  # 自动打印完整的 traceback
        error_result = {
            "error": str(exc),
            "local_output": "",
            "cloud_output": None,
        }
        print(json.dumps(error_result, ensure_ascii=False, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
