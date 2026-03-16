"""
开发者调试端点

GET  /api/dev/status  — LangSmith 连接状态 + 系统信息
GET  /api/dev/traces  — 最近的 Agent 调用记录
POST /api/dev/langsmith — 切换 LangSmith 追踪开关
"""

import logging
import os
import time
from typing import List

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dev"])

# 内存中记录最近的 trace（轻量级，不依赖 LangSmith）
_traces: List[dict] = []
MAX_TRACES = 50


def record_trace(trace: dict) -> None:
    """记录一条 trace（供其他模块调用）"""
    _traces.append(trace)
    if len(_traces) > MAX_TRACES:
        _traces.pop(0)


class DevStatus(BaseModel):
    langsmith: dict
    system: dict


class TraceEntry(BaseModel):
    id: str
    type: str          # "llm" | "chain" | "tool" | "retriever"
    name: str
    startTime: str
    duration: float    # ms
    status: str        # "ok" | "error"
    input: str         # 截断
    output: str        # 截断
    tokens: dict       # {"prompt": N, "completion": N, "total": N}
    metadata: dict


@router.get("/dev/status", response_model=DevStatus)
async def dev_status():
    """返回 LangSmith 连接状态和系统信息"""
    tracing_on = os.getenv("LANGCHAIN_TRACING_V2", "").lower() == "true"
    api_key = os.getenv("LANGCHAIN_API_KEY", "")
    has_key = bool(api_key and api_key != "lsv2_xxx")
    project = os.getenv("LANGCHAIN_PROJECT", "stride28")

    # 检查 langsmith 包是否可用
    try:
        import langsmith  # noqa: F401
        pkg_installed = True
    except ImportError:
        pkg_installed = False

    connected = tracing_on and has_key and pkg_installed

    return DevStatus(
        langsmith={
            "enabled": tracing_on,
            "connected": connected,
            "hasApiKey": has_key,
            "packageInstalled": pkg_installed,
            "project": project,
        },
        system={
            "provider": os.getenv("DEFAULT_PROVIDER", "tongyi"),
            "model": os.getenv("DEFAULT_MODEL", "qwen-turbo"),
            "tracesCount": len(_traces),
        },
    )


@router.get("/dev/traces")
async def dev_traces(limit: int = 20):
    """返回最近的 Agent 调用记录"""
    return _traces[-limit:][::-1]  # 最新的在前


@router.post("/dev/langsmith")
async def toggle_langsmith(body: dict):
    """切换 LangSmith 追踪开关"""
    enabled = body.get("enabled", False)
    os.environ["LANGCHAIN_TRACING_V2"] = "true" if enabled else "false"
    logger.info(f"LangSmith tracing {'enabled' if enabled else 'disabled'}")
    return {"ok": True, "enabled": enabled}


@router.get("/dev/graph")
async def dev_graph():
    """返回 ChatOrchestrator 的 Mermaid 图定义"""
    try:
        from backend.chat_orchestrator import ChatOrchestrator
        graph = ChatOrchestrator.build_for_visualization()
        mermaid_str = graph.get_graph().draw_mermaid()
        return {"mermaid": mermaid_str}
    except Exception as e:
        logger.error(f"图可视化失败: {e}")
        return {"mermaid": None, "error": str(e)}
