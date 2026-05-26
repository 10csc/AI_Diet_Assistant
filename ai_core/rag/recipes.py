# recipes.py — 内置菜谱知识库，为二级模型提供参考菜式

import json
import os
import random

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 从 JSON 文件加载内置菜谱数据（存在时），否则使用内置硬编码兜底
# 项目根目录 = BASE_DIR 的父目录（即 ai_core/ 的上一层）
_PROJECT_ROOT = os.path.dirname(BASE_DIR)
_BUILTIN_RECIPES = []
_recipes_json_path = os.path.join(_PROJECT_ROOT, "data", "recipes.json")
if os.path.isfile(_recipes_json_path):
    try:
        with open(_recipes_json_path, encoding="utf-8") as _f:
            _BUILTIN_RECIPES = json.load(_f).get("recipes", [])
    except Exception:
        _BUILTIN_RECIPES = []
if not _BUILTIN_RECIPES:
    # 硬编码兜底数据
    _BUILTIN_RECIPES = [
        {"dish": "鱼香肉丝", "category": "畜肉", "ingredients": "猪里脊200g、木耳、胡萝卜、青椒、郫县豆瓣酱、醋、糖", "method": "滑炒",
         "nutrition": "能量约280kcal，蛋白质24g，脂肪12g，碳水18g",
         "tags": ["下饭", "家常", "高蛋白", "中等热量"]},
        {"dish": "宫保鸡丁", "category": "禽肉", "ingredients": "鸡胸肉250g、花生米、干辣椒、花椒、葱姜蒜、酱油、醋", "method": "爆炒",
         "nutrition": "能量约320kcal，蛋白质28g，脂肪16g，碳水15g",
         "tags": ["下饭", "经典", "高蛋白", "中等热量"]},
        {"dish": "红烧肉", "category": "畜肉", "ingredients": "五花肉500g、冰糖、八角、桂皮、老抽、姜", "method": "红烧",
         "nutrition": "能量约580kcal，蛋白质18g，脂肪48g，碳水12g",
         "tags": ["经典", "高热量", "高脂肪"]},
        {"dish": "清蒸鲈鱼", "category": "水产", "ingredients": "鲈鱼1条（约500g）、姜丝、葱丝、蒸鱼豉油、料酒", "method": "清蒸",
         "nutrition": "能量约180kcal，蛋白质32g，脂肪4g，碳水2g",
         "tags": ["清淡", "高蛋白", "低脂", "低热量"]},
        {"dish": "糖醋排骨", "category": "畜肉", "ingredients": "猪小排500g、番茄酱、白糖、醋、白芝麻", "method": "炸收",
         "nutrition": "能量约420kcal，蛋白质22g，脂肪26g，碳水30g",
         "tags": ["经典", "酸甜", "中高热量"]},
        {"dish": "青椒肉丝", "category": "畜肉", "ingredients": "猪瘦肉200g、青椒150g、姜蒜、酱油、淀粉", "method": "滑炒",
         "nutrition": "能量约230kcal，蛋白质22g，脂肪10g，碳水12g",
         "tags": ["家常", "快炒", "高蛋白", "低热量"]},
        {"dish": "回锅肉", "category": "畜肉", "ingredients": "五花肉300g、蒜苗、郫县豆瓣酱、豆豉、青椒", "method": "煸炒",
         "nutrition": "能量约480kcal，蛋白质20g，脂肪38g，碳水10g",
         "tags": ["经典", "川菜", "高热量"]},
        {"dish": "番茄牛腩", "category": "畜肉", "ingredients": "牛腩500g、番茄3个、土豆、洋葱、番茄酱、八角", "method": "炖煮",
         "nutrition": "能量约350kcal，蛋白质30g，脂肪18g，碳水22g",
         "tags": ["汤菜", "高蛋白", "暖胃", "中等热量"]},
        {"dish": "黄焖鸡", "category": "禽肉", "ingredients": "鸡腿500g、香菇、青椒、姜蒜、酱油、冰糖", "method": "焖烧",
         "nutrition": "能量约380kcal，蛋白质32g，脂肪20g，碳水15g",
         "tags": ["下饭", "高蛋白", "中等热量"]},
        {"dish": "可乐鸡翅", "category": "禽肉", "ingredients": "鸡中翅8个、可乐一罐、姜、酱油、料酒", "method": "收汁",
         "nutrition": "能量约350kcal，蛋白质24g，脂肪16g，碳水26g",
         "tags": ["甜口", "简单", "中等热量"]},
        {"dish": "白切鸡", "category": "禽肉", "ingredients": "三黄鸡1只、姜葱、沙姜、酱油、花生油", "method": "浸煮",
         "nutrition": "能量约260kcal，蛋白质30g，脂肪15g，碳水1g",
         "tags": ["清淡", "高蛋白", "低脂", "广式"]},
        {"dish": "孜然鸡翅", "category": "禽肉", "ingredients": "鸡中翅8个、孜然粉、辣椒粉、蒜、生抽、料酒", "method": "烤制",
         "nutrition": "能量约320kcal，蛋白质26g，脂肪18g，碳水8g",
         "tags": ["烧烤风味", "高蛋白", "中等热量"]},
        {"dish": "红烧鲫鱼", "category": "水产", "ingredients": "鲫鱼2条（约400g）、姜蒜、葱、酱油、料酒、白糖", "method": "红烧",
         "nutrition": "能量约220kcal，蛋白质28g，脂肪8g，碳水6g",
         "tags": ["家常", "高蛋白", "低热量"]},
        {"dish": "蒜蓉粉丝蒸虾", "category": "水产", "ingredients": "大虾200g、粉丝、蒜蓉、葱花、蒸鱼豉油、蚝油", "method": "清蒸",
         "nutrition": "能量约210kcal，蛋白质22g，脂肪6g，碳水18g",
         "tags": ["清淡", "高蛋白", "低脂", "宴客"]},
        {"dish": "酸菜鱼", "category": "水产", "ingredients": "草鱼500g、酸菜、干辣椒、花椒、姜蒜、蛋清", "method": "煮",
         "nutrition": "能量约250kcal，蛋白质30g，脂肪8g，碳水10g",
         "tags": ["经典", "高蛋白", "低脂", "川菜"]},
        {"dish": "葱姜炒蟹", "category": "水产", "ingredients": "梭子蟹2只、姜片、葱段、料酒、蚝油、淀粉", "method": "爆炒",
         "nutrition": "能量约180kcal，蛋白质24g，脂肪6g，碳水4g",
         "tags": ["海鲜", "高蛋白", "低脂"]},
        {"dish": "麻婆豆腐", "category": "豆制品", "ingredients": "嫩豆腐400g、牛肉末50g、郫县豆瓣酱、花椒粉、葱花", "method": "烧",
         "nutrition": "能量约200kcal，蛋白质16g，脂肪10g，碳水10g",
         "tags": ["经典", "川菜", "下饭", "低热量"]},
        {"dish": "家常豆腐", "category": "豆制品", "ingredients": "老豆腐300g、木耳、青椒、胡萝卜、酱油、豆瓣酱", "method": "煎烧",
         "nutrition": "能量约220kcal，蛋白质18g，脂肪12g，碳水12g",
         "tags": ["家常", "素食友好", "低热量"]},
        {"dish": "皮蛋豆腐", "category": "豆制品", "ingredients": "内酯豆腐1盒、皮蛋2个、葱花、生抽、香油、辣椒油", "method": "凉拌",
         "nutrition": "能量约160kcal，蛋白质12g，脂肪10g，碳水8g",
         "tags": ["凉菜", "简单", "低热量"]},
        {"dish": "蒜蓉油麦菜", "category": "蔬菜", "ingredients": "油麦菜300g、蒜末、蚝油、盐", "method": "清炒",
         "nutrition": "能量约60kcal，蛋白质3g，脂肪3g，碳水6g",
         "tags": ["清淡", "低热量", "快手", "素食"]},
        {"dish": "干煸四季豆", "category": "蔬菜", "ingredients": "四季豆300g、干辣椒、蒜末、花椒、盐", "method": "煸炒",
         "nutrition": "能量约120kcal，蛋白质5g，脂肪8g，碳水10g",
         "tags": ["川菜", "下饭", "中低热量"]},
        {"dish": "地三鲜", "category": "蔬菜", "ingredients": "茄子200g、土豆150g、青椒100g、蒜、酱油、淀粉", "method": "过油炒",
         "nutrition": "能量约180kcal，蛋白质5g，脂肪10g，碳水22g",
         "tags": ["经典", "下饭", "素食友好"]},
        {"dish": "西芹炒百合", "category": "蔬菜", "ingredients": "西芹300g、鲜百合100g、盐、水淀粉", "method": "清炒",
         "nutrition": "能量约80kcal，蛋白质3g，脂肪1g，碳水16g",
         "tags": ["清淡", "低脂", "润燥", "素食"]},
        {"dish": "酸辣土豆丝", "category": "蔬菜", "ingredients": "土豆300g、干辣椒、醋、花椒、盐、葱", "method": "爆炒",
         "nutrition": "能量约140kcal，蛋白质3g，脂肪4g，碳水26g",
         "tags": ["家常", "快手", "经济"]},
        {"dish": "番茄炒蛋", "category": "蛋类", "ingredients": "番茄2个、鸡蛋3个、葱、盐、糖", "method": "炒",
         "nutrition": "能量约200kcal，蛋白质16g，脂肪12g，碳水10g",
         "tags": ["家常", "经典", "快手", "低热量"]},
        {"dish": "蒸水蛋", "category": "蛋类", "ingredients": "鸡蛋3个、温水、盐、生抽、香油", "method": "蒸",
         "nutrition": "能量约170kcal，蛋白质15g，脂肪10g，碳水2g",
         "tags": ["清淡", "易消化", "低热量", "老人儿童"]},
        {"dish": "韭菜炒鸡蛋", "category": "蛋类", "ingredients": "韭菜200g、鸡蛋3个、盐", "method": "炒",
         "nutrition": "能量约210kcal，蛋白质16g，脂肪14g，碳水6g",
         "tags": ["家常", "快手", "低热量"]},
        {"dish": "西红柿蛋汤", "category": "汤羹", "ingredients": "番茄1个、鸡蛋2个、葱花、盐、香油", "method": "煮",
         "nutrition": "能量约80kcal，蛋白质10g，脂肪4g，碳水4g",
         "tags": ["清淡", "简单", "低热量", "暖胃"]},
        {"dish": "紫菜蛋花汤", "category": "汤羹", "ingredients": "干紫菜10g、鸡蛋2个、葱花、虾皮、盐、香油", "method": "煮",
         "nutrition": "能量约70kcal，蛋白质10g，脂肪3g，碳水3g",
         "tags": ["清淡", "简单", "低热量", "快手"]},
        {"dish": "冬瓜排骨汤", "category": "汤羹", "ingredients": "排骨300g、冬瓜500g、姜、枸杞、盐", "method": "炖",
         "nutrition": "能量约250kcal，蛋白质20g，脂肪15g，碳水8g",
         "tags": ["清淡", "滋补", "暖胃", "中低热量"]},
        {"dish": "玉米排骨汤", "category": "汤羹", "ingredients": "排骨300g、甜玉米1根、胡萝卜、姜、盐", "method": "炖",
         "nutrition": "能量约300kcal，蛋白质22g，脂肪16g，碳水18g",
         "tags": ["清淡", "滋补", "甜口", "中等热量"]},
    ]


