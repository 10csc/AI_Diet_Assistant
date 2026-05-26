"""
模型输出解析模块 —— 将 LLM 原始输出解析为结构化结果。

对一级模型的输出做 JSON 提取、字段清洗、隐私兜底模糊化。
"""

import json
import re
from typing import Any

from utils import extract_json_candidate, to_string_list


def parse_preprocess_result(raw_output: str) -> dict:
    """
    解析一级模型的原始输出为结构化的预处理结果字典。

    支持 JSON 格式和纯文本格式两套解析路径。
    对所有输出中的文本字段做隐私兜底模糊化。
    """
    interrupt_code_speechless = "speechless"

    if raw_output.strip().lower() == interrupt_code_speechless:
        return {"interrupt_code": interrupt_code_speechless}

    json_candidate = extract_json_candidate(raw_output)
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
            result[key] = to_string_list(value)
        else:
            result[key] = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

    # 清理空值占位
    for key in expected_keys:
        val = result.get(key, "")
        if val in ("[]", "{}", "", "null"):
            result[key] = ""

    # 隐私兜底模糊化
    for _key in ("用户画像摘要", "身体状态分析", "优化提示词"):
        _val = result.get(_key, "")
        if isinstance(_val, str) and _val:
            _val = re.sub(r"(\d+)岁", lambda m: str(int(int(m.group(1)) / 10) * 10) + "多岁", _val)
            _val = re.sub(r"身高\d+\.?\d*cm[，,;；]?\s*", "", _val)
            _val = re.sub(r"体重\d+\.?\d*kg[，,;；]?\s*", "", _val)
            result[_key] = _val.strip().rstrip("，,;；")

    # 兜底默认值
    if not result["优化提示词"]:
        result["优化提示词"] = raw_output.strip()
    if not result["用户画像摘要"]:
        result["用户画像摘要"] = "用户画像信息已结合输入进行模糊化整理。"
    if not result["身体状态分析"]:
        result["身体状态分析"] = "需结合个人信息、天气与当前诉求做综合饮食判断。"
    if not result["心理状态分析"]:
        result["心理状态分析"] = "未识别到明确情绪风险时，以稳定能量供给与可持续饮食体验为主。"
    return result
