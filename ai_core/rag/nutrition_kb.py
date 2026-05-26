"""
向后兼容层 —— 从子模块重新导出所有公共 API。

原 nutrition_kb.py（1878 行）已拆分为以下子模块：
  - knowledge_rules.py  : 静态常量、映射规则及工具函数
  - data_loader.py      : XLS 解析、缓存及知识库索引构建
  - embedder.py         : ChromaDB 向量嵌入与集合管理
  - retriever.py        : 检索、评分与排序
  - profile_builder.py  : 用户营养画像构建与 RAG 上下文

本文件保持与原有 `from .nutrition_kb import ...` 完全兼容。
"""

import os

os.environ.setdefault("ANONYMIZED_TELEMETRY", "FALSE")

# ---------------------------------------------------------------------------
# knowledge_rules — 静态常量 / 规则 / 工具函数
# ---------------------------------------------------------------------------
from .knowledge_rules import (                          # noqa: F401, E402
    KB_VERSION,
    CHROMA_COLLECTION_NAME,
    TERM_KEYWORDS,
    SEASON_RULES,
    SOFT_PREFERENCE_KEYWORDS,
    KEY_COMPLETENESS_FIELDS,
    CANONICAL_FIELDS,
    NUTRIENT_FIELD_MAP,
    IMAGE_CATEGORY_RULES,
    QUERY_CATEGORY_HINTS,
    CORE_CATEGORY_REQUIREMENTS,
    MEAT_CUT_RULES,
    SOUP_OR_PREPARED_KEYWORDS,
    STORAGE_STATE_KEYWORDS,
    EXPLICIT_STATE_HINTS,
    STATE_EMPHASIS_EQUIVALENTS,
    # 工具函数
    _clean_cell,
    _to_float,
    _dedupe_preserve_order,
    _coerce_value,
    _stringify_value,
    _parse_json_object,
    _parse_list_value,
    _normalize_header,
    _decode_process_output,
    _tokenize,
    _vectorize_text,
    _cosine_similarity,
    # 规则函数
    _season_from_month,
    _build_season_context,
    _extract_soft_preferences,
    _extract_state_emphasis,
    _augment_health_constraints,
)

# ---------------------------------------------------------------------------
# data_loader — 文件路径 / XLS 导出 / 索引构建
# ---------------------------------------------------------------------------
from .data_loader import (                              # noqa: F401, E402
    BASE_DIR,
    PROJECT_ROOT,
    DATA_DIR,
    WORKBOOK_CACHE_PATH,
    INDEX_CACHE_PATH,
    CHROMA_DIR,
    DEFAULT_XLS_PATH,
    # 函数
    _export_workbook_to_json,
    _load_or_export_workbook,
    _build_index_from_workbook,
    _parse_food_sheet,
    _parse_standard_weight_sheet,
    _build_nutrient_stats,
    _match_image_category,
    _build_search_text,
    _calculate_data_coverage,
    _resolve_major_category_group,
    _detect_meat_cut_type,
    _detect_dish_role_preference,
    _detect_storage_state,
    _build_vector_document,
    ensure_knowledge_base,
)

# ---------------------------------------------------------------------------
# embedder — ChromaDB / 向量 embedding
# ---------------------------------------------------------------------------
from .embedder import (                                 # noqa: F401, E402
    HASH_EMBED_DIM,
    SEMANTIC_MODEL_NAME,
    SEMANTIC_MODEL_DEVICE,
    SEMANTIC_MODEL_PATH,
    ALLOW_REMOTE_MODEL_DOWNLOAD,
    # 类
    _HashEmbeddingFunction,
    _SentenceTransformerEmbeddingFunction,
    # 函数
    _embed_text_hash,
    _get_embedding_function,
    _current_embedding_backend,
    _semantic_model_reference,
    _local_semantic_model_available,
    _ensure_chroma_collection,
    _build_chroma_metadata,
    _query_chroma_candidates,
)

# ---------------------------------------------------------------------------
# retriever — 检索 / 评分 / 排序
# ---------------------------------------------------------------------------
from .retriever import (                                # noqa: F401, E402
    _retrieve_documents,
    _score_nutrients,
    _score_restriction_penalty,
    _score_item_state_penalty,
    _is_state_emphasized,
    _score_seasonal_alignment,
    _score_soft_preferences,
    _score_health_mental_balance,
    _format_retrieval_text,
    _build_nutrition_snapshot,
    _build_match_reasons,
    _ensure_core_category_coverage,
    _build_middle_layer_output,
    _build_dish_constraint_policy,
    _build_category_coverage_summary,
)

# ---------------------------------------------------------------------------
# profile_builder — 用户画像 / RAG 上下文 / 提示词构建
# ---------------------------------------------------------------------------
from .profile_builder import (                          # noqa: F401, E402
    _build_deterministic_profile,
    _merge_preprocess_and_rules,
    _build_middle_layer_input,
    _estimate_bmi,
    _estimate_standard_weight,
    build_rag_context,
    format_local_analysis,
    build_secondary_prompt,
)
