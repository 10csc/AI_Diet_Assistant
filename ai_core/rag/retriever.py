"""
检索与评分模块 —— 文档检索、多维评分排序及检索结果格式化。

依赖于 knowledge_rules（常量/工具函数）和 embedder（ChromaDB 向量查询）。
"""

import json
from typing import Any

from .knowledge_rules import (
    CORE_CATEGORY_REQUIREMENTS,
    MEAT_CUT_RULES,
    NUTRIENT_FIELD_MAP,
    STATE_EMPHASIS_EQUIVALENTS,
    _clean_cell,
    _dedupe_preserve_order,
    _to_float,
)

from .embedder import _query_chroma_candidates


# ============================================================
# 核心检索函数
# ============================================================

def _retrieve_documents(kb: dict[str, Any], middle_layer_input: dict[str, Any], top_k: int) -> list[dict[str, Any]]:
    """根据中间层输入检索并排序知识库文档。"""
    query_text = " ".join(
        [
            middle_layer_input.get("user_state_summary", ""),
            middle_layer_input.get("body_status", ""),
            middle_layer_input.get("mental_status", ""),
            " ".join(middle_layer_input.get("target_nutrients", [])),
            " ".join(middle_layer_input.get("dietary_limits", [])),
            " ".join(middle_layer_input.get("retrieval_keywords", [])),
            " ".join(middle_layer_input.get("hard_constraints", [])),
            " ".join(middle_layer_input.get("soft_preferences", [])),
            " ".join(middle_layer_input.get("state_emphasis", [])),
            json.dumps(middle_layer_input.get("season_context", {}), ensure_ascii=False),
        ]
    )
    target_nutrients = middle_layer_input.get("target_nutrients", [])
    preferred_categories = set(middle_layer_input.get("preferred_categories", []))
    nutrient_stats = kb.get("nutrient_stats", {})
    doc_map = {doc.get("doc_id"): doc for doc in kb.get("documents", [])}
    vector_hits = _query_chroma_candidates(query_text, top_n=max(top_k * 8, 24))
    ranked_by_name: dict[str, dict[str, Any]] = {}

    for hit in vector_hits:
        doc = doc_map.get(hit.get("doc_id"))
        if not doc:
            continue
        nutrient_score, nutrition_hits, missing_relevant = _score_nutrients(doc, target_nutrients, nutrient_stats)
        category_score = 0.12 if doc.get("image_category") in preferred_categories else 0.0
        restriction_penalty, risk_notes = _score_restriction_penalty(
            doc, middle_layer_input.get("dietary_limits", []), nutrient_stats
        )
        seasonal_score = _score_seasonal_alignment(doc, middle_layer_input.get("season_context", {}))
        preference_score = _score_soft_preferences(doc, middle_layer_input.get("soft_preferences", []))
        balance_penalty, balance_notes = _score_health_mental_balance(
            doc,
            middle_layer_input.get("hard_constraints", []),
            middle_layer_input.get("soft_preferences", []),
        )
        state_penalty, state_notes = _score_item_state_penalty(
            doc,
            middle_layer_input.get("state_emphasis", []),
        )
        completeness_score = float(doc.get("coverage_score", 0))
        vector_score = float(hit.get("vector_score", 0))
        final_score = (
            vector_score * 0.46
            + nutrient_score * 0.26
            + category_score
            + seasonal_score * 0.08
            + preference_score * 0.07
            + completeness_score * 0.10
            - restriction_penalty
            - balance_penalty
            - state_penalty
        )
        if final_score <= 0:
            continue
        candidate = {
            "doc_id": doc.get("doc_id", ""),
            "name": doc.get("name", ""),
            "image_category": doc.get("image_category", "待分类"),
            "image_subcategory": doc.get("image_subcategory", "其它"),
            "major_category_group": doc.get("major_category_group", ""),
            "meat_cut_type": doc.get("meat_cut_type", ""),
            "dish_role_preference": doc.get("dish_role_preference", ""),
            "storage_state": doc.get("storage_state", ""),
            "source_sheet": doc.get("source_sheet", ""),
            "nutrition_hits": nutrition_hits,
            "match_reasons": _build_match_reasons(
                doc,
                vector_score,
                nutrient_score,
                category_score,
                seasonal_score,
                preference_score,
            ),
            "risk_notes": _dedupe_preserve_order(risk_notes + balance_notes + state_notes),
            "nutrition_snapshot": _build_nutrition_snapshot(doc),
            "coverage_score": round(completeness_score, 3),
            "confidence": round(min(max(final_score, 0.0), 1.0), 3),
            "available_fields": doc.get("available_fields", []),
            "missing_fields": doc.get("missing_fields", []),
            "missing_relevant_fields": missing_relevant,
            "seasonal_score": round(seasonal_score, 3),
            "preference_score": round(preference_score, 3),
        }
        dedupe_key = _clean_cell(doc.get("name"))
        previous = ranked_by_name.get(dedupe_key)
        if not previous or candidate["confidence"] > previous.get("confidence", 0):
            ranked_by_name[dedupe_key] = candidate

    ranked = sorted(ranked_by_name.values(), key=lambda item: item.get("confidence", 0), reverse=True)
    covered_ranked = _ensure_core_category_coverage(
        ranked,
        list(ranked_by_name.values()),
        top_k=top_k,
    )
    return covered_ranked[:top_k]


