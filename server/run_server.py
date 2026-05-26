"""
主后端服务器（Python / Flask）

跨平台运行，替代原有的 C++ 后端（server/backend.cpp 已标记 deprecated）。
功能：静态文件服务 + API 路由 + 调用 Python AI 引擎。

依赖: pip install flask flask-cors

使用:
    python server/run_server.py
    # 打开 http://localhost:8080
"""

import csv
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# 尝试导入 Flask，如果没有则提示安装
try:
    from flask import Flask, request, jsonify, send_from_directory
    from flask_cors import CORS
except ImportError:
    print("请先安装依赖: pip install flask flask-cors")
    sys.exit(1)

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent
AI_CORE_DIR = BASE_DIR / "ai_core"
SERVER_DIR = BASE_DIR / "server"
FRONTEND_DIR = SERVER_DIR / "frontend"
DATA_DIR = BASE_DIR / "data"
WEATHER_CITY_CSV = BASE_DIR / "weather_district_id.csv"

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")
CORS(app, origins=["http://localhost:8080", "http://127.0.0.1:8080"])  # 限制 CORS 来源

# 简单的内存速率限制
_rate_limit_records: dict[str, list[float]] = {}


FORBIDDEN_CONFIG_FIELDS = {"python_script", "static_dir", "port", "logs_dir"}

SENSITIVE_CONFIG_FIELDS = {"api_key", "ak"}


def load_config() -> dict:
    config_path = SERVER_DIR / "Config.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_config_safe() -> dict:
    """返回脱敏后的配置，隐藏 api_key、ak 和 cached_weather"""
    config = load_config()
    # 脱敏天气 API Key
    if "weather_api" in config and isinstance(config["weather_api"], dict):
        if "ak" in config["weather_api"] and config["weather_api"]["ak"]:
            config["weather_api"]["ak"] = "***"
        # 隐藏缓存的天气数据（含用户地理位置）
        if "cached_weather" in config["weather_api"]:
            config["weather_api"]["cached_weather"] = {}
    # 脱敏模型 API Key
    if "models" in config:
        for section in config["models"].values():
            if isinstance(section, dict) and "api_key" in section and section["api_key"]:
                section["api_key"] = "***"
    return config


def check_rate_limit(endpoint: str, max_requests: int = 6, window_seconds: int = 60) -> bool:
    """简单的滑动窗口速率限制，返回 True 表示允许请求"""
    now = time.time()
    records = _rate_limit_records.setdefault(endpoint, [])
    # 清理过期记录
    records[:] = [t for t in records if now - t <= window_seconds]
    if len(records) >= max_requests:
        return False
    records.append(now)
    return True


# API Key 映射到系统环境变量名
_API_KEY_PATHS = [
    (("models", "primary", "api_key"), "AI_DIET_PRIMARY_API_KEY"),
    (("models", "secondary", "api_key"), "AI_DIET_SECONDARY_API_KEY"),
    (("weather_api", "ak"), "AI_DIET_WEATHER_AK"),
]


