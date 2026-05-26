"""
隐私模糊化共享模块

对用户个人信息进行脱敏处理，确保模型不接触精确隐私值。
所有路径的隐私模糊逻辑统一于此，避免重复实现。
"""

import json
import re
from typing import Any, Optional


def _parse_float_value(value: Any) -> Optional[float]:
    """安全解析浮点数值"""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _parse_int_value(value: Any) -> Optional[int]:
    """安全解析整数值"""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def blur_personal_info(personal_info: str) -> str:
    """
    将 personal_info JSON 中的隐私字段替换为模糊化描述。
    - 具体年龄（28）→ 年龄段（20多岁）
    - 具体身高体重（175cm / 70kg）→ BMI 等级（偏瘦/正常/超重/肥胖）

    在验证通过后、构建模型输入前调用，确保模型不接触原始精确值。
    """
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


def blur_profile_text(profile_text: str) -> str:
    """
    对模型输出中的用户画像摘要做正则兜底模糊化。
    当模型未遵守隐私约束时，作为最后防线脱敏。

    - 具体年龄：28岁 → 20多岁，35岁 → 30多岁
    - 具体身高体重：删除精确数值
    """
    if not profile_text:
        return ""

    text = profile_text
    # 模糊化具体年龄
    text = re.sub(
        r"(\d+)岁",
        lambda m: str(int(int(m.group(1)) / 10) * 10) + "多岁",
        text
    )
    # 删除精确身高体重描述
    text = re.sub(r"身高\d+cm[，,;；]?\s*", "", text)
    text = re.sub(r"体重\d+kg[，,;；]?\s*", "", text)
    return text.strip().rstrip("，,；")
