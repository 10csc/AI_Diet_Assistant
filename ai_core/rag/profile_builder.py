"""
用户画像构建模块 —— 用户营养需求分析、画像融合及 RAG 上下文构建。

依赖于 knowledge_rules（规则/工具函数）、data_loader（知识库初始化）、
retriever（检索与评分）和 embedder（向量查询）。
"""

import json
from typing import Any, Optional

from .knowledge_rules import (
    QUERY_CATEGORY_HINTS,
    _augment_health_constraints,
    _build_season_context,
    _clean_cell,
    _dedupe_preserve_order,
    _extract_soft_preferences,
    _extract_state_emphasis,
    _parse_json_object,
    _parse_list_value,
    _stringify_value,
    _to_float,
)

from .data_loader import DEFAULT_XLS_PATH, ensure_knowledge_base

from .retriever import (
    _build_middle_layer_output,
    _format_retrieval_text,
    _retrieve_documents,
)


# ============================================================
# 用户画像构建
# ============================================================

def _estimate_bmi(personal_info: dict[str, Any]) -> tuple[Optional[float], str]:
    """根据身高体重估算 BMI 和状态。"""
    height_cm = _to_float(personal_info.get("height"))
    weight_kg = _to_float(personal_info.get("weight"))
    if not height_cm or not weight_kg:
        return None, "未知"
    height_m = height_cm / 100
    bmi = weight_kg / (height_m * height_m)
    if bmi < 18.5:
        return bmi, "偏瘦"
    if bmi < 24:
        return bmi, "正常"
    if bmi < 28:
        return bmi, "超重"
    return bmi, "肥胖"


def _estimate_standard_weight(personal_info: dict[str, Any], table: dict[str, Any]) -> Optional[float]:
    """从标准体重表估算用户标准体重。"""
    heights = table.get("heights", [])
    profiles = table.get("profiles", [])
    gender = _clean_cell(personal_info.get("gender"))
    age_value = _to_float(personal_info.get("age"))
    height_value = _to_float(personal_info.get("height"))
    if not gender or age_value is None or height_value is None or not heights or not profiles:
        return None

    same_gender = [item for item in profiles if item.get("gender") == gender]
    if not same_gender:
        return None
    profile = min(same_gender, key=lambda item: abs(float(item.get("age", 0)) - age_value))
    height_index = min(range(len(heights)), key=lambda idx: abs(heights[idx] - height_value))
    weights = profile.get("weights", [])
    if height_index >= len(weights):
        return None
    return weights[height_index]


