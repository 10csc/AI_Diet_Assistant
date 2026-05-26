# ai_core/main.py
import argparse
import json
import sys
import os
import logging
from privacy import blur_personal_info
from models.base import init_providers, get_provider
from rag import build_rag_context, build_secondary_prompt, format_local_analysis
from utils import (
    sanitize_user_input,
    save_to_jsonl,
    call_with_retry,
    load_request_payload,
    sanitize_weather_payload,
    build_raw_input,
)
from validator import (
    validate_personal_info_fields,
    build_interrupt_result,
    INTERRUPT_CODE_SPEECHLESS,
)
from result_parser import parse_preprocess_result

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# ---- 日志配置 ----  
logger = logging.getLogger("diet_assistant")
logger.setLevel(logging.INFO)

_file_handler = logging.FileHandler(
    os.path.join(LOG_DIR, "service.log"),
    encoding="utf-8", delay=False,
)
_file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))
logger.addHandler(_file_handler)

_console_handler = logging.StreamHandler(sys.stderr)
_console_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
))
logger.addHandler(_console_handler)


# ---- 编码兼容 ----
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    import codecs
    if sys.stdout.encoding != 'UTF-8':
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer)
    if sys.stderr.encoding != 'UTF-8':
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer)


# ---- 模型初始化 ----
init_providers()


def resolve_request_args(args) -> dict:
    """从命令行参数或请求文件解析并组装请求参数字典。"""
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
        "recipe_profile": payload.get("recipe_profile", []),
    }

    # 环境变量传入 API Key（避免出现在命令行/临时文件中）
    env_primary_key = os.getenv("AI_DIET_PRIMARY_API_KEY", "")
    env_secondary_key = os.getenv("AI_DIET_SECONDARY_API_KEY", "")
    if env_primary_key and "|" not in resolved["primary_model_id"]:
        resolved["primary_model_id"] = f"{resolved['primary_model_id']}|{env_primary_key}"
    if env_secondary_key and "|" not in resolved["secondary_model_id"]:
        resolved["secondary_model_id"] = f"{resolved['secondary_model_id']}|{env_secondary_key}"

    if not resolved["user_input"]:
        raise ValueError("缺少 user_input")
    if not resolved["primary_model_id"]:
        raise ValueError("缺少 primary_model_id")

    resolved["weather"] = sanitize_weather_payload(resolved["weather"])
    resolved["use_secondary"] = bool(resolved["use_secondary"])
    return resolved


def preprocess_input(raw_input: str, primary_model_id: str) -> str:
    """根据模型 ID 查找对应的 Provider 并调用预处理。"""
    provider = get_provider(primary_model_id)
    safe_id = primary_model_id.split("|")[0] if "|" in primary_model_id else primary_model_id
    logger.info("使用一级模型: %s → %s", safe_id, type(provider).__name__)
    return provider.preprocess(raw_input, primary_model_id)