def search_recipes(keywords: list[str], top_k: int = 5) -> list[dict]:
    """
    根据关键词检索内置菜谱库。
    使用简单的关键词匹配 + 标签匹配。
    """
    if not keywords:
        return random.sample(_BUILTIN_RECIPES, min(top_k, len(_BUILTIN_RECIPES)))

    scored = []
    kw_lower = [k.lower() for k in keywords]
    kw_text = " ".join(kw_lower)

    for recipe in _BUILTIN_RECIPES:
        score = 0.0
        text = (recipe["dish"] + recipe["category"] + " ".join(recipe["tags"]) + recipe["ingredients"]).lower()

        for kw in kw_lower:
            if kw in text:
                score += 1.0
            # 部分匹配
            for word in kw.split():
                if len(word) > 1 and word in text:
                    score += 0.3

        # 清淡/低脂/低热量 标签加权
        tags = " ".join(recipe["tags"]).lower()
        if any(w in tags for w in ["清淡", "低脂", "低热量", "清淡"]):
            if "清淡" in kw_text or "低脂" in kw_text or "健康" in kw_text or "减肥" in kw_text:
                score += 0.5
        if "高蛋白" in tags and ("高蛋白" in kw_text or "蛋白质" in kw_text):
            score += 0.5
        if "下饭" in tags and ("下饭" in kw_text or "家常" in kw_text):
            score += 0.3

        if score > 0:
            scored.append((score, recipe))

    scored.sort(key=lambda x: -x[0])
    return [r for _, r in scored[:top_k]]


def get_all_recipes() -> list[dict]:
    """获取全部内置菜谱"""
    return _BUILTIN_RECIPES.copy()


def format_recipes_for_prompt(recipes: list[dict], max_count: int = 3) -> str:
    """
    将菜谱列表格式化为提示词可用的文本。
    最多选 max_count 条，优先选择不同的 category。
    """
    if not recipes:
        return ""

    # 按类别去重选取
    selected = []
    seen_cats = set()
    for r in recipes:
        if r["category"] not in seen_cats:
            selected.append(r)
            seen_cats.add(r["category"])
        if len(selected) >= max_count:
            break
    if len(selected) < max_count:
        for r in recipes:
            if r not in selected:
                selected.append(r)
            if len(selected) >= max_count:
                break

    lines = ["参考菜谱："]
    for r in selected:
        lines.append(f"- {r['dish']}（{r['category']}）")
        lines.append(f"  食材：{r['ingredients']}")
        lines.append(f"  做法：{r['method']}")
        lines.append(f"  营养：{r['nutrition']}")
    return "\n".join(lines)
