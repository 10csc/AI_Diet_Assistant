"""
模型提供者抽象基类

定义统一的模型提供者接口。所有模型供应商（Ollama、DeepSeek、llama.cpp）
均需实现此接口，以便在 main.py 中统一调用。

未来 RAG → Agent 演进时，每个 provider 可独立演化为一个 Agent。
"""

from abc import ABC, abstractmethod
from typing import Optional


class BaseModelProvider(ABC):
    """模型提供者抽象基类"""

    @classmethod
    @abstractmethod
    def key_prefix(cls) -> str:
        """模型 ID 前缀，用于匹配，如 'ollama:', 'deepseek:', 'llamacpp:'"""
        ...

    @abstractmethod
    def preprocess(self, raw_input: str, model_id: str) -> str:
        """
        一级模型：预处理用户输入，返回分析结果 JSON 字符串。

        各 provider 自行处理 API 调用、超时、错误处理。
        """
        ...

    def get_recommendation(self, prompt: str, model_id: str) -> dict:
        """
        二级模型：生成饮食推荐。

        非所有 provider 都支持二级模型，默认抛出 NotImplementedError。
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} 不支持二级模型推荐"
        )


# 全局 Provider 注册表：前缀 → 实例
_PROVIDER_REGISTRY: dict[str, BaseModelProvider] = {}


def register_provider(provider: BaseModelProvider) -> None:
    """注册一个模型提供者实例"""
    prefix = provider.key_prefix()
    _PROVIDER_REGISTRY[prefix] = provider


def get_provider(model_id: str) -> BaseModelProvider:
    """根据模型 ID 查找对应的 Provider"""
    for prefix, provider in _PROVIDER_REGISTRY.items():
        if model_id.startswith(prefix):
            return provider
    raise ValueError(f"不支持的模型 ID: {model_id}")


def list_providers() -> list[str]:
    """列出所有已注册的 provider 前缀"""
    return list(_PROVIDER_REGISTRY.keys())


def init_providers() -> None:
    """初始化并注册所有内置 Provider"""
    from .ollama_import import OllamaProvider
    from .cloudmodel_import import DeepSeekProvider
    from .llamacpp_import import LlamaCppProvider
    register_provider(OllamaProvider())
    register_provider(DeepSeekProvider())
    register_provider(LlamaCppProvider())
