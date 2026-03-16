"""
Provider 抽象基类

设计原则：
1. 定义统一接口，业务代码不依赖具体服务商
2. 支持同步和异步调用
3. 支持流式输出
4. 便于 Mock 测试

面试话术：
> "Provider 抽象层解决了 LLM 调用的强耦合问题。通过抽象基类定义统一接口，
>  工厂模式根据配置创建具体 Provider。这样业务代码不依赖具体服务商，
>  我可以一行配置切换模型。"
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Generator, Optional
from pydantic import BaseModel


class Message(BaseModel):
    """对话消息模型"""
    role: str  # "system" | "user" | "assistant"
    content: str


class LLMResponse(BaseModel):
    """LLM 响应模型"""
    content: str
    model: str
    usage: Optional[Dict[str, Any]] = None  # Token 使用信息（可能嵌套）
    

class LLMProvider(ABC):
    """
    LLM Provider 抽象基类
    
    所有 LLM Provider（Tongyi、OpenAI、DeepSeek 等）必须实现此接口
    """
    
    @property
    @abstractmethod
    def model_name(self) -> str:
        """返回当前使用的模型名称"""
        pass
    
    @abstractmethod
    def chat(
        self, 
        messages: List[Message],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        """
        同步对话接口
        
        Args:
            messages: 对话历史
            temperature: 温度参数，控制输出随机性
            max_tokens: 最大输出 token 数
            **kwargs: 其他模型特定参数
            
        Returns:
            LLMResponse 对象
        """
        pass
    
    @abstractmethod
    def stream(
        self,
        messages: List[Message],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Generator[str, None, None]:
        """
        流式输出接口
        
        Args:
            messages: 对话历史
            temperature: 温度参数
            max_tokens: 最大输出 token 数
            **kwargs: 其他模型特定参数
            
        Yields:
            逐个输出的文本片段
        """
        pass
    
    def simple_chat(self, prompt: str, system_prompt: Optional[str] = None, max_tokens: Optional[int] = None) -> str:
        """
        简化的对话接口
        
        Args:
            prompt: 用户输入
            system_prompt: 系统提示词（可选）
            max_tokens: 最大输出 token 数（可选，默认使用模型默认值）
            
        Returns:
            模型回复的文本
        """
        messages = []
        if system_prompt:
            messages.append(Message(role="system", content=system_prompt))
        messages.append(Message(role="user", content=prompt))
        
        response = self.chat(messages, max_tokens=max_tokens)
        return response.content


class EmbeddingProvider(ABC):
    """
    Embedding Provider 抽象基类
    
    所有 Embedding Provider 必须实现此接口
    """
    
    @property
    @abstractmethod
    def embedding_dim(self) -> int:
        """返回向量维度"""
        pass
    
    @abstractmethod
    def embed_text(self, text: str) -> List[float]:
        """
        单文本向量化
        
        Args:
            text: 输入文本
            
        Returns:
            向量列表
        """
        pass
    
    @abstractmethod
    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """
        批量文本向量化
        
        Args:
            texts: 输入文本列表
            
        Returns:
            向量列表的列表
        """
        pass
    
    def embed_query(self, query: str) -> List[float]:
        """
        查询文本向量化（某些模型对 query 和 document 使用不同的编码）
        
        默认实现：直接调用 embed_text
        """
        return self.embed_text(query)
