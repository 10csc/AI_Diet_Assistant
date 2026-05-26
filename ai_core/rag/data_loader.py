"""
数据加载模块 —— XLS 解析、工作簿缓存及知识库索引构建。

依赖于 knowledge_rules（常量/工具函数）和 embedder（ChromaDB 集合管理）。
"""

import json
import logging
import os
import re
import subprocess
import tempfile
from typing import Any

logger = logging.getLogger(__name__)

from .knowledge_rules import (
    KB_VERSION,
    CANONICAL_FIELDS,
    IMAGE_CATEGORY_RULES,
    KEY_COMPLETENESS_FIELDS,
    NUTRIENT_FIELD_MAP,
    CORE_CATEGORY_REQUIREMENTS,
    MEAT_CUT_RULES,
    SOUP_OR_PREPARED_KEYWORDS,
    STORAGE_STATE_KEYWORDS,
    _clean_cell,
    _coerce_value,
    _decode_process_output,
    _dedupe_preserve_order,
    _normalize_header,
    _to_float,
    _tokenize,
    _vectorize_text,
)

from .embedder import _ensure_chroma_collection

# ============================================================
# 文件路径常量
# ============================================================

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(BASE_DIR, "data", "knowledge_base")
WORKBOOK_CACHE_PATH = os.path.join(DATA_DIR, "nutrition_workbook_cache.json")
INDEX_CACHE_PATH = os.path.join(DATA_DIR, "nutrition_vector_index.json")
CHROMA_DIR = os.path.join(DATA_DIR, "chroma_db")
DEFAULT_XLS_PATH = os.path.join(PROJECT_ROOT, "data", "食材营养.xls")


# ============================================================
# XLS 导出与缓存
# ============================================================

def _export_workbook_via_powershell(xls_path: str) -> dict[str, Any]:
    """通过 PowerShell COM 接口将 XLS 文件导出为 JSON。"""
    if not os.path.exists(xls_path):
        raise FileNotFoundError(f"未找到食材营养表: {xls_path}")

    escaped_path = xls_path.replace("'", "''")
    script = f"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$path = '{escaped_path}'
