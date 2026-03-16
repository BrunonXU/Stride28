"""
Provider 模块 - LLM 抽象层

使用工厂模式支持多个 LLM Provider 的无缝切换
"""

from .base import LLMProvider, EmbeddingProvider
from .tongyi import TongyiProvider, TongyiEmbeddingProvider
from .factory import ProviderFactory

__all__ = [
    "LLMProvider",
    "EmbeddingProvider",
    "TongyiProvider",
    "TongyiEmbeddingProvider",
    "ProviderFactory",
]
