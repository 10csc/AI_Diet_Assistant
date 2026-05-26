"""
知识规则模块 —— 静态常量、映射规则及基于规则的决策函数。

本模块不含对其他子模块的依赖，仅使用 Python 标准库。
所有与知识库规则无关的通用工具函数也集中于此。
"""

import calendar
import json
import math
import re
from collections import Counter
from datetime import datetime
from typing import Any, Optional

# ============================================================
# 公共常量
# ============================================================

KB_VERSION = 5
CHROMA_COLLECTION_NAME = "nutrition_foods_v5"

# 二十四节气与饮食倾向
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

# 季节规则
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

# 口感/偏好关键词
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

# 完整性评估字段
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

# 字段名映射（中文 -> 规范化字段名）
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

# 中文营养素名 -> 规范化字段名（用于评分/检索）
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

# 图像分类规则（一级类 -> 子类 -> 关键词）
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

# 查询分类提示
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

# 核心分类需求
CORE_CATEGORY_REQUIREMENTS = {
    "主食谷薯": ["谷类及制品", "薯类、淀粉及制品"],
    "蔬菜菌藻": ["蔬菜类及制品", "菌藻类"],
    "肉禽水产": ["畜肉类及制品", "禽肉类及制品", "鱼虾蟹贝类"],
    "蛋奶豆": ["蛋类及制品", "乳类及制品", "干豆类及制品"],
}

# 肉类切分规则
MEAT_CUT_RULES = {
    "瘦肉": ["里脊", "瘦肉", "腱子", "后腿", "前腿", "腿肉", "腱"],
    "高脂部位": ["五花", "肥牛", "肥羊", "肥肠", "蹄", "皮", "板油", "培根", "排骨"],
    "内脏": ["肝", "肚", "肠", "腰", "心", "肺", "肾", "脑", "胆", "血"],
    "禽类优质部位": ["鸡胸", "鸡腿", "鸭胸", "鸭腿", "火鸡胸"],
    "翅爪类": ["鸡翅", "鸭翅", "凤爪", "鸡爪", "鸭掌"],
    "海鲜优质蛋白": ["鱼", "虾", "虾仁", "贝", "牡蛎", "扇贝", "鳕鱼", "鲈鱼", "带鱼"],
}

# 汤/成品类关键词
SOUP_OR_PREPARED_KEYWORDS = ["汤", "羹", "粥", "卤", "熟食", "扒鸡", "烤鸡", "烧鸡", "酱肉", "成品"]

# 储存状态关键词
STORAGE_STATE_KEYWORDS = ["干", "脱水", "风干", "腌", "罐头", "熏", "腊", "咸", "速食", "方便"]

# 显式状态提示
EXPLICIT_STATE_HINTS = ["干货", "脱水", "罐头", "腌制", "风干", "汤", "羹", "粥", "熟食", "成品", "卤味", "速食"]

# 状态强调等价词
STATE_EMPHASIS_EQUIVALENTS = {
    "干货": ["干", "风干", "脱水"],
    "汤": ["汤", "羹", "粥"],
    "成品": ["成品", "熟食", "卤", "扒鸡", "烧鸡"],
}


# ============================================================
# 通用工具函数
# ============================================================

def _clean_cell(value: Any) -> str:
    """清理单元格值：转字符串、去换行、去首尾空白。"""
    return str(value or "").replace("\r", " ").replace("\n", " ").strip()


def _to_float(value: Any) -> Optional[float]:
    """安全的字符串转浮点数。"""
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


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    """去重并保持原有顺序。"""
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
    """尝试将值转为数值类型，否则返回清理后的字符串。"""
    cleaned = _clean_cell(value)
    number = _to_float(cleaned)
    if number is not None:
        return int(number) if number.is_integer() else number
    return cleaned


def _stringify_value(value: Any) -> str:
    """将任意值转为字符串表示。"""
    if isinstance(value, list):
        return "、".join(_clean_cell(item) for item in value if _clean_cell(item))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return _clean_cell(value)


def _parse_json_object(text: str) -> dict[str, Any]:
    """安全地解析 JSON 字符串为字典。"""
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _parse_list_value(value: Any) -> list[str]:
    """将各种形式的列表值解析为字符串列表。"""
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


def _normalize_header(value: Any) -> str:
    """规范化表头字段名。"""
    return re.sub(r"\s+", " ", _clean_cell(value)).strip()