def _build_deterministic_profile(
    user_input: str,
    personal_info: dict[str, Any],
    weather_info: dict[str, Any],
    kb: dict[str, Any],
) -> dict[str, Any]:
    """基于用户输入和个人信息构建确定性营养画像。"""
    combined_text = " ".join(
        str(item) for item in [user_input, personal_info.get("health", ""), personal_info.get("taste", "")]
    )
    target_nutrients: list[str] = []
    dietary_limits: list[str] = []
    retrieval_keywords: list[str] = []
    preferred_categories: list[str] = []
    body_notes: list[str] = []
    mental_notes: list[str] = []
    hard_constraints: list[str] = []
    soft_preferences: list[str] = []
    state_emphasis: list[str] = []
    season_context = _build_season_context(weather_info, user_input)

    bmi, bmi_status = _estimate_bmi(personal_info)
    ideal_weight = _estimate_standard_weight(personal_info, kb.get("standard_weight", {}))
    if bmi is not None:
        body_notes.append(f"BMI约为 {bmi:.1f}，当前属于{bmi_status}")
    if ideal_weight is not None and _to_float(personal_info.get("weight")) is not None:
        current_weight = float(_to_float(personal_info.get("weight")) or 0)
        weight_gap = current_weight - ideal_weight
        if abs(weight_gap) >= 2:
            direction = "高于" if weight_gap > 0 else "低于"
            body_notes.append(f"体重较标准体重{direction}约 {abs(weight_gap):.1f} kg")

    if bmi_status == "偏瘦":
        target_nutrients.extend(["蛋白质", "复合碳水", "铁"])
        retrieval_keywords.extend(["高蛋白", "能量补充", "易吸收"])
        hard_constraints.append("在控制疾病风险前提下兼顾能量补充")
    elif bmi_status in ("超重", "肥胖"):
        target_nutrients.extend(["蛋白质", "膳食纤维", "钾"])
        dietary_limits.extend(["控制高油高糖", "减少高能量密度食物"])
        retrieval_keywords.extend(["低脂", "高纤维", "高饱腹"])
        hard_constraints.append("优先控制总能量和高油高糖负担")

    keyword_rules = [
        (["感冒", "咳嗽", "免疫"], ["维生素C", "蛋白质"], [], ["清淡", "温热", "补水"], []),
        (["焦虑", "压力", "烦躁"], ["B族维生素", "镁", "蛋白质"], [], ["舒缓情绪", "稳定能量"], ["存在心理压力或情绪波动"]),
        (["失眠", "熬夜", "睡眠"], ["B族维生素", "镁", "蛋白质"], [], ["晚餐清淡", "避免刺激"], ["作息可能紊乱，需兼顾睡眠支持"]),
        (["健身", "增肌", "训练"], ["蛋白质", "复合碳水", "钾"], [], ["高蛋白", "训练恢复"], []),
        (["减脂", "减肥", "控卡"], ["蛋白质", "膳食纤维"], ["控制高脂高糖"], ["低脂", "高纤维"], []),
        (["便秘"], ["膳食纤维", "维生素C"], [], ["高纤维", "补水"], []),
        (["贫血"], ["铁", "维生素C", "蛋白质"], [], ["补铁", "促进吸收"], []),
        (["高血压"], ["钾", "镁"], ["控制钠"], ["低钠"], []),
        (["胃炎", "胃不舒服", "胃痛"], ["蛋白质", "复合碳水"], ["避免辛辣油炸"], ["软烂", "易消化"], []),
        (["糖尿病", "控糖"], ["膳食纤维", "蛋白质"], ["控制精制糖"], ["低GI", "稳定血糖"], []),
    ]
    for keywords, nutrients, limits, search_terms, mind_notes in keyword_rules:
        if any(keyword in combined_text for keyword in keywords):
            target_nutrients.extend(nutrients)
            dietary_limits.extend(limits)
            retrieval_keywords.extend(search_terms)
            mental_notes.extend(mind_notes)
            if keywords in (["高血压"],):
                hard_constraints.append("优先控制钠负担")

    _augment_health_constraints(combined_text, dietary_limits, hard_constraints, target_nutrients, retrieval_keywords)
    soft_preferences.extend(_extract_soft_preferences(user_input, personal_info, weather_info))
    state_emphasis.extend(_extract_state_emphasis(user_input, personal_info, weather_info))

    weather_now = weather_info.get("now", {}) if isinstance(weather_info, dict) else {}
    condition = str(weather_now.get("condition", ""))
    if "雨" in condition or "阴" in condition:
        retrieval_keywords.append("温热")
        soft_preferences.append("温热")
    if "热" in condition or (_to_float(weather_now.get("temperature")) or 0) >= 30:
        target_nutrients.append("维生素C")
        retrieval_keywords.extend(["补水", "清爽"])
        soft_preferences.extend(["清爽", "补水"])

    if season_context.get("season_keywords"):
        retrieval_keywords.extend(season_context["season_keywords"])
    if season_context.get("body_notes"):
        body_notes.extend(season_context["body_notes"])
    if season_context.get("term_preference"):
        soft_preferences.extend(season_context["term_preference"])
    if season_context.get("summary"):
        mental_notes.append(f"季节与节气倾向：{season_context['summary']}")

    for keyword, category in QUERY_CATEGORY_HINTS.items():
        if keyword in user_input or keyword in combined_text:
            preferred_categories.append(category)

    target_nutrients = _dedupe_preserve_order(target_nutrients)
    dietary_limits = _dedupe_preserve_order(dietary_limits)
    retrieval_keywords = _dedupe_preserve_order(retrieval_keywords)
    preferred_categories = _dedupe_preserve_order(preferred_categories)
    hard_constraints = _dedupe_preserve_order(hard_constraints)
    soft_preferences = _dedupe_preserve_order(soft_preferences)
    state_emphasis = _dedupe_preserve_order(state_emphasis)
    mental_status = "；".join(mental_notes) if mental_notes else "未发现明显心理风险描述，以稳定情绪和规律能量供给为主。"
    body_status = "；".join(body_notes) if body_notes else "体型信息有限，优先结合症状、目标和天气做营养推断。"

    profile_summary = []
    age = _clean_cell(personal_info.get("age"))
    gender = _clean_cell(personal_info.get("gender"))
    occupation = _clean_cell(personal_info.get("occupation"))
    if age or gender:
        profile_summary.append(f"{age or '未知年龄'}岁附近{gender or '未说明性别'}")
    if occupation:
        profile_summary.append(occupation)
    if personal_info.get("taste"):
        profile_summary.append(f"口味偏好：{personal_info.get('taste')}")
    if personal_info.get("health"):
        profile_summary.append(f"健康备注：{personal_info.get('health')}")

    return {
        "profile_summary": "，".join(profile_summary) or "用户画像信息有限，以当前对话需求为主。",
        "body_status": body_status,
        "mental_status": mental_status,
        "target_nutrients": target_nutrients,
        "dietary_limits": dietary_limits,
        "retrieval_keywords": retrieval_keywords,
        "preferred_categories": preferred_categories,
        "season_context": season_context,
        "hard_constraints": hard_constraints,
        "soft_preferences": soft_preferences,
        "state_emphasis": state_emphasis,
    }


