"""
校验与中断模块 —— 用户个人信息校验、中断结果构建。
"""

import json
from typing import Any, Optional

from privacy import _parse_int_value, _parse_float_value


INTERRUPT_CODE_SPEECHLESS = "speechless"
INTERRUPT_IMAGE_URL = "/image/speechless.webp"


def _load_personal_info_object(personal_info_text: str) -> dict[str, Any]:
    if not personal_info_text:
        return {}
    try:
        payload = json.loads(personal_info_text)
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize_gender_value(value: Any) -> str:
    text = str(value or "").strip().lower()
    gender_map = {
        "男": "男", "男性": "男", "male": "男", "m": "男",
        "女": "女", "女性": "女", "female": "女", "f": "女",
    }
    return gender_map.get(text, "")


def validate_personal_info_fields(personal_info_text: str) -> list[str]:
    """
    校验个人信息字段（age/gender/height/weight）是否在合理范围内。
    返回非法字段名列表，空列表表示全部通过。
    """
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
