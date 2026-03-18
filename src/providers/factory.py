"""
Provider 工厂

使用工厂模式根据配置创建具体的 Provider 实例

面试话术：
> "工厂模式的好处是业务代码不需要知道具体用哪个 Provider，
>  只需要调用 ProviderFactory.create('tongyi')，工厂会根据配置
>  返回正确的 Provider 实例。这样切换模型只需要改配置，不需要改代码。"
"""

import os
from typing import Dict, Type, Optional

from .base import LLMProvider, EmbeddingProvider
from .tongyi import TongyiProvider, TongyiEmbeddingProvider
from .openai_compatible import OpenAICompatibleProvider


class ProviderFactory:
    """
    Provider 工厂类
    
    负责根据配置创建具体的 Provider 实例
    """
    
    # 注册的 LLM Provider
    _llm_providers: Dict[str, Type[LLMProvider]] = {
        "tongyi": TongyiProvider,
        "qwen": TongyiProvider,  # 别名
        "openai": OpenAICompatibleProvider,
        "deepseek": OpenAICompatibleProvider,
        "zhipu": OpenAICompatibleProvider,
    }
    
    # 注册的 Embedding Provider
    _embedding_providers: Dict[str, Type[EmbeddingProvider]] = {
        "tongyi": TongyiEmbeddingProvider,
        "dashscope": TongyiEmbeddingProvider,  # 别名
        # 未来扩展：
        # "openai": OpenAIEmbeddingProvider,
    }
    
    @classmethod
    def create_llm(
        cls,
        provider_name: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs
    ) -> LLMProvider:
        """
        创建 LLM Provider 实例
        
        Args:
            provider_name: Provider 名称，默认从环境变量 DEFAULT_PROVIDER 读取
            model: 模型名称，默认从环境变量 DEFAULT_MODEL 读取
            **kwargs: 其他参数传递给 Provider
            
        Returns:
            LLMProvider 实例
            
        Raises:
            ValueError: 如果 Provider 不存在
        """
        # 默认值
        provider_name = provider_name or os.getenv("DEFAULT_PROVIDER", "deepseek")
        model = model or os.getenv("DEFAULT_MODEL", "deepseek-chat")
        
        # 查找 Provider
        provider_name = provider_name.lower()
        if provider_name not in cls._llm_providers:
            available = list(cls._llm_providers.keys())
            raise ValueError(
                f"Unknown LLM provider: {provider_name}. "
                f"Available: {available}"
            )
        
        # 创建实例
        provider_class = cls._llm_providers[provider_name]
        # OpenAICompatibleProvider 需要 provider_name 来查找预设配置
        if provider_class is OpenAICompatibleProvider:
            return provider_class(model=model, provider_name=provider_name, **kwargs)
        return provider_class(model=model, **kwargs)
    
    @classmethod
    def create_embedding(
        cls,
        provider_name: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs
    ) -> EmbeddingProvider:
        """
        创建 Embedding Provider 实例
        
        Args:
            provider_name: Provider 名称
            model: 模型名称
            **kwargs: 其他参数
            
        Returns:
            EmbeddingProvider 实例
        """
        # 默认值：优先读 EMBEDDING_PROVIDER，与 LLM 的 DEFAULT_PROVIDER 解耦
        provider_name = provider_name or os.getenv("EMBEDDING_PROVIDER") or os.getenv("DEFAULT_PROVIDER", "tongyi")
        model = model or "text-embedding-v2"
        
        # 查找 Provider
        provider_name = provider_name.lower()
        if provider_name not in cls._embedding_providers:
            available = list(cls._embedding_providers.keys())
            raise ValueError(
                f"Unknown embedding provider: {provider_name}. "
                f"Available: {available}"
            )
        
        # 创建实例
        provider_class = cls._embedding_providers[provider_name]
        return provider_class(model=model, **kwargs)
    
    @classmethod
    def register_llm(cls, name: str, provider_class: Type[LLMProvider]):
        """注册新的 LLM Provider"""
        cls._llm_providers[name.lower()] = provider_class
    
    @classmethod
    def register_embedding(cls, name: str, provider_class: Type[EmbeddingProvider]):
        """注册新的 Embedding Provider"""
        cls._embedding_providers[name.lower()] = provider_class
    
    @classmethod
    def list_llm_providers(cls) -> list:
        """列出所有可用的 LLM Provider"""
        return list(cls._llm_providers.keys())
    
    @classmethod
    def list_embedding_providers(cls) -> list:
        """列出所有可用的 Embedding Provider"""
        return list(cls._embedding_providers.keys())
