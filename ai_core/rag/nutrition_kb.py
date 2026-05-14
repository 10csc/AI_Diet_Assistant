import base64
import calendar
import hashlib
import json
import math
import os
import re
import subprocess
from collections import Counter
from datetime import datetime
from typing import Any

os.environ.setdefault("ANONYMIZED_TELEMETRY", "FALSE")

try:
    import chromadb
except ImportError:  # pragma: no cover - 依赖缺失时在运行期给出明确提示
    chromadb = None

try:
    from sentence_transformers import SentenceTransformer
except ImportError:  # pragma: no cover - 依赖缺失时自动回退到本地哈希向量
    SentenceTransformer = None  # type: ignore

try:
    from huggingface_hub import snapshot_download
except ImportError:  # pragma: no cover - 未安装时不影响回退逻辑
    snapshot_download = None  # type: ignore


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(BASE_DIR, "data", "knowledge_base")
WORKBOOK_CACHE_PATH = os.path.join(DATA_DIR, "nutrition_workbook_cache.json")
INDEX_CACHE_PATH = os.path.join(DATA_DIR, "nutrition_vector_index.json")
CHROMA_DIR = os.path.join(DATA_DIR, "chroma_db")
DEFAULT_XLS_PATH = os.path.join(PROJECT_ROOT, "data", "食材营养.xls")
KB_VERSION = 5
CHROMA_COLLECTION_NAME = "nutrition_foods_v5"
HASH_EMBED_DIM = 256
SEMANTIC_MODEL_NAME = os.getenv("AI_DIET_EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
SEMANTIC_MODEL_DEVICE = os.getenv("AI_DIET_EMBED_DEVICE", "cpu")
SEMANTIC_MODEL_PATH = os.getenv("AI_DIET_EMBED_MODEL_PATH", "").strip()
ALLOW_REMOTE_MODEL_DOWNLOAD = os.getenv("AI_DIET_EMBED_ALLOW_DOWNLOAD", "0").strip() == "1"
TERM_KEYWORDS = [
    ("立春", ["清淡", "舒展", "芽菜", "春鲜"]),
    ("雨水", ["祛湿", "温和", "少油"]),
    ("惊蛰", ["清淡", "增鲜", "时蔬"]),
    ("春分", ["均衡", "轻盈", "新鲜蔬菜"]),
    ("清明", ["平和", "少腻", "时令蔬菜"]),
    ("谷雨", ["清爽", "祛湿", "豆类"]),
    ("立夏", ["补水", "清爽", "时蔬"]),
    ("小满", ["清淡", "祛湿", "豆类蔬菜"]),
    ("芒种", ["补水", "易消化", "清爽"]),
    ("夏至", ["补水", "清爽", "低油"]),
    ("小暑", ["补水", "清热", "清爽"]),
    ("大暑", ["补水", "清热", "低油"]),
    ("立秋", ["润燥", "平和", "汤羹"]),
    ("处暑", ["润燥", "少辛辣", "清润"]),
    ("白露", ["润燥", "温润", "汤羹"]),
    ("秋分", ["润燥", "均衡", "根茎类"]),
    ("寒露", ["温润", "少生冷", "汤羹"]),
    ("霜降", ["温补", "暖胃", "根茎豆类"]),
    ("立冬", ["温补", "暖身", "高蛋白"]),
    ("小雪", ["温热", "暖胃", "汤羹"]),
    ("大雪", ["温热", "暖身", "根茎类"]),
    ("冬至", ["温补", "暖身", "高蛋白"]),
    ("小寒", ["温热", "暖胃", "高蛋白"]),
    ("大寒", ["温热", "暖身", "易消化"]),
]
SEASON_RULES = {
    "春": {
        "keywords": ["春季", "春天", "春", "回暖"],
        "search_terms": ["春季时蔬", "清淡", "新鲜蔬菜"],
        "body_notes": ["当前季节偏春，饮食宜清爽均衡，兼顾新鲜蔬菜摄入"],
    },
    "夏": {
        "keywords": ["夏季", "夏天", "夏", "炎热", "酷暑"],
        "search_terms": ["补水", "清爽", "低油"],
        "body_notes": ["当前季节偏夏，饮食宜补水、清爽并降低油腻负担"],
    },
    "秋": {
        "keywords": ["秋季", "秋天", "秋", "干燥", "秋燥"],
        "search_terms": ["润燥", "温润", "汤羹"],
        "body_notes": ["当前季节偏秋，饮食宜兼顾润燥和温润口感"],
    },
    "冬": {
        "keywords": ["冬季", "冬天", "冬", "寒冷", "降温"],
        "search_terms": ["温热", "暖胃", "汤羹"],
        "body_notes": ["当前季节偏冬，饮食宜温热暖身，减少生冷刺激"],
    },
}
SOFT_PREFERENCE_KEYWORDS = [
    ("甜", "甜口"),
    ("辣", "辣味"),
    ("酸", "酸味"),
    ("香", "香味"),
    ("鲜", "鲜味"),
    ("温热", "温热"),
    ("清爽", "清爽"),
    ("软烂", "软烂"),
    ("汤", "汤羹"),
]
KEY_COMPLETENESS_FIELDS = [
    "energy_kcal",
    "protein_g",
    "fat_g",
    "fiber_g",
    "carb_g",
    "vitamin_a_ug",
    "vitamin_b1_mg",
    "vitamin_b2_mg",
    "niacin_mg",
    "vitamin_e_mg",
    "vitamin_c_mg",
    "sodium_mg",
    "calcium_mg",
    "iron_mg",
    "cholesterol_mg",
]

CANONICAL_FIELDS = {
    "名称": "name",
    "名  称": "name",
    "食物名": "name",
    "地区": "region",
    "可食部分": "edible_portion",
    "能量": "energy_kcal",
    "水分": "water_g",
    "蛋白质": "protein_g",
    "脂肪": "fat_g",
    "膳食纤维": "fiber_g",
    "碳水化物": "carb_g",
    "视黄醇当量": "vitamin_a_ug",
    "维生素A": "vitamin_a_ug",
    "硫胺素(VB1)": "vitamin_b1_mg",
    "维生素B1": "vitamin_b1_mg",
    "核黄素(VB2)": "vitamin_b2_mg",
    "维生素B2": "vitamin_b2_mg",
    "尼克酸 (烟酸, VPP)": "niacin_mg",
    "尼克 酸 (烟酸, VPP)": "niacin_mg",
    "烟酸": "niacin_mg",
    "维生素E": "vitamin_e_mg",
    "钠": "sodium_mg",
    "钙": "calcium_mg",
    "铁": "iron_mg",
    "抗坏血酸(VC)": "vitamin_c_mg",
    "维生素C": "vitamin_c_mg",
    "胆固醇": "cholesterol_mg",
    "类别": "raw_category",
    "类": "raw_class",
}

NUTRIENT_FIELD_MAP = {
    "蛋白质": "protein_g",
    "膳食纤维": "fiber_g",
    "碳水化合物": "carb_g",
    "复合碳水": "carb_g",
    "脂肪": "fat_g",
    "维生素A": "vitamin_a_ug",
    "维生素B1": "vitamin_b1_mg",
    "维生素B2": "vitamin_b2_mg",
    "B族维生素": "niacin_mg",
    "烟酸": "niacin_mg",
    "维生素C": "vitamin_c_mg",
    "维生素E": "vitamin_e_mg",
    "钠": "sodium_mg",
    "钙": "calcium_mg",
    "铁": "iron_mg",
    "胆固醇": "cholesterol_mg",
}

IMAGE_CATEGORY_RULES = {
    "谷类及制品": {
        "小麦": ["小麦", "面粉", "面条", "挂面", "馒头", "面包", "麦片", "全麦"],
        "稻米": ["稻米", "大米", "粳米", "籼米", "糙米", "米饭", "米粉"],
        "玉米": ["玉米", "玉米面"],
        "大麦": ["大麦"],
        "小米、黄米": ["小米", "黄米", "黍", "粟米"],
        "其它": ["燕麦", "荞麦", "藜麦", "高粱"],
    },
    "薯类、淀粉及制品": {
        "薯类": ["红薯", "甘薯", "白薯", "马铃薯", "土豆", "山药", "芋头", "芋艿"],
        "淀粉类": ["淀粉", "粉条", "粉丝", "藕粉", "木薯粉"],
    },
    "干豆类及制品": {
        "大豆": ["黄豆", "大豆", "豆腐", "豆浆", "豆皮", "豆干", "腐竹"],
        "赤豆": ["赤豆", "红豆"],
        "蚕豆": ["蚕豆"],
        "绿豆": ["绿豆"],
        "芸豆": ["芸豆", "四季豆"],
        "其它": ["豌豆", "黑豆", "扁豆"],
    },
    "蔬菜类及制品": {
        "根菜类": ["萝卜", "胡萝卜", "甜菜", "芜菁", "牛蒡"],
        "鲜豆类": ["豌豆苗", "鲜豌豆", "荷兰豆", "毛豆"],
        "茄果、瓜菜类": ["番茄", "西红柿", "黄瓜", "南瓜", "冬瓜", "苦瓜", "茄子", "辣椒"],
        "葱蒜类": ["葱", "洋葱", "蒜", "韭菜"],
        "嫩茎、叶、花菜类": ["菠菜", "油菜", "白菜", "生菜", "芹菜", "菜心", "花椰菜", "西兰花"],
        "水生蔬菜类": ["莲藕", "茭白", "荸荠"],
        "薯芋类": ["土豆", "山药", "芋头"],
        "野生蔬菜类": ["蕨菜", "马齿苋", "香椿"],
    },
    "菌藻类": {
        "菌类": ["香菇", "平菇", "金针菇", "木耳", "银耳", "蘑菇"],
        "藻类": ["海带", "紫菜", "裙带菜"],
    },
    "水果类及制品": {
        "仁果类": ["苹果", "梨", "山楂"],
        "核果类": ["桃", "李", "杏", "枣", "樱桃"],
        "浆果类": ["草莓", "葡萄", "蓝莓", "桑葚"],
        "柑橘类": ["橙", "橘", "柚", "柠檬", "金桔"],
        "热带、亚热带水果": ["香蕉", "芒果", "木瓜", "菠萝", "荔枝", "龙眼"],
        "瓜果类": ["西瓜", "甜瓜", "哈密瓜"],
    },
    "坚果、种子类": {
        "树坚果": ["核桃", "杏仁", "榛子", "腰果", "开心果", "松子"],
        "种子": ["芝麻", "南瓜子", "葵花子", "莲子", "花生"],
    },
    "畜肉类及制品": {
        "猪": ["猪", "猪肉", "猪肝", "猪血", "猪蹄"],
        "牛": ["牛", "牛肉", "牛肚"],
        "羊": ["羊", "羊肉", "羊肝"],
        "驴": ["驴"],
        "马": ["马肉"],
        "其它": ["兔肉", "鹿肉"],
    },
    "禽肉类及制品": {
        "鸡": ["鸡", "鸡肉", "鸡腿", "鸡胸", "鸡翅"],
        "鸭": ["鸭", "鸭肉", "鸭血"],
        "鹅": ["鹅", "鹅肉"],
        "火鸡": ["火鸡"],
        "其它": ["鸽", "鹌鹑"],
    },
    "乳类及制品": {
        "液态乳": ["牛奶", "羊奶", "酸奶", "奶饮料"],
        "奶粉": ["奶粉"],
        "酸奶": ["酸奶", "发酵乳"],
        "奶酪": ["奶酪", "芝士"],
        "奶油": ["奶油", "黄油", "白脱"],
        "其它": ["炼乳"],
    },
    "蛋类及制品": {
        "鸡蛋": ["鸡蛋", "蛋清", "蛋黄"],
        "鸭蛋": ["鸭蛋", "皮蛋", "咸鸭蛋"],
        "鹅蛋": ["鹅蛋"],
        "鹌鹑蛋": ["鹌鹑蛋"],
    },
    "鱼虾蟹贝类": {
        "鱼": ["鱼", "鲈鱼", "鲫鱼", "鳕鱼", "带鱼", "三文鱼"],
        "虾": ["虾", "虾仁"],
        "蟹": ["蟹", "螃蟹"],
        "贝": ["贝", "蛤", "蚬", "牡蛎", "扇贝"],
        "其它": ["海参", "鱿鱼", "墨鱼"],
    },
    "婴幼儿食品": {
        "婴幼儿配方奶": ["配方奶", "婴儿奶粉"],
        "婴幼儿断奶期辅助食品": ["米粉", "泥糊", "辅食"],
        "婴幼儿补充食品": ["营养米粉", "磨牙饼"],
    },
    "小吃、甜饼": {
        "小吃": ["包子", "饺子", "馄饨", "烧卖"],
        "蛋糕、甜点": ["蛋糕", "饼干", "月饼", "甜点", "布丁"],
    },
    "速食食品": {
        "快餐食品": ["汉堡", "披萨", "炸鸡"],
        "方便食品": ["方便面", "自热", "速食粥"],
        "休闲食品": ["薯片", "膨化", "辣条"],
    },
    "饮料类": {
        "碳酸饮料": ["可乐", "雪碧", "汽水"],
        "果汁及其饮料": ["果汁", "橙汁", "果蔬汁"],
        "蔬菜汁饮料": ["蔬菜汁"],
        "含乳饮料": ["乳饮料"],
        "植物蛋白饮料": ["豆奶", "杏仁露", "椰汁"],
        "茶汁及茶饮料": ["茶饮料", "绿茶", "红茶", "乌龙茶"],
        "固体饮料": ["固体饮料", "冲调粉"],
        "棒冰、冰淇凌": ["冰淇淋", "雪糕", "棒冰"],
        "其它": ["咖啡饮料", "功能饮料"],
    },
    "含酒精饮料": {
        "发酵酒": ["葡萄酒", "黄酒", "啤酒"],
        "蒸馏酒": ["白酒", "威士忌", "伏特加"],
        "配制酒": ["果酒", "药酒", "鸡尾酒"],
    },
    "糖、果脯和蜜饯、蜂蜜": {
        "糖": ["白糖", "红糖", "冰糖"],
        "糖果": ["糖果", "巧克力"],
        "果脯和蜜饯": ["果脯", "蜜饯", "葡萄干"],
        "蜂蜜": ["蜂蜜"],
    },
    "油脂类": {
        "动物油脂": ["猪油", "牛油", "羊油", "鸡油"],
        "植物油": ["花生油", "菜籽油", "豆油", "橄榄油", "葵花籽油"],
    },
    "调味品类": {
        "酱油": ["酱油"],
        "醋": ["醋"],
        "酱": ["豆瓣酱", "甜面酱", "辣椒酱"],
        "腐乳": ["腐乳"],
        "咸菜类": ["咸菜", "榨菜"],
        "辛香料": ["花椒", "胡椒", "八角", "桂皮"],
        "盐、味精及其它": ["食盐", "味精", "鸡精"],
    },
}

QUERY_CATEGORY_HINTS = {
    "主食": "谷类及制品",
    "米饭": "谷类及制品",
    "面食": "谷类及制品",
    "蔬菜": "蔬菜类及制品",
    "水果": "水果类及制品",
    "豆制品": "干豆类及制品",
    "菌菇": "菌藻类",
    "肉类": "畜肉类及制品",
    "鸡肉": "禽肉类及制品",
    "鱼": "鱼虾蟹贝类",
    "海鲜": "鱼虾蟹贝类",
    "奶": "乳类及制品",
    "鸡蛋": "蛋类及制品",
    "坚果": "坚果、种子类",
    "饮料": "饮料类",
    "零食": "速食食品",
}

CORE_CATEGORY_REQUIREMENTS = {
    "主食谷薯": ["谷类及制品", "薯类、淀粉及制品"],
    "蔬菜菌藻": ["蔬菜类及制品", "菌藻类"],
    "肉禽水产": ["畜肉类及制品", "禽肉类及制品", "鱼虾蟹贝类"],
    "蛋奶豆": ["蛋类及制品", "乳类及制品", "干豆类及制品"],
}

MEAT_CUT_RULES = {
    "瘦肉": ["里脊", "瘦肉", "腱子", "后腿", "前腿", "腿肉", "腱"],
    "高脂部位": ["五花", "肥牛", "肥羊", "肥肠", "蹄", "皮", "板油", "培根", "排骨"],
    "内脏": ["肝", "肚", "肠", "腰", "心", "肺", "肾", "脑", "胆", "血"],
    "禽类优质部位": ["鸡胸", "鸡腿", "鸭胸", "鸭腿", "火鸡胸"],
    "翅爪类": ["鸡翅", "鸭翅", "凤爪", "鸡爪", "鸭掌"],
    "海鲜优质蛋白": ["鱼", "虾", "虾仁", "贝", "牡蛎", "扇贝", "鳕鱼", "鲈鱼", "带鱼"],
}

SOUP_OR_PREPARED_KEYWORDS = ["汤", "羹", "粥", "卤", "熟食", "扒鸡", "烤鸡", "烧鸡", "酱肉", "成品"]
STORAGE_STATE_KEYWORDS = ["干", "脱水", "风干", "腌", "罐头", "熏", "腊", "咸", "速食", "方便"]
EXPLICIT_STATE_HINTS = ["干货", "脱水", "罐头", "腌制", "风干", "汤", "羹", "粥", "熟食", "成品", "卤味", "速食"]
STATE_EMPHASIS_EQUIVALENTS = {
    "干货": ["干", "风干", "脱水"],
    "汤": ["汤", "羹", "粥"],
    "成品": ["成品", "熟食", "卤", "扒鸡", "烧鸡"],
}


def ensure_knowledge_base(xls_path: str = DEFAULT_XLS_PATH) -> dict[str, Any]:
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


def build_rag_context(
    user_input: str,
    personal_info_text: str = "",
    weather_text: str = "",
    preprocess_result: dict[str, Any] | None = None,
    xls_path: str = DEFAULT_XLS_PATH,
    top_k: int = 8,
) -> dict[str, Any]:
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
    nutrition_profile = rag_context.get("nutrition_profile", {})
    middle_layer_input = rag_context.get("middle_layer_input", {})
    middle_layer_output = rag_context.get("middle_layer_output", {})
    sections = [
        f"原始用户需求：{user_input}",
        f"一级分析结果：{json.dumps(preprocess_result, ensure_ascii=False)}",
        f"规则增强后的用户营养需求：{json.dumps(nutrition_profile, ensure_ascii=False)}",
        f"中间层输入（营养需求）：{json.dumps(middle_layer_input, ensure_ascii=False)}",
        f"中间层输出（食材候选）：{json.dumps(middle_layer_output, ensure_ascii=False)}",
        f"菜品软约束策略：{json.dumps(middle_layer_output.get('dish_constraint_policy', {}), ensure_ascii=False)}",
        f"知识库召回结果：\n{rag_context.get('retrieval_text', '无')}",
        (
            "任务要求：请结合用户画像、身体状态、心理状态、天气趋势、"
            "用户所需营养素与知识库召回证据，给出匹配的中国菜式推荐。"
        ),
    ]
    return "\n\n".join(sections)


def _load_or_export_workbook(xls_path: str) -> dict[str, Any]:
    if os.path.exists(WORKBOOK_CACHE_PATH):
        with open(WORKBOOK_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    workbook_data = _export_workbook_to_json(xls_path)
    with open(WORKBOOK_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(workbook_data, f, ensure_ascii=False, indent=2)
    return workbook_data


def _export_workbook_to_json(xls_path: str) -> dict[str, Any]:
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
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
        ],
        capture_output=True,
        check=False,
    )
    stdout_text = _decode_process_output(completed.stdout)
    stderr_text = _decode_process_output(completed.stderr)
    if completed.returncode != 0:
        message = (stderr_text or stdout_text).strip()
        raise RuntimeError(f"导出 xls 失败: {message}")
    payload = json.loads((stdout_text or "").strip() or "[]")
    if isinstance(payload, dict):
        payload = [payload]
    return {"sheets": payload}


def _build_index_from_workbook(workbook_data: dict[str, Any]) -> dict[str, Any]:
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
    stats = {}
    for field in set(NUTRIENT_FIELD_MAP.values()):
        max_value = 0.0
        for doc in docs:
            value = _to_float(doc.get(field))
            if value is not None and value > max_value:
                max_value = value
        stats[field] = max_value or 1.0
    return stats


def _build_deterministic_profile(
    user_input: str,
    personal_info: dict[str, Any],
    weather_info: dict[str, Any],
    kb: dict[str, Any],
) -> dict[str, Any]:
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


def _build_season_context(weather_info: dict[str, Any], user_input: str) -> dict[str, Any]:
    season = ""
    season_keywords: list[str] = []
    body_notes: list[str] = []
    term_name = ""
    term_preference: list[str] = []
    text_parts = [user_input]
    if isinstance(weather_info, dict):
        text_parts.append(json.dumps(weather_info, ensure_ascii=False))
    combined_text = " ".join(part for part in text_parts if part)
    for season_name, config in SEASON_RULES.items():
        if any(keyword in combined_text for keyword in config.get("keywords", [])):
            season = season_name
            season_keywords.extend(config.get("search_terms", []))
            body_notes.extend(config.get("body_notes", []))
            break
    if not season:
        season = _season_from_month(datetime.now().month)
        config = SEASON_RULES.get(season, {})
        season_keywords.extend(config.get("search_terms", []))
        body_notes.extend(config.get("body_notes", []))

    for term, term_words in TERM_KEYWORDS:
        if term in combined_text:
            term_name = term
            term_preference.extend(term_words)
            break

    return {
        "season": season,
        "term": term_name,
        "season_keywords": _dedupe_preserve_order(season_keywords),
        "body_notes": _dedupe_preserve_order(body_notes),
        "term_preference": _dedupe_preserve_order(term_preference),
        "term_keywords": _dedupe_preserve_order(term_preference),
        "summary": "、".join([part for part in [season, term_name] if part]) or "未显式识别节气，按当前季节处理",
    }


def _season_from_month(month: int) -> str:
    if month in (3, 4, 5):
        return "春"
    if month in (6, 7, 8):
        return "夏"
    if month in (9, 10, 11):
        return "秋"
    return "冬"


def _augment_health_constraints(
    combined_text: str,
    dietary_limits: list[str],
    hard_constraints: list[str],
    target_nutrients: list[str],
    retrieval_keywords: list[str],
) -> None:
    if any(keyword in combined_text for keyword in ["糖尿病", "控糖", "血糖"]):
        dietary_limits.extend(["控制总糖摄入", "选择低GI食材", "避免高脂肪高热量食物"])
        hard_constraints.extend(["控糖优先于口味满足", "避免高糖高负荷食材"])
        target_nutrients.extend(["膳食纤维", "维生素C"])
        retrieval_keywords.extend(["低GI", "稳定血糖", "优质蛋白"])
    if any(keyword in combined_text for keyword in ["胃炎", "胃不舒服", "胃痛", "胃部敏感"]):
        hard_constraints.extend(["避免刺激性和过度油腻食材"])
        retrieval_keywords.extend(["软烂", "温和"])
    if any(keyword in combined_text for keyword in ["高血压", "血压高"]):
        hard_constraints.extend(["优先控制钠摄入"])


def _extract_soft_preferences(*texts: Any) -> list[str]:
    combined_text = " ".join(_stringify_value(text) for text in texts if text)
    preferences = []
    for keyword, label in SOFT_PREFERENCE_KEYWORDS:
        if keyword in combined_text:
            preferences.append(label)
    if any(keyword in combined_text for keyword in ["开心", "安慰", "情绪", "压力", "烦躁", "想吃点好吃的"]):
        preferences.append("情绪安抚")
    return _dedupe_preserve_order(preferences)


def _extract_state_emphasis(*texts: Any) -> list[str]:
    combined_text = " ".join(_stringify_value(text) for text in texts if text)
    matched = []
    for keyword in EXPLICIT_STATE_HINTS:
        if keyword in combined_text:
            matched.append(keyword)
    return _dedupe_preserve_order(matched)


def _merge_preprocess_and_rules(
    preprocess_result: dict[str, Any],
    deterministic_profile: dict[str, Any],
) -> dict[str, Any]:
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


def _build_middle_layer_input(nutrition_profile: dict[str, Any]) -> dict[str, Any]:
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


def _build_middle_layer_output(food_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "food_candidates": food_candidates,
        "candidate_count": len(food_candidates),
        "output_description": "依据用户所需营养、分类偏好和缺失值处理后的食材候选列表",
        "dish_constraint_policy": _build_dish_constraint_policy(food_candidates),
        "category_coverage_summary": _build_category_coverage_summary(food_candidates),
    }


def _build_dish_constraint_policy(food_candidates: list[dict[str, Any]]) -> dict[str, Any]:
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


def _resolve_major_category_group(image_category: str) -> str:
    category = _clean_cell(image_category)
    for group, categories in CORE_CATEGORY_REQUIREMENTS.items():
        if category in categories:
            return group
    return ""


def _detect_meat_cut_type(doc: dict[str, Any]) -> str:
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


def _ensure_core_category_coverage(
    ranked: list[dict[str, Any]],
    fallback_pool: list[dict[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
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


def _retrieve_documents(kb: dict[str, Any], middle_layer_input: dict[str, Any], top_k: int) -> list[dict[str, Any]]:
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


def _score_nutrients(
    doc: dict[str, Any],
    target_nutrients: list[str],
    nutrient_stats: dict[str, Any],
) -> tuple[float, list[str], list[str]]:
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


def _format_retrieval_text(retrieved_items: list[dict[str, Any]]) -> str:
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


def _build_vector_document(doc: dict[str, Any]) -> str:
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


def _calculate_data_coverage(doc: dict[str, Any]) -> tuple[list[str], list[str], float]:
    available_fields = []
    missing_fields = []
    for field in KEY_COMPLETENESS_FIELDS:
        if _to_float(doc.get(field)) is None:
            missing_fields.append(field)
        else:
            available_fields.append(field)
    coverage_score = len(available_fields) / max(len(KEY_COMPLETENESS_FIELDS), 1)
    return available_fields, missing_fields, round(coverage_score, 3)


def _ensure_chroma_collection(kb: dict[str, Any]) -> str:
    if chromadb is None:
        raise RuntimeError("未安装 chromadb，请先执行 `pip install chromadb`")
    embedding_function = _get_embedding_function()
    embedding_backend = _current_embedding_backend()
    os.makedirs(CHROMA_DIR, exist_ok=True)
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    needs_rebuild = False
    try:
        collection = client.get_collection(
            name=CHROMA_COLLECTION_NAME,
            embedding_function=embedding_function,
        )
        metadata = collection.metadata or {}
        if (
            collection.count() != len(kb.get("documents", []))
            or metadata.get("embedding_backend") != embedding_backend
            or metadata.get("kb_version") != KB_VERSION
        ):
            needs_rebuild = True
    except Exception:
        needs_rebuild = True

    if needs_rebuild:
        try:
            client.delete_collection(CHROMA_COLLECTION_NAME)
        except Exception:
            pass
        collection = client.create_collection(
            name=CHROMA_COLLECTION_NAME,
            embedding_function=embedding_function,
            metadata={
                "description": "AI Diet Assistant nutrition foods",
                "embedding_backend": embedding_backend,
                "kb_version": KB_VERSION,
            },
        )
        documents = []
        ids = []
        metadatas = []
        for doc in kb.get("documents", []):
            ids.append(doc.get("doc_id", ""))
            documents.append(doc.get("vector_document", doc.get("search_text", "")))
            metadatas.append(_build_chroma_metadata(doc))
        if ids:
            collection.add(ids=ids, documents=documents, metadatas=metadatas)
    return embedding_backend


def _build_chroma_metadata(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "doc_id": _clean_cell(doc.get("doc_id")),
        "name": _clean_cell(doc.get("name")),
        "image_category": _clean_cell(doc.get("image_category")),
        "image_subcategory": _clean_cell(doc.get("image_subcategory")),
        "source_sheet": _clean_cell(doc.get("source_sheet")),
        "coverage_score": float(doc.get("coverage_score", 0.0)),
        "missing_count": len(doc.get("missing_fields", [])),
        "available_count": len(doc.get("available_fields", [])),
    }


def _query_chroma_candidates(query_text: str, top_n: int) -> list[dict[str, Any]]:
    if chromadb is None:
        raise RuntimeError("未安装 chromadb，请先执行 `pip install chromadb`")
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    collection = client.get_collection(
        name=CHROMA_COLLECTION_NAME,
        embedding_function=_get_embedding_function(),
    )
    result = collection.query(
        query_texts=[query_text],
        n_results=top_n,
        include=["metadatas", "distances"],
    )
    ids = result.get("ids", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]
    hits = []
    for index, doc_id in enumerate(ids):
        distance = float(distances[index]) if index < len(distances) and distances[index] is not None else 1.0
        metadata = metadatas[index] if index < len(metadatas) and isinstance(metadatas[index], dict) else {}
        hits.append(
            {
                "doc_id": metadata.get("doc_id") or doc_id,
                "vector_score": round(1 / (1 + max(distance, 0.0)), 4),
            }
        )
    return hits


class _HashEmbeddingFunction:
    def __call__(self, input: list[str]) -> list[list[float]]:
        return [_embed_text_hash(text) for text in input]


class _SentenceTransformerEmbeddingFunction:
    _model = None
    _backend_name = ""
    _disabled = False

    @classmethod
    def backend_name(cls) -> str:
        if SentenceTransformer is None or cls._disabled:
            return "hash_fallback"
        model_ref = _semantic_model_reference()
        if _local_semantic_model_available():
            return f"sentence-transformers:{model_ref}"
        if ALLOW_REMOTE_MODEL_DOWNLOAD:
            return f"sentence-transformers:{model_ref}"
        return "hash_fallback"

    @classmethod
    def _get_model(cls):
        if SentenceTransformer is None or cls._disabled:
            raise RuntimeError("未安装 sentence-transformers")
        if not _local_semantic_model_available() and not ALLOW_REMOTE_MODEL_DOWNLOAD:
            cls._disabled = True
            raise RuntimeError("未检测到本地中文 embedding 模型，且未开启远程下载")
        if cls._model is None:
            cls._model = SentenceTransformer(
                _semantic_model_reference(),
                device=SEMANTIC_MODEL_DEVICE,
                local_files_only=not ALLOW_REMOTE_MODEL_DOWNLOAD,
            )
            cls._backend_name = cls.backend_name()
        return cls._model

    def __call__(self, input: list[str]) -> list[list[float]]:
        try:
            model = self._get_model()
            embeddings = model.encode(
                input,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            return embeddings.tolist()
        except Exception:
            self.__class__._disabled = True
            return [_embed_text_hash(text) for text in input]


_EMBEDDING_FUNCTION = None


def _get_embedding_function():
    global _EMBEDDING_FUNCTION
    if _EMBEDDING_FUNCTION is None:
        _EMBEDDING_FUNCTION = _SentenceTransformerEmbeddingFunction()
    return _EMBEDDING_FUNCTION


def _current_embedding_backend() -> str:
    return _SentenceTransformerEmbeddingFunction.backend_name()


def _semantic_model_reference() -> str:
    return SEMANTIC_MODEL_PATH if SEMANTIC_MODEL_PATH else SEMANTIC_MODEL_NAME


def _local_semantic_model_available() -> bool:
    model_ref = _semantic_model_reference()
    if not model_ref:
        return False
    if os.path.isdir(model_ref):
        return True
    if snapshot_download is None:
        return False
    try:
        snapshot_download(model_ref, local_files_only=True)
        return True
    except Exception:
        return False


def _match_image_category(doc: dict[str, Any]) -> tuple[str, str]:
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


def _vectorize_text(text: str) -> Counter[str]:
    tokens = _tokenize(text)
    return Counter(tokens)


def _tokenize(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    words = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", normalized)
    tokens = []
    for word in words:
        tokens.append(word)
        if re.fullmatch(r"[\u4e00-\u9fff]+", word):
            if len(word) == 1:
                continue
            for index in range(len(word) - 1):
                tokens.append(word[index:index + 2])
    return tokens


def _cosine_similarity(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    common = set(left) & set(right)
    numerator = sum(left[token] * right[token] for token in common)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _embed_text_hash(text: str) -> list[float]:
    vector = [0.0] * HASH_EMBED_DIM
    tokens = _tokenize(text)
    if not tokens:
        return vector
    for token in tokens:
        digest = hashlib.md5(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:2], "big") % HASH_EMBED_DIM
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        weight = 1.0 + (len(token) / 10.0)
        vector[index] += sign * weight
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def _estimate_bmi(personal_info: dict[str, Any]) -> tuple[float | None, str]:
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


def _estimate_standard_weight(personal_info: dict[str, Any], table: dict[str, Any]) -> float | None:
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


def _normalize_header(value: Any) -> str:
    return re.sub(r"\s+", " ", _clean_cell(value)).strip()


def _parse_json_object(text: str) -> dict[str, Any]:
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _parse_list_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_clean_cell(item) for item in value if _clean_cell(item)]
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return []
        if cleaned.startswith("[") and cleaned.endswith("]"):
            try:
                parsed = json.loads(cleaned)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [_clean_cell(item) for item in parsed if _clean_cell(item)]
        parts = re.split(r"[，,、；;]\s*", cleaned)
        return [_clean_cell(item) for item in parts if _clean_cell(item)]
    return []


def _stringify_value(value: Any) -> str:
    if isinstance(value, list):
        return "、".join(_clean_cell(item) for item in value if _clean_cell(item))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return _clean_cell(value)


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        cleaned = _clean_cell(value)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _coerce_value(value: Any) -> Any:
    cleaned = _clean_cell(value)
    number = _to_float(cleaned)
    if number is not None:
        return int(number) if number.is_integer() else number
    return cleaned


def _to_float(value: Any) -> float | None:
    text = _clean_cell(value)
    if not text:
        return None
    text = text.replace("%", "").replace("＜", "<")
    if text.startswith("<"):
        text = text[1:]
    try:
        return float(text)
    except ValueError:
        return None


def _clean_cell(value: Any) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ").strip()


def _decode_process_output(raw_output: Any) -> str:
    if raw_output is None:
        return ""
    if isinstance(raw_output, str):
        return raw_output
    for encoding in ("utf-8", "gbk", "utf-16le"):
        try:
            return raw_output.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw_output.decode("utf-8", errors="ignore")
