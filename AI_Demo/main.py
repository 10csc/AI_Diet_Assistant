# AI_Demo/main.py
import argparse
import json
import sys
import os
import time
import logging
from datetime import datetime
from typing import Optional
from models.ollama_import import preprocess_with_ollama
from models.cloudmodel_import import get_diet_recommendation, preprocess_with_deepseek

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# ---- 日志配置（使用标准库，无需外部依赖） ----
logger = logging.getLogger("diet_assistant")
logger.setLevel(logging.INFO)

# 文件日志 — 统一记录到 service.log
_file_handler = logging.FileHandler(
    os.path.join(LOG_DIR, "service.log"),
    encoding="utf-8",
    delay=False,
)
_file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))
logger.addHandler(_file_handler)

# 控制台日志 — 输出到 stderr，不影响 stdout 的 JSON 结果
_console_handler = logging.StreamHandler(sys.stderr)
_console_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
))
logger.addHandler(_console_handler)


# 设置标准输出编码（兼容性处理）
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore
except Exception:
    import codecs
    if sys.stdout.encoding != 'UTF-8':
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer)
    if sys.stderr.encoding != 'UTF-8':
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer)


# ---- 一级模型预处理函数注册表（扩展模型供应商时只需在此添加） ----
PREPROCESSOR_MAP = {
    "ollama:": preprocess_with_ollama,
    "deepseek:": preprocess_with_deepseek,
}


# ---- 工具函数 ----