# ============================================================
# 画像融合
# ============================================================

def _merge_preprocess_and_rules(
    preprocess_result: dict[str, Any],
    deterministic_profile: dict[str, Any],
) -> dict[str, Any]:
    """将预处理结果与确定性画像融合。"""
    merged = dict(deterministic_profile)
    for key in ("用户画像摘要", "身体状态分析", "心理状态分析"):
        if preprocess_result.get(key):
            if key == "用户画像摘要":
                merged["profile_summary"] = _stringify_value(preprocess_result.get(key))
            elif key == "身体状态分析":
                merged["body_status"] = _stringify_value(preprocess_result.get(key))
            elif key == "心理状态分析":
                merged["mental_status"] = _stringify_value(preprocess_result.get(key))
    merged["target_nutrients"] = _dedupe_preserve_order(
        deterministic_profile.get("target_nutrients", [])
        + _parse_list_value(preprocess_result.get("需重点关注营养素"))
    )
    merged["dietary_limits"] = _dedupe_preserve_order(
        deterministic_profile.get("dietary_limits", [])
        + _parse_list_value(preprocess_result.get("饮食限制"))
    )
    merged["retrieval_keywords"] = _dedupe_preserve_order(
        deterministic_profile.get("retrieval_keywords", [])
        + _parse_list_value(preprocess_result.get("检索关键词"))
        + _parse_list_value(preprocess_result.get("优化提示词"))
    )
    merged["hard_constraints"] = _dedupe_preserve_order(
        deterministic_profile.get("hard_constraints", [])
        + _parse_list_value(preprocess_result.get("饮食限制"))
    )
    merged["soft_preferences"] = _dedupe_preserve_order(
        deterministic_profile.get("soft_preferences", [])
        + _extract_soft_preferences(_stringify_value(preprocess_result.get("心理状态分析")))
    )
    merged["state_emphasis"] = _dedupe_preserve_order(
        deterministic_profile.get("state_emphasis", [])
        + _extract_state_emphasis(
            _stringify_value(preprocess_result.get("优化提示词")),
            _stringify_value(preprocess_result.get("心理状态分析")),
        )
    )
    return merged


# ============================================================
# 中间层输入构建
# ============================================================

def _build_middle_layer_input(nutrition_profile: dict[str, Any]) -> dict[str, Any]:
    """将营养画像转换为中间层输入格式。"""
    return {
        "user_state_summary": nutrition_profile.get("profile_summary", ""),
        "body_status": nutrition_profile.get("body_status", ""),
        "mental_status": nutrition_profile.get("mental_status", ""),
        "target_nutrients": nutrition_profile.get("target_nutrients", []),
        "dietary_limits": nutrition_profile.get("dietary_limits", []),
        "preferred_categories": nutrition_profile.get("preferred_categories", []),
        "retrieval_keywords": nutrition_profile.get("retrieval_keywords", []),
        "season_context": nutrition_profile.get("season_context", {}),
        "hard_constraints": nutrition_profile.get("hard_constraints", []),
        "soft_preferences": nutrition_profile.get("soft_preferences", []),
        "state_emphasis": nutrition_profile.get("state_emphasis", []),
    }


# ============================================================
# 顶层入口
# ============================================================

def build_rag_context(
    user_input: str,
    personal_info_text: str = "",
    weather_text: str = "",
    preprocess_result: Optional[dict[str, Any]] = None,
    xls_path: str = DEFAULT_XLS_PATH,
    top_k: int = 8,
) -> dict[str, Any]:
    """构建完整的 RAG 上下文（主入口）。"""
    kb = ensure_knowledge_base(xls_path)
    personal_info = _parse_json_object(personal_info_text)
    weather_info = _parse_json_object(weather_text)
    deterministic_profile = _build_deterministic_profile(user_input, personal_info, weather_info, kb)
    merged_profile = _merge_preprocess_and_rules(preprocess_result or {}, deterministic_profile)
    middle_layer_input = _build_middle_layer_input(merged_profile)
    middle_layer_output = _build_middle_layer_output(
        _retrieve_documents(kb, middle_layer_input, top_k=top_k)
    )
    retrieved_items = middle_layer_output.get("food_candidates", [])
    return {
        "nutrition_profile": merged_profile,
        "middle_layer_input": middle_layer_input,
        "middle_layer_output": middle_layer_output,
        "retrieved_items": retrieved_items,
        "retrieval_text": _format_retrieval_text(retrieved_items),
        "knowledge_base_summary": (
            f"食材条目 {kb.get('document_count', 0)} 条，"
            f"图谱分类 {len(kb.get('taxonomy', {}))} 个一级类，"
            f"包含标准体重参考表，向量库={kb.get('vector_store', 'unknown')}，"
            f"向量模型={kb.get('embedding_backend', 'unknown')}"
        ),
    }


