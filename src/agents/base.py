"""
Agent 基类

定义所有 Agent 的通用接口和行为

设计亮点：
1. 抽象基类 (ABC) - 强制子类实现 run() 方法
2. 依赖注入 - LLM Provider 通过构造函数传入
3. 类属性定义 - name, system_prompt 由子类覆盖

面试话术：
> "我用抽象基类定义 Agent 接口，所有 Agent 必须实现 run() 方法。
>  LLM Provider 通过构造函数注入，方便测试时 Mock。
>  每个 Agent 有自己的 system_prompt，决定了它的'人设'。"
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from src.providers import LLMProvider, ProviderFactory
from src.core import Config


class BaseAgent(ABC):
    """
    Agent 抽象基类
    
    所有功能 Agent 必须继承此类
    """
    
    # Agent 名称，子类必须定义
    name: str = "BaseAgent"
    
    # Agent 描述
    description: str = ""
    
    # 系统提示词
    system_prompt: str = ""
    
    def __init__(
        self,
        llm_provider: Optional[LLMProvider] = None,
        config: Optional[Config] = None,
        on_event: Optional[Any] = None,
    ):
        """
        初始化 Agent
        
        Args:
            llm_provider: LLM Provider，默认使用工厂创建
            config: 配置对象
            on_event: 事件回调函数 (event_type, name, detail)
        """
        self.config = config or Config.get()
        self.llm = llm_provider or ProviderFactory.create_llm()
        self.on_event = on_event

    def _emit_event(self, event_type: str, name: str, detail: str = ""):
        """发射追踪事件"""
        if self.on_event:
            self.on_event(event_type, name, detail)
    
    @abstractmethod
    def run(self, input_data: Any, **kwargs) -> Any:
        """
        运行 Agent
        
        Args:
            input_data: 输入数据
            **kwargs: 其他参数
            
        Returns:
            Agent 输出
        """
        pass
    
    def _call_llm(self, prompt: str, system_prompt: Optional[str] = None, max_tokens: Optional[int] = None) -> str:
        """
        调用 LLM

        Args:
            prompt: 用户提示
            system_prompt: 系统提示（默认使用类属性）
            max_tokens: 最大输出 token 数（默认不限制，使用模型默认值）

        Returns:
            LLM 响应
        """
        sp = system_prompt or self.system_prompt
        return self.llm.simple_chat(prompt, system_prompt=sp, max_tokens=max_tokens)

    
    def __repr__(self):
        return f"{self.name}(llm={self.llm.model_name})"