# ============================================================
# 评分函数
# ============================================================

def _score_nutrients(
    doc: dict[str, Any],
    target_nutrients: list[str],
    nutrient_stats: dict[str, Any],
) -> tuple[float, list[str], list[str]]:
    """计算食材与目标营养素的匹配度。"""
    if not target_nutrients:
        return 0.0, [], []
    score = 0.0
    matched = []
    missing_relevant = []
    considered = 0
    for nutrient in target_nutrients:
        field = NUTRIENT_FIELD_MAP.get(nutrient)
        if not field:
            continue
        raw_value = _to_float(doc.get(field))
        if raw_value is None:
            if field not in missing_relevant:
                missing_relevant.append(field)
            continue
        considered += 1
        if raw_value <= 0:
            continue
        max_value = float(nutrient_stats.get(field, 1.0))
        normalized = min(raw_value / max_value, 1.0)
        score += normalized
        matched.append(f"{nutrient}={raw_value}")
    if considered == 0:
        return 0.0, matched, missing_relevant
    return score / considered, matched, missing_relevant


def _score_restriction_penalty(
    doc: dict[str, Any],
    dietary_limits: list[str],
    nutrient_stats: dict[str, Any],
) -> tuple[float, list[str]]:
    """根据饮食限制计算惩罚分。"""
    penalty = 0.0
    risk_notes = []
    limit_text = " ".join(dietary_limits)
    sodium = _to_float(doc.get("sodium_mg"))
    fat = _to_float(doc.get("fat_g"))
    energy = _to_float(doc.get("energy_kcal"))
    carb = _to_float(doc.get("carb_g"))
    fiber = _to_float(doc.get("fiber_g"))
    cholesterol = _to_float(doc.get("cholesterol_mg"))
    doc_name = _clean_cell(doc.get("name"))
    category = _clean_cell(doc.get("image_category"))
    combined = " ".join([doc_name, category, _clean_cell(doc.get("image_subcategory"))])
    if "控制钠" in limit_text:
        if sodium is None:
            penalty += 0.02
            risk_notes.append("钠含量字段缺失，需谨慎")
        elif sodium > nutrient_stats.get("sodium_mg", 1.0) * 0.4:
            penalty += 0.08
            risk_notes.append("钠含量相对偏高")
    if any(keyword in limit_text for keyword in ["控制高脂高糖", "避免高脂肪高热量食物", "减少高能量密度食物"]):
        if fat is None:
            penalty += 0.02
            risk_notes.append("脂肪字段缺失，需谨慎")
        elif fat > nutrient_stats.get("fat_g", 1.0) * 0.35:
            penalty += 0.1
            risk_notes.append("脂肪含量相对偏高")
        if energy is None:
            penalty += 0.02
            risk_notes.append("能量字段缺失，需谨慎")
        elif energy > nutrient_stats.get("energy_kcal", 1.0) * 0.35:
            penalty += 0.08
            risk_notes.append("能量密度相对偏高")
    if any(keyword in limit_text for keyword in ["控制精制糖", "控制总糖摄入", "选择低GI食材"]):
        if any(keyword in combined for keyword in ["蛋糕", "甜点", "饮料", "汽水", "糖", "蜜", "炼乳"]):
            penalty += 0.16
            risk_notes.append("不符合控糖或低GI限制")
        if carb is not None and fiber is not None and carb > 0:
            fiber_ratio = fiber / carb
            if "选择低GI食材" in limit_text and fiber_ratio < 0.06:
                penalty += 0.06
                risk_notes.append("碳水占比高且纤维偏低，低GI优势不足")
        elif "选择低GI食材" in limit_text:
            penalty += 0.02
            risk_notes.append("缺少足够字段判断低GI倾向")
    if "避免苦瓜" in limit_text and "苦瓜" in combined:
        penalty += 0.25
        risk_notes.append("命中明确忌口")
    if "糖尿病" in limit_text or any(keyword in limit_text for keyword in ["控制总糖摄入", "选择低GI食材"]):
        if cholesterol is not None and cholesterol > nutrient_stats.get("cholesterol_mg", 1.0) * 0.45:
            penalty += 0.04
            risk_notes.append("胆固醇相对偏高，需控制总负担")
    return penalty, risk_notes