def _decode_process_output(raw_output: Any) -> str:
    """解码子进程输出（支持 utf-8 / gbk / utf-16le 回退）。"""
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


def _tokenize(text: str) -> list[str]:
    """中文分词（基于正则的简单切词 + 二元组）。"""
    normalized = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    words = re.findall("[a-z0-9_]+|[一-鿿]+", normalized)
    tokens = []
    for word in words:
        tokens.append(word)
        if re.fullmatch(r"[一-鿿]+", word):
            if len(word) == 1:
                continue
            for index in range(len(word) - 1):
                tokens.append(word[index:index + 2])
    return tokens


def _vectorize_text(text: str) -> Counter[str]:
    """文本向量化（词袋）。"""
    tokens = _tokenize(text)
    return Counter(tokens)


def _cosine_similarity(left: Counter[str], right: Counter[str]) -> float:
    """计算两个词袋向量的余弦相似度。"""
    if not left or not right:
        return 0.0
    common = set(left) & set(right)
    numerator = sum(left[token] * right[token] for token in common)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


# ============================================================
# 基于规则的决策函数
# ============================================================

def _season_from_month(month: int) -> str:
    """根据月份返回季节。"""
    if month in (3, 4, 5):
        return "春"
    if month in (6, 7, 8):
        return "夏"
    if month in (9, 10, 11):
        return "秋"
    return "冬"


# 二十四节气近似日期（基于太阳黄经，公历日期 ±1 天）
_SOLAR_TERM_DATES = [
    (1, 5, "小寒"),   (1, 20, "大寒"),
    (2, 4, "立春"),   (2, 19, "雨水"),
    (3, 6, "惊蛰"),   (3, 21, "春分"),
    (4, 5, "清明"),   (4, 20, "谷雨"),
    (5, 6, "立夏"),   (5, 21, "小满"),
    (6, 6, "芒种"),   (6, 21, "夏至"),
    (7, 7, "小暑"),   (7, 23, "大暑"),
    (8, 7, "立秋"),   (8, 23, "处暑"),
    (9, 8, "白露"),   (9, 23, "秋分"),
    (10, 8, "寒露"),  (10, 24, "霜降"),
    (11, 7, "立冬"),  (11, 22, "小雪"),
    (12, 7, "大雪"),  (12, 22, "冬至"),
]


def _get_current_solar_term(today: datetime = None) -> str:
    """
    根据日期自动判断当前节气（近似，误差 ±1 天）。

    节气是太阳历，公历日期基本固定。
    如用户输入已包含节气名（由 _build_season_context 处理），此函数作为后备。
    """
    today = today or datetime.now()
    target = (today.month, today.day)
    last_term = _SOLAR_TERM_DATES[-1][2]  # 大寒（兜底）
    for month, day, term in _SOLAR_TERM_DATES:
        if (month, day) > target:
            return last_term
        last_term = term
    return last_term


def _build_season_context(weather_info: dict[str, Any], user_input: str) -> dict[str, Any]:
    """构建季节上下文（含节气信息）。"""
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

    # 用户未明确提到节气时，根据日期自动推断
    if not term_name:
        auto_term = _get_current_solar_term()
        for term, term_words in TERM_KEYWORDS:
            if term == auto_term:
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


def _extract_soft_preferences(*texts: Any) -> list[str]:
    """从文本中提取口感/偏好倾向。"""
    combined_text = " ".join(_stringify_value(text) for text in texts if text)
    preferences = []
    for keyword, label in SOFT_PREFERENCE_KEYWORDS:
        if keyword in combined_text:
            preferences.append(label)
    if any(keyword in combined_text for keyword in ["开心", "安慰", "情绪", "压力", "烦躁", "想吃点好吃的"]):
        preferences.append("情绪安抚")
    return _dedupe_preserve_order(preferences)


def _extract_state_emphasis(*texts: Any) -> list[str]:
    """从文本中提取状态强调。"""
    combined_text = " ".join(_stringify_value(text) for text in texts if text)
    matched = []
    for keyword in EXPLICIT_STATE_HINTS:
        if keyword in combined_text:
            matched.append(keyword)
    return _dedupe_preserve_order(matched)


def _augment_health_constraints(
    combined_text: str,
    dietary_limits: list[str],
    hard_constraints: list[str],
    target_nutrients: list[str],
    retrieval_keywords: list[str],
) -> None:
    """根据健康关键词增强约束条件。"""
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