$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false
try {{
    $wb = $excel.Workbooks.Open($path)
    $result = @()
    foreach ($ws in $wb.Worksheets) {{
        $used = $ws.UsedRange
        $values = $used.Value2
        $rows = @()
        for ($r = 1; $r -le $used.Rows.Count; $r++) {{
            $row = @()
            for ($c = 1; $c -le $used.Columns.Count; $c++) {{
                $cellValue = $values[$r, $c]
                if ($null -eq $cellValue) {{
                    $cellText = ''
                }} else {{
                    $cellText = [string]$cellValue
                }}
                $row += $cellText
            }}
            $rows += ,@($row)
        }}
        $result += [PSCustomObject]@{{
            name = [string]$ws.Name
            rows = @($rows)
        }}
    }}
    $wb.Close($false)
    $result | ConvertTo-Json -Depth 8 -Compress
}} finally {{
    $excel.Quit()
}}
"""
    ps1_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".ps1", delete=False, encoding="utf-8"
        ) as f:
            f.write(script)
            ps1_path = f.name
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "RemoteSigned", "-File", ps1_path],
            capture_output=True,
            check=False,
        )
    finally:
        if ps1_path and os.path.exists(ps1_path):
            os.unlink(ps1_path)

    stdout_text = _decode_process_output(completed.stdout)
    stderr_text = _decode_process_output(completed.stderr)
    if completed.returncode != 0:
        message = (stderr_text or stdout_text).strip()
        raise RuntimeError(f"导出 xls 失败: {message}")
    payload = json.loads((stdout_text or "").strip() or "[]")
    if isinstance(payload, dict):
        payload = [payload]
    return {"sheets": payload}


def _export_workbook_via_xlrd(xls_path: str) -> dict[str, Any]:
    """通过 xlrd 库解析 XLS 文件（跨平台后备方案）。"""
    try:
        import xlrd
    except ImportError:
        raise RuntimeError("xlrd 未安装，无法解析 XLS 文件: pip install xlrd")

    wb = xlrd.open_workbook(xls_path)
    sheets = []
    for sheet_name in wb.sheet_names():
        ws = wb.sheet_by_name(sheet_name)
        rows = []
        for r in range(ws.nrows):
            row = [str(ws.cell_value(r, c)) if ws.cell_type(r, c) != 0 else ""
                   for c in range(ws.ncols)]
            rows.append(row)
        sheets.append({"name": sheet_name, "rows": rows})
    return {"sheets": sheets}


def _export_workbook_to_json(xls_path: str) -> dict[str, Any]:
    """
    将 XLS 文件导出为 JSON。

    优先尝试 PowerShell COM（Windows），失败则尝试 xlrd（跨平台）。
    若均失败则使用已有缓存 JSON。
    """
    if not os.path.exists(xls_path):
        raise FileNotFoundError(f"未找到食材营养表: {xls_path}")

    # 尝试 PowerShell COM
    try:
        return _export_workbook_via_powershell(xls_path)
    except (FileNotFoundError, RuntimeError, subprocess.SubprocessError) as e:
        logger.warning("PowerShell XLS 导出失败，尝试 xlrd 后备: %s", e)

    # 尝试 xlrd
    try:
        return _export_workbook_via_xlrd(xls_path)
    except (ImportError, RuntimeError) as e:
        logger.warning("xlrd 后备也失败: %s", e)

    # 尝试读取已有缓存
    if os.path.exists(WORKBOOK_CACHE_PATH):
        logger.info("使用已有缓存文件: %s", WORKBOOK_CACHE_PATH)
        with open(WORKBOOK_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    raise RuntimeError(f"无法解析 XLS 文件（PowerShell 和 xlrd 均失败）: {xls_path}")


def _load_or_export_workbook(xls_path: str) -> dict[str, Any]:
    """加载工作簿缓存，若不存在则从 XLS 导出。"""
    if os.path.exists(WORKBOOK_CACHE_PATH):
        with open(WORKBOOK_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    workbook_data = _export_workbook_to_json(xls_path)
    with open(WORKBOOK_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(workbook_data, f, ensure_ascii=False, indent=2)
    return workbook_data


# ============================================================
# 知识库索引构建
# ============================================================

def _build_index_from_workbook(workbook_data: dict[str, Any]) -> dict[str, Any]:
    """从工作簿数据构建知识库索引。"""
    sheets = workbook_data.get("sheets", [])
    sheet_map = {sheet.get("name", ""): sheet.get("rows", []) for sheet in sheets if isinstance(sheet, dict)}
    food_docs = []
    food_docs.extend(_parse_food_sheet(sheet_map.get("食物成份表", []), source_sheet="食物成份表", header_index=1, take_columns=20))
    food_docs.extend(_parse_food_sheet(sheet_map.get("新食物成份表", []), source_sheet="新食物成份表", header_index=0, take_columns=21))
    standard_weight = _parse_standard_weight_sheet(sheet_map.get("标准体重表", []))

    nutrient_stats = _build_nutrient_stats(food_docs)
    for index, doc in enumerate(food_docs, start=1):
        category, subcategory = _match_image_category(doc)
        doc["image_category"] = category
        doc["image_subcategory"] = subcategory
        doc["major_category_group"] = _resolve_major_category_group(category)
        doc["meat_cut_type"] = _detect_meat_cut_type(doc)
        doc["dish_role_preference"] = _detect_dish_role_preference(doc)
        doc["storage_state"] = _detect_storage_state(doc)
        doc["search_text"] = _build_search_text(doc)
        doc["token_vector"] = dict(_vectorize_text(doc["search_text"]))
        doc["doc_id"] = f"food_{index:05d}"
        doc["vector_document"] = _build_vector_document(doc)
        available_fields, missing_fields, coverage_score = _calculate_data_coverage(doc)
        doc["available_fields"] = available_fields
        doc["missing_fields"] = missing_fields
        doc["coverage_score"] = coverage_score

    taxonomy = {key: list(value.keys()) for key, value in IMAGE_CATEGORY_RULES.items()}
    return {
        "kb_version": KB_VERSION,
        "document_count": len(food_docs),
        "documents": food_docs,
        "standard_weight": standard_weight,
        "nutrient_stats": nutrient_stats,
        "taxonomy": taxonomy,
        "vector_store": "chroma",
        "embedding_backend": "pending",
    }


def _parse_food_sheet(
    rows: list[list[Any]],
    source_sheet: str,
    header_index: int,
    take_columns: int,
) -> list[dict[str, Any]]:
    """解析食物成份表的一个 sheet。"""
    if len(rows) <= header_index:
        return []
    raw_headers = [_normalize_header(cell) for cell in rows[header_index][:take_columns]]
    headers = [CANONICAL_FIELDS.get(header, "") for header in raw_headers]
    docs = []
    for raw_row in rows[header_index + 1:]:
        cells = list(raw_row[:take_columns])
        if not cells:
            continue
        name = _clean_cell(cells[0 if source_sheet == "新食物成份表" else 1])
        if not name:
            continue
        doc = {
            "source_sheet": source_sheet,
            "name": name,
        }
        for index, canonical in enumerate(headers):
            if not canonical:
                continue
            doc[canonical] = _coerce_value(cells[index] if index < len(cells) else "")
        doc["name"] = name
        docs.append(doc)
    return docs


def _parse_standard_weight_sheet(rows: list[list[Any]]) -> dict[str, Any]:
    """解析标准体重表。"""
    if len(rows) < 3:
        return {"heights": [], "profiles": []}
    heights = []
    for cell in rows[1][1:]:
        value = _to_float(cell)
        if value is not None:
            heights.append(int(value))
    profiles = []
    for raw_row in rows[2:]:
        if not raw_row:
            continue
        label = _clean_cell(raw_row[0])
        if not label:
            continue
        match = re.match(r"^(男|女)\s*(\d+)$", label)
        if not match:
            continue
        gender = match.group(1)
        age = int(match.group(2))
        weights = []
        for cell in raw_row[1:1 + len(heights)]:
            value = _to_float(cell)
            weights.append(value)
        profiles.append({"gender": gender, "age": age, "weights": weights})
    return {"heights": heights, "profiles": profiles}


def _build_nutrient_stats(docs: list[dict[str, Any]]) -> dict[str, float]:
    """计算各营养素在所有食材中的最大值（用于归一化）。"""
    stats = {}
    for field in set(NUTRIENT_FIELD_MAP.values()):
        max_value = 0.0
        for doc in docs:
            value = _to_float(doc.get(field))
            if value is not None and value > max_value:
                max_value = value
        stats[field] = max_value or 1.0
    return stats


# ============================================================
# 文档标注函数
# ============================================================

def _match_image_category(doc: dict[str, Any]) -> tuple[str, str]:
    """根据名称和原始分类信息匹配图像分类。"""
    text = " ".join(
        [
            _clean_cell(doc.get("name")),
            _clean_cell(doc.get("raw_category")),
            _clean_cell(doc.get("raw_class")),
        ]
    )
    for category, sub_map in IMAGE_CATEGORY_RULES.items():
        for subcategory, keywords in sub_map.items():
            if any(keyword and keyword in text for keyword in keywords):
                return category, subcategory
    return "待分类", "其它"


def _build_search_text(doc: dict[str, Any]) -> str:
    """构建用于检索的文本。"""
    parts = [
        _clean_cell(doc.get("name")),
        _clean_cell(doc.get("region")),
        _clean_cell(doc.get("image_category")),
        _clean_cell(doc.get("image_subcategory")),
    ]
    for nutrient_label, field in NUTRIENT_FIELD_MAP.items():
        value = _to_float(doc.get(field))
        if value is not None and value > 0:
            parts.append(nutrient_label)
            if value > 0:
                parts.append(f"{nutrient_label}{value}")
    return " ".join(part for part in parts if part)


def _calculate_data_coverage(doc: dict[str, Any]) -> tuple[list[str], list[str], float]:
    """计算文档的数据完整度评分。"""
    available_fields = []
    missing_fields = []
    for field in KEY_COMPLETENESS_FIELDS:
        if _to_float(doc.get(field)) is None:
            missing_fields.append(field)
        else:
            available_fields.append(field)
    coverage_score = len(available_fields) / max(len(KEY_COMPLETENESS_FIELDS), 1)
    return available_fields, missing_fields, round(coverage_score, 3)


def _resolve_major_category_group(image_category: str) -> str:
    """将图像分类映射到核心分类组。"""
    category = _clean_cell(image_category)
    for group, categories in CORE_CATEGORY_REQUIREMENTS.items():
        if category in categories:
            return group
    return ""


def _detect_meat_cut_type(doc: dict[str, Any]) -> str:
    """检测肉类的切分/部位类型。"""
    category = _clean_cell(doc.get("image_category"))
    if category not in ("畜肉类及制品", "禽肉类及制品", "鱼虾蟹贝类"):
        return ""
    combined = " ".join(
        [
            _clean_cell(doc.get("name")),
            _clean_cell(doc.get("image_subcategory")),
            _clean_cell(doc.get("raw_category")),
            _clean_cell(doc.get("raw_class")),
        ]
    )
    for cut_type, keywords in MEAT_CUT_RULES.items():
        if any(keyword in combined for keyword in keywords):
            return cut_type
    if category in ("畜肉类及制品", "禽肉类及制品"):
        return "常规部位"
    if category == "鱼虾蟹贝类":
        return "海鲜优质蛋白"
    return ""


def _detect_dish_role_preference(doc: dict[str, Any]) -> str:
    """检测食材在菜品中的角色偏好。"""
    combined = " ".join(
        [
            _clean_cell(doc.get("name")),
            _clean_cell(doc.get("image_category")),
            _clean_cell(doc.get("image_subcategory")),
        ]
    )
    if any(keyword in combined for keyword in SOUP_OR_PREPARED_KEYWORDS):
        return "配菜优先"
    if _clean_cell(doc.get("major_category_group")) in ("肉禽水产", "蛋奶豆"):
        return "主菜优先"
    if _clean_cell(doc.get("major_category_group")) == "主食谷薯":
        return "主食参考"
    return "通用"


def _detect_storage_state(doc: dict[str, Any]) -> str:
    """检测食材的储存/加工状态。"""
    combined = " ".join(
        [
            _clean_cell(doc.get("name")),
            _clean_cell(doc.get("image_category")),
            _clean_cell(doc.get("image_subcategory")),
        ]
    )
    for keyword in STORAGE_STATE_KEYWORDS:
        if keyword in combined:
            return keyword
    return ""


def _build_vector_document(doc: dict[str, Any]) -> str:
    """构建用于向量化的文档文本。"""
    parts = [
        f"食材名：{_clean_cell(doc.get('name'))}",
        f"分类：{_clean_cell(doc.get('image_category'))}/{_clean_cell(doc.get('image_subcategory'))}",
    ]
    if doc.get("region"):
        parts.append(f"地区：{_clean_cell(doc.get('region'))}")
    nutrient_parts = []
    for nutrient_label, field in NUTRIENT_FIELD_MAP.items():
        value = _to_float(doc.get(field))
        if value is not None and value > 0:
            nutrient_parts.append(f"{nutrient_label}{value}")
    if nutrient_parts:
        parts.append("营养特征：" + "，".join(_dedupe_preserve_order(nutrient_parts[:12])))
    if doc.get("source_sheet"):
        parts.append(f"来源：{_clean_cell(doc.get('source_sheet'))}")
    return "。".join(part for part in parts if part)


# ============================================================
# 顶层入口：知识库初始化
# ============================================================

def ensure_knowledge_base(xls_path: str = DEFAULT_XLS_PATH) -> dict[str, Any]:
    """确保知识库就绪，返回完整知识库字典。"""
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(INDEX_CACHE_PATH):
        with open(INDEX_CACHE_PATH, "r", encoding="utf-8") as f:
            cached = json.load(f)
        if isinstance(cached, dict) and cached.get("kb_version") == KB_VERSION:
            embedding_backend = _ensure_chroma_collection(cached)
            cached["embedding_backend"] = embedding_backend
            return cached

    workbook_data = _load_or_export_workbook(xls_path)
    kb = _build_index_from_workbook(workbook_data)
    with open(INDEX_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(kb, f, ensure_ascii=False, indent=2)
    kb["embedding_backend"] = _ensure_chroma_collection(kb)
    return kb