def _score_item_state_penalty(doc: dict[str, Any], state_emphasis: list[str]) -> tuple[float, list[str]]:
    """根据食材加工/储存状态计算惩罚分。"""
    penalty = 0.0
    notes = []
    role = _clean_cell(doc.get("dish_role_preference"))
    storage_state = _clean_cell(doc.get("storage_state"))
    if role == "配菜优先":
        penalty += 0.035
        notes.append("该条目更适合作为配菜或汤品参考")
    if storage_state and not _is_state_emphasized(doc, state_emphasis):
        penalty += 0.04
        notes.append("默认略微降低干制、脱水或储藏态条目的常规优先级")
    return penalty, notes


def _is_state_emphasized(doc: dict[str, Any], state_emphasis: list[str]) -> bool:
    """判断食材的状态是否与用户强调的状态一致。"""
    if not state_emphasis:
        return False
    combined = " ".join(
        [
            _clean_cell(doc.get("name")),
            _clean_cell(doc.get("image_category")),
            _clean_cell(doc.get("image_subcategory")),
            _clean_cell(doc.get("storage_state")),
            _clean_cell(doc.get("dish_role_preference")),
        ]
    )
    for keyword in state_emphasis:
        if keyword and keyword in combined:
            return True
        for alias in STATE_EMPHASIS_EQUIVALENTS.get(keyword, []):
            if alias in combined:
                return True
    return False


def _score_seasonal_alignment(doc: dict[str, Any], season_context: dict[str, Any]) -> float:
    """计算食材的季节匹配度。"""
    if not isinstance(season_context, dict):
        return 0.0
    score = 0.0
    season = _clean_cell(season_context.get("season"))
    term_name = _clean_cell(season_context.get("term"))
    category = _clean_cell(doc.get("image_category"))
    subcategory = _clean_cell(doc.get("image_subcategory"))
    combined = " ".join([category, subcategory, _clean_cell(doc.get("name"))])
    if season == "春" and any(token in combined for token in ["蔬菜", "菠菜", "菜心", "豆"]):
        score += 0.08
    elif season == "夏" and any(token in combined for token in ["蔬菜", "瓜", "豆", "菌"]):
        score += 0.08
    elif season == "秋" and any(token in combined for token in ["菌", "薯", "根菜", "梨", "百合"]):
        score += 0.08
    elif season == "冬" and any(token in combined for token in ["豆", "菌", "禽", "畜", "薯"]):
        score += 0.08
    if term_name:
        term_keywords = season_context.get("term_keywords", [])
        if any(keyword and keyword in combined for keyword in term_keywords):
            score += 0.04
    return min(score, 0.12)


def _score_soft_preferences(doc: dict[str, Any], soft_preferences: list[str]) -> float:
    """计算食材与用户口味偏好的匹配度。"""
    if not soft_preferences:
        return 0.0
    combined = " ".join(
        [
            _clean_cell(doc.get("name")),
            _clean_cell(doc.get("image_category")),
            _clean_cell(doc.get("image_subcategory")),
            _clean_cell(doc.get("raw_category")),
            _clean_cell(doc.get("raw_class")),
        ]
    )
    score = 0.0
    for pref in soft_preferences:
        if not pref:
            continue
        if pref in combined:
            score += 0.05
    if any(pref in ("温热", "汤羹", "软烂") for pref in soft_preferences):
        if any(token in combined for token in ["粥", "羹", "汤", "面", "豆腐", "蛋"]):
            score += 0.05
    return min(score, 0.12)


