"""
Tongyi/Qwen Provider 实现

使用 LangChain 的 ChatTongyi 和 DashScopeEmbeddings
这样可以自动接入 LangSmith 追踪

技术栈选择理由：
1. ChatTongyi 是 LangChain 官方支持的组件，简历关键词 ✔️
2. DashScopeEmbeddings 同样是 LangChain 组件
3. 使用 LangChain 组件可以自动被 LangSmith 追踪
"""

import os
from typing import List, Generator, Optional, Dict, Any
import dashscope

from langchain_community.chat_models import ChatTongyi
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from .base import LLMProvider, EmbeddingProvider, Message, LLMResponse


class TongyiProvider(LLMProvider):
    """
    Tongyi/Qwen LLM Provider
    
    基于 LangChain 的 ChatTongyi 实现
    """
    
    def __init__(
        self,
        model: str = "qwen-turbo",
        api_key: Optional[str] = None,
        **kwargs
    ):
        """
        初始化 Tongyi Provider
        
        Args:
            model: 模型名称，默认 qwen-turbo
                   可选：qwen-plus, qwen-max, qwen-turbo
            api_key: DashScope API Key，默认从环境变量读取
            **kwargs: 其他 ChatTongyi 参数
        """
        self._model = model
        self._api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        
        if not self._api_key:
            raise ValueError(
                "DASHSCOPE_API_KEY not found. "
                "Please set it in .env file or pass it as api_key parameter."
            )
        
        # 显式设置 dashscope 全局 key，防止 SDK 读取不到
        dashscope.api_key = self._api_key
        
        # 确保环境变量存在
        if self._api_key:
            os.environ["DASHSCOPE_API_KEY"] = self._api_key

        # 初始化 LangChain ChatTongyi
        # 注意: LangChain 0.3.x 中建议使用 model_name 参数
        self._llm = ChatTongyi(
            model_name=model,
            dashscope_api_key=self._api_key,
            request_timeout=60,
            **kwargs
        )
    
    @property
    def model_name(self) -> str:
        return self._model
    
    def _convert_messages(self, messages: List[Message]) -> List:
        """将 Message 转换为 LangChain 消息格式"""
        lc_messages = []
        for msg in messages:
            if msg.role == "system":
                lc_messages.append(SystemMessage(content=msg.content))
            elif msg.role == "user":
                lc_messages.append(HumanMessage(content=msg.content))
            elif msg.role == "assistant":
                lc_messages.append(AIMessage(content=msg.content))
        return lc_messages
    
    def chat(
        self,
        messages: List[Message],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        """同步对话"""
        lc_messages = self._convert_messages(messages)
        
        # 更新参数
        if temperature != 0.7:
            self._llm.temperature = temperature
        if max_tokens:
            self._llm.max_tokens = max_tokens
            
        # 调用 LLM
        response = self._llm.invoke(lc_messages)
        
        # 提取 token 使用信息（如果有）
        usage = None
        if hasattr(response, "response_metadata"):
            metadata = response.response_metadata
            if "token_usage" in metadata:
                usage = metadata["token_usage"]
        
        return LLMResponse(
            content=response.content,
            model=self._model,
            usage=usage
        )
    
    def stream(
        self,
        messages: List[Message],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Generator[str, None, None]:
        """流式输出"""
        lc_messages = self._convert_messages(messages)
        
        # 更新参数
        if temperature != 0.7:
            self._llm.temperature = temperature
        if max_tokens:
            self._llm.max_tokens = max_tokens
        
        # 流式调用
        for chunk in self._llm.stream(lc_messages):
            if chunk.content:
                yield chunk.content


class TongyiEmbeddingProvider(EmbeddingProvider):
    """
    Tongyi/DashScope Embedding Provider
    
    基于 LangChain 的 DashScopeEmbeddings 实现
    """
    
    def __init__(
        self,
        model: str = "text-embedding-v2",
        api_key: Optional[str] = None,
        **kwargs
    ):
        """
        初始化 Embedding Provider
        
        Args:
            model: 模型名称，默认 text-embedding-v2
            api_key: DashScope API Key
            **kwargs: 其他参数
        """
        self._model = model
        self._api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        
        if not self._api_key:
            raise ValueError(
                "DASHSCOPE_API_KEY not found. "
                "Please set it in .env file or pass it as api_key parameter."
            )
        
        # 初始化 LangChain DashScopeEmbeddings
        self._embeddings = DashScopeEmbeddings(
            model=model,
            dashscope_api_key=self._api_key,
            **kwargs
        )
        
        # text-embedding-v2 的向量维度是 1536
        self._dim = 1536
    
    @property
    def embedding_dim(self) -> int:
        return self._dim
    
    def embed_text(self, text: str) -> List[float]:
        """单文本向量化"""
        return self._embeddings.embed_documents([text])[0]
    
    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """批量文本向量化"""
        return self._embeddings.embed_documents(texts)
    
    def embed_query(self, query: str) -> List[float]:
        """查询文本向量化"""
        return self._embeddings.embed_query(query)