def save_to_jsonl(record: dict) -> None:
    """
    保存一条记录到 JSONL 日志文件。

    :param record: 包含所有待保存字段的字典（timestamp 由本函数自动补充）
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    file_path = os.path.join(LOG_DIR, f"{today_str}.jsonl")
    record["timestamp"] = datetime.now().isoformat()
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_raw_input(
    user_input: str,
    personal_info: str = "",
    weather: str = "",
    conversation_context: str = "",
) -> str:
    """将多个可选部分组合成完整的原始输入文本"""
    parts = []
    if conversation_context:
        parts.append(f"历史对话上下文：{conversation_context}")
    if user_input:
        parts.append(f"用户对话框输入：{user_input}")
    if personal_info:
        parts.append(f"用户个人信息：{personal_info}")
    if weather:
        parts.append(f"天气数据：{weather}")
    return "\n".join(parts) if parts else ""


def load_request_payload(request_file: str) -> dict:
    with open(request_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("request_file 内容必须为 JSON 对象")
    return data


def _relative_period_label(index: int) -> str:
    labels = ["近期", "接下来", "后续", "再后续"]
    if index < len(labels):
        return labels[index]
    return f"后续第{index + 1}阶段"


def sanitize_weather_payload(weather_text: str) -> str:
    """
    天气脱敏：
    - 保留天气趋势能力（now/forecasts/indexes/alerts）
    - 去除具体日期和具体时间信息，避免暴露精确时刻
    """
    if not weather_text:
        return weather_text

    try:
        weather_obj = json.loads(weather_text)
    except (TypeError, json.JSONDecodeError):
        return weather_text

    if not isinstance(weather_obj, dict):
        return weather_text

    now_obj = weather_obj.get("now")
    if isinstance(now_obj, dict):
        now_obj["uptime"] = "近期"

    forecasts = weather_obj.get("forecasts")
    if isinstance(forecasts, list):
        for idx, item in enumerate(forecasts):
            if not isinstance(item, dict):
                continue
            item.pop("date", None)
            item.pop("week", None)
            item["period"] = _relative_period_label(idx)

    return json.dumps(weather_obj, ensure_ascii=False, separators=(",", ":"))


def resolve_request_args(args) -> dict:
    payload = load_request_payload(args.request_file) if args.request_file else {}

    resolved = {
        "user_input": payload.get("user_input", args.user_input),
        "personal_info": payload.get("personal_info", args.personal_info),
        "weather": payload.get("weather", args.weather),
        "primary_model_id": payload.get("primary_model_id", args.primary_model_id),
        "secondary_model_id": payload.get("secondary_model_id", args.secondary_model_id),
        "use_secondary": payload.get("use_secondary", args.use_secondary),
        "conversation_id": payload.get("conversation_id", ""),
        "conversation_title": payload.get("conversation_title", ""),
        "conversation_context": payload.get("conversation_context", ""),
    }

    if not resolved["user_input"]:
        raise ValueError("缺少 user_input")
    if not resolved["primary_model_id"]:
        raise ValueError("缺少 primary_model_id")

    resolved["weather"] = sanitize_weather_payload(resolved["weather"])
    resolved["use_secondary"] = bool(resolved["use_secondary"])
    return resolved


def _call_with_retry(
    func,
    args,
    kwargs=None,
    max_retries: int = 2,
    base_delay: float = 1.0,
):
    """
    带指数退避重试的通用调用封装。

    当被调用函数抛出异常时，按 1s → 2s → 4s 间隔重试。
    所有重试均失败后，抛出最后一次捕获的异常。

    :param func: 被调用的可调用对象
    :param args: 位置参数列表
    :param kwargs: 关键字参数字典
    :param max_retries: 最大重试次数（不含首次尝试），默认 2
    :param base_delay: 初始等待秒数，默认 1.0
    """
    if kwargs is None:
        kwargs = {}
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = base_delay * (2**attempt)
                logger.warning(
                    "调用 %s.%s 失败（第 %d 次），%.1fs 后重试: %s",
                    func.__module__,
                    func.__name__,
                    attempt + 1,
                    delay,
                    exc,
                )
                time.sleep(delay)
    assert last_exc is not None
    logger.error(
        "调用 %s.%s 已重试 %d 次，全部失败: %s",
        func.__module__,
        func.__name__,
        max_retries,
        last_exc,
    )
    raise last_exc


def preprocess_input(raw_input: str, primary_model_id: str) -> str:
    """根据模型 ID 前缀查找对应的预处理函数并调用"""
    for prefix, func in PREPROCESSOR_MAP.items():
        if primary_model_id.startswith(prefix):
            logger.info(
                "使用一级模型: %s → %s.%s",
                primary_model_id,
                func.__module__,
                func.__name__,
            )
            return func(raw_input, model_id=primary_model_id)
    raise ValueError(f"不支持的一级模型: {primary_model_id}")


def main():
    parser = argparse.ArgumentParser(description="饮食推荐助手 - 支持两级模型调用")
    parser.add_argument("--request_file", type=str, default="", help="请求 JSON 文件路径")
    parser.add_argument("--user_input", type=str, default="", help="用户对话框输入（必需）")
    parser.add_argument(
        "--personal_info", type=str, default="", help="用户个人信息（可选，JSON或纯文本）"
    )
    parser.add_argument("--weather", type=str, default="", help="天气数据（可选，JSON或纯文本）")
    parser.add_argument(
        "--primary_model_id",
        type=str,
        default="",
        help="一级模型ID，格式：provider:model_name，例如 ollama:deepseek-r1:7b",
    )
    parser.add_argument(
        "--secondary_model_id",
        type=str,
        default="",
        help="二级模型ID，格式同primary_model_id，例如 deepseek:deepseek-chat",
    )
    parser.add_argument(
        "--use_secondary",
        action="store_true",
        help="是否使用二级模型进行饮食推荐，不加此参数则只返回一级模型预处理结果",
    )

    args = parser.parse_args()

    try:
        resolved = resolve_request_args(args)

        logger.info(
            "开始处理请求  primary_model=%s  use_secondary=%s",
            resolved["primary_model_id"],
            resolved["use_secondary"],
        )

        # 构建完整原始输入
        raw_input = build_raw_input(
            resolved["user_input"],
            resolved["personal_info"],
            resolved["weather"],
            resolved["conversation_context"],
        )

        # 步骤1：使用一级模型预处理（带自动重试）
        local_output = _call_with_retry(
            preprocess_input, [raw_input, resolved["primary_model_id"]]
        )

        if resolved["use_secondary"] and resolved["secondary_model_id"]:
            # 步骤2：使用二级模型生成饮食推荐（带自动重试）
            cloud_output = _call_with_retry(
                get_diet_recommendation,
                [local_output],
                {"model_id": resolved["secondary_model_id"]},
            )
        else:
            cloud_output = {"mode": "only_local", "optimized_prompt": local_output}

        logger.info("处理完成")

        # 保存历史日志
        save_to_jsonl(
            {
                "user_input": resolved["user_input"],
                "personal_info": resolved["personal_info"],
                "weather": resolved["weather"],
                "primary_model_id": resolved["primary_model_id"],
                "secondary_model_id": resolved["secondary_model_id"],
                "use_secondary": resolved["use_secondary"],
                "conversation_id": resolved["conversation_id"],
                "conversation_title": resolved["conversation_title"],
                "conversation_context": resolved["conversation_context"],
                "local_output": local_output,
                "cloud_output": cloud_output,
            }
        )

        result = {"local_output": local_output, "cloud_output": cloud_output}
        print(json.dumps(result, ensure_ascii=False, indent=2))

    except Exception as exc:
        logger.exception("请求处理异常")  # 自动打印完整的 traceback
        error_result = {
            "error": str(exc),
            "local_output": "",
            "cloud_output": None,
        }
        print(json.dumps(error_result, ensure_ascii=False, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()