def format_local_analysis(preprocess_result: dict[str, Any], rag_context: dict[str, Any]) -> str:
    """将 RAG 上下文格式化为可读的本地分析文本。"""
    nutrition_profile = rag_context.get("nutrition_profile", {})
    middle_layer_input = rag_context.get("middle_layer_input", {})
    middle_layer_output = rag_context.get("middle_layer_output", {})
    retrieved_items = rag_context.get("retrieved_items", [])
    sections = [
        ("用户画像摘要", _stringify_value(preprocess_result.get("用户画像摘要")) or nutrition_profile.get("profile_summary", "")),
        ("身体状态分析", _stringify_value(preprocess_result.get("身体状态分析")) or nutrition_profile.get("body_status", "")),
        ("心理状态分析", _stringify_value(preprocess_result.get("心理状态分析")) or nutrition_profile.get("mental_status", "")),
        ("需重点关注营养素", "、".join(nutrition_profile.get("target_nutrients", []))),
        ("饮食限制", "、".join(nutrition_profile.get("dietary_limits", [])) or "无明显限制"),
        ("RAG检索关键词", "、".join(nutrition_profile.get("retrieval_keywords", []))),
        ("知识库概况", rag_context.get("knowledge_base_summary", "")),
    ]
    lines = []
    for title, value in sections:
        if value:
            lines.append(f"{title}：{value}")
    if middle_layer_input:
        lines.append(f"中间层输入：{json.dumps(middle_layer_input, ensure_ascii=False)}")
    if retrieved_items:
        lines.append("知识库召回证据：")
        for item in retrieved_items[:5]:
            nutrient_summary = "；".join(item.get("nutrition_hits", [])) or "与当前需求相关"
            lines.append(
                f"- {item.get('name', '未知食材')} | "
                f"{item.get('image_category', '待分类')} / {item.get('image_subcategory', '其它')} | "
                f"{nutrient_summary} | 完整度={item.get('coverage_score', 0)} | 置信度={item.get('confidence', 0)}"
            )
    if middle_layer_output:
        lines.append(f"中间层输出：{json.dumps(middle_layer_output, ensure_ascii=False)}")
        if middle_layer_output.get("dish_constraint_policy"):
            lines.append(
                f"菜品软约束：{json.dumps(middle_layer_output.get('dish_constraint_policy'), ensure_ascii=False)}"
            )
    optimized_prompt = _stringify_value(preprocess_result.get("优化提示词"))
    if optimized_prompt:
        lines.append(f"优化提示词：{optimized_prompt}")
    return "\n".join(lines)


def build_secondary_prompt(
    user_input: str,
    preprocess_result: dict[str, Any],
    rag_context: dict[str, Any],
) -> str:
    """构建二级模型的提示词（含菜谱检索）。"""
    # 惰性导入 — 避免顶层循环依赖
    from .recipes import format_recipes_for_prompt, search_recipes

    nutrition_profile = rag_context.get("nutrition_profile", {})
    middle_layer_input = rag_context.get("middle_layer_input", {})
    middle_layer_output = rag_context.get("middle_layer_output", {})

    # 用一级模型产出的关键词检索内置菜谱库
    recipe_keywords = []
    for field in ("检索关键词", "优化提示词", "需重点关注营养素"):
        val = preprocess_result.get(field, [])
        if isinstance(val, list):
            recipe_keywords.extend(val)
        elif isinstance(val, str):
            recipe_keywords.append(val)
    matched_recipes = search_recipes(recipe_keywords, top_k=6)
    recipe_text = format_recipes_for_prompt(matched_recipes, max_count=3)

    sections = [
        f"原始用户需求：{user_input}",
        f"一级分析结果：{json.dumps(preprocess_result, ensure_ascii=False)}",
        f"规则增强后的用户营养需求：{json.dumps(nutrition_profile, ensure_ascii=False)}",
        f"中间层输入（营养需求）：{json.dumps(middle_layer_input, ensure_ascii=False)}",
        f"中间层输出（食材候选）：{json.dumps(middle_layer_output, ensure_ascii=False)}",
        f"菜品软约束策略：{json.dumps(middle_layer_output.get('dish_constraint_policy', {}), ensure_ascii=False)}",
        f"知识库召回结果：\n{rag_context.get('retrieval_text', '无')}",
        f"参考菜谱库匹配结果：\n{recipe_text if recipe_text else '无匹配菜谱，请根据食材候选自由发挥'}",
        (
            "任务要求：请结合用户画像、身体状态、心理状态、天气趋势、"
            "用户所需营养素与知识库召回证据，给出匹配的中国菜式推荐。"
        ),
    ]
    return "\n\n".join(sections)
