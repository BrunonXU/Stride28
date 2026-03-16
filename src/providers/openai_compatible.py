"""
OpenAI 兼容 Provider

一个 class 搞定所有兼容 OpenAI API 格式的服务商：
- OpenAI (https://api.openai.com/v1)
- DeepSeek (https://api.deepseek.com)
- 智谱 GLM (https://open.bigmodel.cn/api/paas/v4)
- 其他兼容 API

面试话术：
> "国产大模型（DeepSeek、智谱、Moonshot 等）都选择兼容 OpenAI API 格式，
>  这是 API 标准化的网络效应。我用一个 OpenAICompatibleProvider + base_url 参数
>  就覆盖了所有兼容服务商，比每个厂商写一个 Provider 优雅得多。"
"""

import os
from typing import List, Generator, Optional

from openai import OpenAI
from langsmith.wrappers import wrap_openai

from .base import LLMProvider, Message, LLMResponse


# 预设的 Provider 配置
PROVIDER_PRESETS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "env_key": "OPENAI_API_KEY",
        "models": ["gpt-4o-mini", "gpt-4o", "gpt-5", "o3"],
        "default_model": "gpt-4o-mini",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "env_key": "DEEPSEEK_API_KEY",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "default_model": "deepseek-chat",
    },
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "env_key": "ZHIPU_API_KEY",
        "models": ["glm-4.7-flash", "glm-5"],
        "default_model": "glm-4.7-flash",
    },
}


class OpenAICompatibleProvider(LLMProvider):
    """兼容 OpenAI API 格式的通用 LLM Provider"""

    def __init__(
        self,
        model: str = "deepseek-chat",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        provider_name: Optional[str] = None,
        **kwargs,
    ):
        self._model = model
        self._provider_name = provider_name

        # 根据 provider_name 自动填充 base_url 和 api_key
        preset = PROVIDER_PRESETS.get(provider_name, {}) if provider_name else {}

        self._base_url = base_url or preset.get("base_url", "https://api.deepseek.com")
        env_key = preset.get("env_key", "OPENAI_API_KEY")
        self._api_key = api_key or os.getenv(env_key)

        if not self._api_key:
            raise ValueError(
                f"{env_key} not found. "
                f"Please set it in .env or pass api_key parameter."
            )

        self._client = wrap_openai(OpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
        ))

    @property
    def model_name(self) -> str:
        return self._model

    def chat(
        self,
        messages: List[Message],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> LLMResponse:
        """同步对话"""
        oai_messages = [{"role": m.role, "content": m.content} for m in messages]

        params = {
            "model": self._model,
            "messages": oai_messages,
            "temperature": temperature,
        }
        if max_tokens:
            params["max_tokens"] = max_tokens

        response = self._client.chat.completions.create(**params)

        usage = None
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return LLMResponse(
            content=response.choices[0].message.content or "",
            model=response.model or self._model,
            usage=usage,
        )

    def stream(
        self,
        messages: List[Message],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> Generator[str, None, None]:
        """流式输出"""
        oai_messages = [{"role": m.role, "content": m.content} for m in messages]

        params = {
            "model": self._model,
            "messages": oai_messages,
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens:
            params["max_tokens"] = max_tokens

        for chunk in self._client.chat.completions.create(**params):
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