def _score_health_mental_balance(
    doc: dict[str, Any],
    hard_constraints: list[str],
    soft_preferences: list[str],
) -> tuple[float, list[str]]:
    """计算健康约束与情绪偏好的平衡惩罚。"""
    penalty = 0.0
    notes = []
    doc_name = _clean_cell(doc.get("name"))
    lower_constraints = "".join(hard_constraints)
    if "控制精制糖" in lower_constraints or "控制总糖摄入" in lower_constraints or "糖尿病" in lower_constraints:
        if any(keyword in doc_name for keyword in ["蛋糕", "糖", "蜜", "汽水", "甜饮"]):
            penalty += 0.18
            notes.append("虽可能贴合口味，但不优先满足控糖健康约束")
        if any(keyword in doc_name for keyword in ["肝", "胆", "肥肉", "油炸"]):
            penalty += 0.08
            notes.append("营养密度虽高，但与当前健康约束和日常成菜场景不够匹配")
    if "避免苦瓜" in lower_constraints and "苦瓜" in doc_name:
        penalty += 0.25
        notes.append("命中明确忌口，不建议优先推荐")
    if any(pref in ("甜口", "辣味") for pref in soft_preferences) and any(
        keyword in doc_name for keyword in ["辣条", "炸鸡", "薯片"]
    ):
        penalty += 0.08
        notes.append("仅贴合情绪口味，但不利于整体健康目标")
    if any(keyword in doc_name for keyword in ["脱水", "风干", "烤", "腌", "罐头"]):
        penalty += 0.04
        notes.append("更偏储存或加工形态，适合作为参考而非当日首选主食材")
    if doc.get("meat_cut_type") == "高脂部位":
        penalty += 0.05
        notes.append("该肉类部位脂肪负担相对更高")
    if doc.get("meat_cut_type") == "内脏":
        penalty += 0.05
        notes.append("该肉类属于内脏类，适合作为补充参考而非默认首选")
    return penalty, notes


# ============================================================
# 分类覆盖保障
# ============================================================