def _set_env_key(name: str, value: str) -> None:
    """写入进程环境变量，尝试持久化到系统。"""
    os.environ[name] = value
    if platform.system() == "Windows":
        try:
            subprocess.run(["setx", name, value], capture_output=True, timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            pass


def _strip_apikeys_from_config(config: dict) -> dict:
    """
    从配置中提取 API Key 存入环境变量，并从配置中移除。
    直接原地修改并返回 config 本身（引用）。
    """
    for keys_path, env_name in _API_KEY_PATHS:
        # 取叶子节点前的路径
        *parent_keys, leaf = keys_path
        parent = config
        for k in parent_keys:
            if isinstance(parent, dict) and k in parent:
                parent = parent[k]
            else:
                parent = None
                break
        if isinstance(parent, dict):
            value = parent.get(leaf, "")
            if value and isinstance(value, str) and value.strip() not in ("", "***"):
                _set_env_key(env_name, value.strip())
            # 清除配置中的 Key（防止明文落盘）
            parent[leaf] = ""
    return config


def _mark_apikeys_from_env(config: dict) -> dict:
    """读取时标注系统环境变量中已设置的 Key。"""
    result = dict(config)
    for keys_path, env_name in _API_KEY_PATHS:
        if os.environ.get(env_name, ""):
            *parent_keys, leaf = keys_path
            parent = result
            for k in parent_keys:
                if k not in parent:
                    parent[k] = {}
                parent = parent[k]
            parent[leaf] = "***"
    return result


def _desensitize_config_for_write(config: dict) -> dict:
    """检查配置中是否包含禁止通过 API 修改的字段"""
    for field in FORBIDDEN_CONFIG_FIELDS:
        if field in config:
            raise ValueError(f"禁止通过 API 修改字段: {field}")
    return config


def call_python_ai(request_data: dict) -> str:
    """调用 AI 引擎 main.py，通过环境变量传递 API Key"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(request_data, f, ensure_ascii=False)
        temp_path = f.name

    # 构建子进程环境变量，传递 API Key
    # 如果请求中传的是 "***"（前端脱敏占位），则改用系统环境变量中的实际值
    def _resolve_key(request_key: str, env_name: str) -> str:
        val = request_data.get(request_key, "")
        if val and val != "***":
            return val
        return os.environ.get(env_name, "")

    env = os.environ.copy()
    env["AI_DIET_PRIMARY_API_KEY"] = _resolve_key("primary_api_key", "AI_DIET_PRIMARY_API_KEY")
    env["AI_DIET_SECONDARY_API_KEY"] = _resolve_key("secondary_api_key", "AI_DIET_SECONDARY_API_KEY")

    try:
        result = subprocess.run(
            [sys.executable, str(AI_CORE_DIR / "main.py"),
             "--request_file", temp_path],
            capture_output=True, text=True, timeout=300,
            cwd=str(AI_CORE_DIR),
            env=env,
        )
        output = result.stdout
        if not output and result.stderr:
            output = f'{{"error": "{result.stderr.strip()}"}}'
        return output or '{"error": "empty output"}'
    except subprocess.TimeoutExpired:
        return '{"error": "AI engine timeout"}'
    finally:
        os.unlink(temp_path)


# ----- API 路由 -----

@app.route("/")
def index():
    return send_from_directory(str(FRONTEND_DIR), "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(str(FRONTEND_DIR), filename)


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    config_path = SERVER_DIR / "Config.json"
    if request.method == "GET":
        if config_path.exists():
            safe_config = get_config_safe()
            safe_config = _mark_apikeys_from_env(safe_config)
            return jsonify(safe_config)
        return jsonify({"error": "config not found"}), 500
    else:
        try:
            new_config = _desensitize_config_for_write(request.json or {})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        # 提取 API Key 存入环境变量，清除配置中的明文 Key
        new_config = _strip_apikeys_from_config(new_config)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(new_config, f, ensure_ascii=False, indent=4)
        return jsonify({"ok": True})


@app.route("/api/chat", methods=["POST"])
def api_chat():
    # 速率限制：每分钟最多 6 次
    if not check_rate_limit("/api/chat", max_requests=6, window_seconds=60):
        return jsonify({"error": "请求过于频繁，请稍后再试"}), 429

    data = request.json or {}
    # 限制用户输入长度
    user_input = data.get("user_input", "")
    if isinstance(user_input, str) and len(user_input) > 2000:
        data["user_input"] = user_input[:2000]

    output = call_python_ai(data)
    return app.response_class(output, mimetype="application/json")


@app.route("/api/favorites", methods=["GET"])
def api_favorites():
    fav_path = DATA_DIR / "favorites.json"
    if fav_path.exists():
        with open(fav_path, "r", encoding="utf-8") as f:
            return app.response_class(f.read(), mimetype="application/json")
    return jsonify([])


@app.route("/api/favorites/add", methods=["POST"])
def api_favorites_add():
    fav_path = DATA_DIR / "favorites.json"
    existing = []
    if fav_path.exists():
        with open(fav_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    existing.append(request.json)
    with open(fav_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    return jsonify({"ok": True})


@app.route("/api/favorites/remove", methods=["POST"])
def api_favorites_remove():
    dish_name = (request.json or {}).get("dish_name", "")
    fav_path = DATA_DIR / "favorites.json"
    if fav_path.exists():
        with open(fav_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        existing = [i for i in existing if i.get("dish_name") != dish_name]
        with open(fav_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
    return jsonify({"ok": True})


@app.route("/api/feedback", methods=["POST"])
def api_feedback():
    profile_path = DATA_DIR / "recipe_profile.json"
    existing = []
    if profile_path.exists():
        with open(profile_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    existing.append(request.json)
    with open(profile_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    return jsonify({"ok": True})


@app.route("/api/history/delete", methods=["POST"])
def api_history_delete():
    logs_dir = AI_CORE_DIR / "logs"
    data = request.json or {}
    conversation_id = data.get("conversation_id", "")
    log_file = data.get("log_file", "")
    line_index = data.get("line_index", -1)
    if not log_file:
        return jsonify({"error": "missing log_file"}), 400
    # 验证 log_file 不包含路径遍历字符且扩展名为 .jsonl
    if ".." in log_file or "/" in log_file or "\\" in log_file:
        return jsonify({"error": "invalid log_file"}), 400
    if not log_file.endswith(".jsonl"):
        return jsonify({"error": "log_file must be .jsonl"}), 400
    log_path = (logs_dir / log_file).resolve()
    # 确认解析后的路径仍在 logs_dir 内
    if not str(log_path).startswith(str(logs_dir.resolve())):
        return jsonify({"error": "invalid log_file path"}), 400
    if log_path.exists():
        content = log_path.read_text(encoding="utf-8").splitlines()
        if line_index >= 0 and line_index < len(content):
            content.pop(line_index)
        log_path.write_text("\n".join(content) + "\n", encoding="utf-8")
    return jsonify({"ok": True})


@app.route("/api/weather/cities")
def api_weather_cities():
    """提供城市列表数据（CSV → JSON）"""
    items = []
    if WEATHER_CITY_CSV.exists():
        with open(WEATHER_CITY_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("district_id") == row.get("city_geocode"):
                    city_name = row.get("city") or row.get("district", "")
                    display_name = (city_name if row.get("province") == city_name
                                    else f"{row.get('province', '')} {city_name}").strip()
                    items.append({
                        "district_id": row["district_id"],
                        "city_name": city_name,
                        "display_name": display_name
                    })
    return jsonify({"items": items})


if __name__ == "__main__":
    config = load_config()
    port = config.get("server", {}).get("port", 8080)
    print(f"[INFO] Linux backend starting on http://0.0.0.0:{port}")
    print(f"[INFO] Frontend: {FRONTEND_DIR}")
    print(f"[INFO] AI engine: {AI_CORE_DIR}")
    app.run(host="0.0.0.0", port=port, debug=False)
