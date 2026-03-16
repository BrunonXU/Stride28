"""
LangSmith 追踪模块

集成 LangSmith 实现全链路追踪

技术要点：
1. LangChain 组件（ChatTongyi、DashScopeEmbeddings）自动被追踪
2. 自研代码需要手动标记 Trace

环境变量配置：
- LANGCHAIN_TRACING_V2=true  # 开启追踪
- LANGCHAIN_API_KEY=lsv2_xxx  # API Key
- LANGCHAIN_PROJECT=stride28  # 项目名

面试话术：
> "LangSmith 解决了 Agent 系统难以调试的问题。通过全链路追踪，
>  我可以看到每次 LLM 调用的输入输出、Token 消耗、响应时间。
>  有一次发现生成计划特别慢，通过 Trace 定位到是 GitHub API 超时。"
"""

import os
import functools
from typing import Callable, Any, Optional
from contextlib import contextmanager

# 尝试导入 LangSmith
try:
    from langsmith import traceable
    from langsmith.run_trees import RunTree
    LANGSMITH_AVAILABLE = True
except ImportError:
    LANGSMITH_AVAILABLE = False
    traceable = None
    RunTree = None


def setup_tracing(project_name: Optional[str] = None) -> bool:
    """
    设置追踪
    
    Args:
        project_name: 项目名称（可选）
        
    Returns:
        是否成功启用追踪
    """
    # 检查环境变量
    tracing_enabled = os.getenv("LANGCHAIN_TRACING_V2", "").lower() == "true"
    api_key = os.getenv("LANGCHAIN_API_KEY") or os.getenv("LANGSMITH_API_KEY")
    
    if not tracing_enabled:
        print("ℹ️  LangSmith tracing is disabled. Set LANGCHAIN_TRACING_V2=true to enable.")
        return False
    
    if not api_key:
        print("⚠️  LangSmith API key not found. Tracing won't work.")
        return False
    
    if not LANGSMITH_AVAILABLE:
        print("⚠️  LangSmith package not installed. Run: pip install langsmith")
        return False
    
    # 设置项目名
    if project_name:
        os.environ["LANGCHAIN_PROJECT"] = project_name
        os.environ["LANGSMITH_PROJECT"] = project_name
    
    print(f"✅ LangSmith tracing enabled for project: {os.getenv('LANGCHAIN_PROJECT', 'default')}")
    return True


def trace_agent(name: str = "agent"):
    """
    Agent 追踪装饰器
    
    用于追踪自研 Agent 的调用
    
    Usage:
        @trace_agent("PlannerAgent")
        def run(self, input_data):
            ...
    """
    def decorator(func: Callable) -> Callable:
        if LANGSMITH_AVAILABLE and traceable:
            return traceable(name=name, run_type="chain")(func)
        else:
            # 如果 LangSmith 不可用，返回原函数
            return func
    return decorator


def trace_rag(name: str = "rag"):
    """
    RAG 追踪装饰器
    
    用于追踪 RAG 检索操作
    
    Usage:
        @trace_rag("retrieve")
        def retrieve(self, query):
            ...
    """
    def decorator(func: Callable) -> Callable:
        if LANGSMITH_AVAILABLE and traceable:
            return traceable(name=name, run_type="retriever")(func)
        else:
            return func
    return decorator


def trace_tool(name: str = "tool"):
    """
    工具追踪装饰器
    
    用于追踪工具调用
    """
    def decorator(func: Callable) -> Callable:
        if LANGSMITH_AVAILABLE and traceable:
            return traceable(name=name, run_type="tool")(func)
        else:
            return func
    return decorator


@contextmanager
def trace_span(name: str, run_type: str = "chain", metadata: Optional[dict] = None):
    """
    上下文管理器形式的追踪
    
    Usage:
        with trace_span("my_operation"):
            # do something
            ...
    """
    if LANGSMITH_AVAILABLE and RunTree:
        # 创建 RunTree
        run = RunTree(
            name=name,
            run_type=run_type,
            extra={"metadata": metadata} if metadata else {},
        )
        try:
            yield run
            run.end()
        except Exception as e:
            run.end(error=str(e))
            raise
    else:
        # 如果 LangSmith 不可用，只是执行代码
        yield None


def get_trace_url(run_id: str) -> str:
    """
    获取 Trace URL
    
    Args:
        run_id: Run ID
        
    Returns:
        LangSmith Trace URL
    """
    project = os.getenv("LANGCHAIN_PROJECT", "default")
    return f"https://smith.langchain.com/o/default/projects/{project}/runs/{run_id}"