def _ensure_core_category_coverage(
    ranked: list[dict[str, Any]],
    fallback_pool: list[dict[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
    """确保前 top_k 结果覆盖所有核心分类组。"""
    if not ranked:
        return ranked
    selected = ranked[:top_k]
    selected_names = {_clean_cell(item.get("name")) for item in selected}
    coverage = {_clean_cell(item.get("major_category_group")) for item in selected}
    pool = ranked[top_k:] + [item for item in fallback_pool if item not in ranked[top_k:]]
    for group in CORE_CATEGORY_REQUIREMENTS:
        if group in coverage:
            continue
        for candidate in pool:
            if _clean_cell(candidate.get("major_category_group")) != group:
                continue
            candidate_name = _clean_cell(candidate.get("name"))
            if not candidate_name or candidate_name in selected_names:
                continue
            selected.append(candidate)
            selected_names.add(candidate_name)
            coverage.add(group)
            break
    selected.sort(key=lambda item: item.get("confidence", 0), reverse=True)
    return selected


# ============================================================
# 检索结果格式化
# ============================================================

def _format_retrieval_text(retrieved_items: list[dict[str, Any]]) -> str:
    """将检索结果格式化为可读文本。"""
    if not retrieved_items:
        return "未检索到明确食材证据，可退化为常规经验推荐。"
    lines = []
    for index, item in enumerate(retrieved_items, start=1):
        lines.append(
            f"{index}. 食材={item.get('name', '未知')}；"
            f"分类={item.get('image_category', '待分类')}/{item.get('image_subcategory', '其它')}；"
            f"命中营养={','.join(item.get('nutrition_hits', [])) or '综合匹配'}；"
            f"完整度={item.get('coverage_score', 0)}；"
            f"置信度={item.get('confidence', 0)}；"
            f"营养摘要={item.get('nutrition_snapshot', '暂无')}"
        )
    return "\n".join(lines)


def _build_nutrition_snapshot(doc: dict[str, Any]) -> str:
    """构建食材营养概览摘要。"""
    fields = [
        ("能量", "energy_kcal"),
        ("蛋白质", "protein_g"),
        ("脂肪", "fat_g"),
        ("膳食纤维", "fiber_g"),
        ("碳水", "carb_g"),
        ("维生素C", "vitamin_c_mg"),
        ("钙", "calcium_mg"),
        ("铁", "iron_mg"),
        ("钠", "sodium_mg"),
    ]
    parts = []
    for label, field in fields:
        value = doc.get(field)
        text = _clean_cell(value)
        if text and text != "0":
            parts.append(f"{label}={text}")
    return "，".join(parts[:5]) or "暂无营养概览"


def _build_match_reasons(
    doc: dict[str, Any],
    vector_score: float,
    nutrient_score: float,
    category_score: float,
    seasonal_score: float = 0.0,
    preference_score: float = 0.0,
) -> list[str]:
    """构建食材匹配原因说明。"""
    reasons = []
    if vector_score >= 0.5:
        reasons.append("与当前营养需求语义接近")
    if nutrient_score >= 0.35:
        reasons.append("关键营养素命中度较高")
    if category_score > 0:
        reasons.append("符合分类偏好")
    if seasonal_score > 0:
        reasons.append("符合当前季节或节气饮食倾向")
    if preference_score > 0:
        reasons.append("在健康范围内兼顾口味或情绪偏好")
    if _clean_cell(doc.get("meat_cut_type")) in ("瘦肉", "禽类优质部位", "海鲜优质蛋白"):
        reasons.append("肉类部位更适合作为主菜主蛋白来源")
    if _clean_cell(doc.get("dish_role_preference")) == "配菜优先":
        reasons.append("更适合作为汤品或配菜参考")
    if float(doc.get("coverage_score", 0)) >= 0.7:
        reasons.append("营养字段较完整")
    return reasons or ["综合匹配当前需求"]


# ============================================================
# 中间层输出构建
# ============================================================

def _build_middle_layer_output(food_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """从检索结果构建中间层输出。"""
    return {
        "food_candidates": food_candidates,
        "candidate_count": len(food_candidates),
        "output_description": "依据用户所需营养、分类偏好和缺失值处理后的食材候选列表",
        "dish_constraint_policy": _build_dish_constraint_policy(food_candidates),
        "category_coverage_summary": _build_category_coverage_summary(food_candidates),
    }


def _build_dish_constraint_policy(food_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """根据候选食材构建菜品软约束策略。"""
    core_candidates = []
    reference_candidates = []
    side_dish_candidates = []
    for candidate in food_candidates:
        name = _clean_cell(candidate.get("name"))
        if not name:
            continue
        if candidate.get("dish_role_preference") == "配菜优先" and len(side_dish_candidates) < 4:
            side_dish_candidates.append(name)
        if candidate.get("confidence", 0) >= 0.34 and len(core_candidates) < 3:
            core_candidates.append(name)
        elif len(reference_candidates) < 5:
            reference_candidates.append(name)
    return {
        "policy": "soft_constraint",
        "core_candidates": core_candidates,
        "reference_candidates": reference_candidates,
        "side_dish_candidates": side_dish_candidates,
        "guidelines": [
            "优先围绕高置信度候选食材或其同类替代食材组织菜品",
            "主菜必须优先使用肉禽鱼蛋豆奶中的高置信度候选，避免只生成汤或轻配菜",
            "汤品和成品条目优先作为配菜参考；若配菜本身已经是成品菜或汤品，不必再额外为它搭配子配菜",
            "至少参考1到2个核心候选，但不要机械拼接所有候选食材",
            "允许补充少量常见配菜和调味食材，使菜品更自然",
            "如果候选食材不适合直接成菜，可继承其营养方向而不是强行入菜",
        ],
    }


def _build_category_coverage_summary(food_candidates: list[dict[str, Any]]) -> dict[str, list[str]]:
    """构建分类覆盖总结。"""
    summary: dict[str, list[str]] = {}
    for candidate in food_candidates:
        group = _clean_cell(candidate.get("major_category_group"))
        if not group:
            continue
        names = summary.setdefault(group, [])
        name = _clean_cell(candidate.get("name"))
        if name and name not in names:
            names.append(name)
    return summary