def main():
    parser = argparse.ArgumentParser(description="饮食推荐助手 - 支持两级模型调用")
    parser.add_argument("--request_file", type=str, default="", help="请求 JSON 文件路径")
    parser.add_argument("--user_input", type=str, default="", help="用户对话框输入（必需）")
    parser.add_argument("--personal_info", type=str, default="", help="用户个人信息（可选）")
    parser.add_argument("--weather", type=str, default="", help="天气数据（可选）")
    parser.add_argument("--primary_model_id", type=str, default="",
                        help="一级模型ID，格式：provider:model_name")
    parser.add_argument("--secondary_model_id", type=str, default="",
                        help="二级模型ID，格式同 primary_model_id")
    parser.add_argument("--use_secondary", action="store_true",
                        help="是否使用二级模型进行饮食推荐")

    args = parser.parse_args()

    try:
        resolved = resolve_request_args(args)

        logger.info("开始处理请求  primary_model=%s  use_secondary=%s",
                     resolved["primary_model_id"], resolved["use_secondary"])

        # 校验个人信息
        invalid_fields = validate_personal_info_fields(resolved["personal_info"])
        if invalid_fields:
            logger.warning("用户个人信息校验未通过: %s", ",".join(invalid_fields))
            result = build_interrupt_result(INTERRUPT_CODE_SPEECHLESS, invalid_fields)
            blurred = blur_personal_info(resolved["personal_info"])
            save_to_jsonl({
                "user_input": sanitize_user_input(resolved["user_input"]),
                "personal_info": blurred,
                "weather": resolved["weather"],
                "primary_model_id": resolved["primary_model_id"],
                "secondary_model_id": resolved["secondary_model_id"],
                "use_secondary": resolved["use_secondary"],
                "conversation_id": resolved["conversation_id"],
                "conversation_title": resolved["conversation_title"],
                "conversation_context": resolved["conversation_context"],
                "interrupt_code": INTERRUPT_CODE_SPEECHLESS,
                "invalid_fields": invalid_fields,
                "local_output": result["local_output"],
                "cloud_output": result["cloud_output"],
            }, LOG_DIR)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return

        # 模糊化 + 净化
        resolved["personal_info"] = blur_personal_info(resolved["personal_info"])
        resolved["user_input"] = sanitize_user_input(resolved["user_input"])

        raw_input = build_raw_input(
            resolved["user_input"], resolved["personal_info"],
            resolved["weather"], resolved["conversation_context"],
        )

        # 步骤 1：一级模型预处理
        raw_preprocess_output = call_with_retry(
            preprocess_input, [raw_input, resolved["primary_model_id"]],
            logger=logger,
        )
        preprocess_result = parse_preprocess_result(raw_preprocess_output)
        if preprocess_result.get("interrupt_code") == INTERRUPT_CODE_SPEECHLESS:
            logger.warning("一级模型判定输入无效，已截断")
            result = build_interrupt_result(INTERRUPT_CODE_SPEECHLESS)
            save_to_jsonl({
                "user_input": resolved["user_input"],
                "personal_info": resolved["personal_info"],
                "weather": resolved["weather"],
                "primary_model_id": resolved["primary_model_id"],
                "secondary_model_id": resolved["secondary_model_id"],
                "use_secondary": resolved["use_secondary"],
                "conversation_id": resolved["conversation_id"],
                "conversation_title": resolved["conversation_title"],
                "conversation_context": resolved["conversation_context"],
                "preprocess_raw_output": raw_preprocess_output,
                "preprocess_result": preprocess_result,
                "interrupt_code": INTERRUPT_CODE_SPEECHLESS,
                "local_output": result["local_output"],
                "cloud_output": result["cloud_output"],
            }, LOG_DIR)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return

        rag_context = build_rag_context(
            resolved["user_input"], resolved["personal_info"],
            resolved["weather"], preprocess_result=preprocess_result,
        )
        local_output = format_local_analysis(preprocess_result, rag_context)
        secondary_prompt = build_secondary_prompt(
            resolved["user_input"], preprocess_result, rag_context,
        )

        # 附加菜品偏好画像
        recipe_profile = resolved.get("recipe_profile", [])
        if recipe_profile and isinstance(recipe_profile, list):
            secondary_prompt += (
                f"\n\n用户历史菜品反馈：{json.dumps(recipe_profile, ensure_ascii=False)}\n"
                "请参考用户的历史反馈调整推荐，避免推荐踩过的菜品。"
            )

        # 步骤 2：二级模型推荐
        if resolved["use_secondary"] and resolved["secondary_model_id"]:
            sec_provider = get_provider(resolved["secondary_model_id"])
            cloud_output = call_with_retry(
                sec_provider.get_recommendation,
                [secondary_prompt],
                {"model_id": resolved["secondary_model_id"]},
                logger=logger,
            )
        else:
            cloud_output = {"mode": "only_local", "optimized_prompt": local_output}

        logger.info("处理完成")

        save_to_jsonl({
            "user_input": resolved["user_input"],
            "personal_info": resolved["personal_info"],
            "weather": resolved["weather"],
            "primary_model_id": resolved["primary_model_id"],
            "secondary_model_id": resolved["secondary_model_id"],
            "use_secondary": resolved["use_secondary"],
            "conversation_id": resolved["conversation_id"],
            "conversation_title": resolved["conversation_title"],
            "conversation_context": resolved["conversation_context"],
            "preprocess_raw_output": raw_preprocess_output,
            "preprocess_result": preprocess_result,
            "rag_context": rag_context,
            "local_output": local_output,
            "cloud_output": cloud_output,
        }, LOG_DIR)

        print(json.dumps(
            {"local_output": local_output, "cloud_output": cloud_output},
            ensure_ascii=False, indent=2,
        ))

    except Exception as exc:
        logger.exception("请求处理异常")
        print(json.dumps({
            "error": str(exc), "local_output": "", "cloud_output": None,
        }, ensure_ascii=False, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
