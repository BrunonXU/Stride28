"""MCP 搜索服务数据模型

定义 Envelope 响应格式、错误码、搜索结果数据结构。
"""
from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ============================================================
# 错误码
# ============================================================

class ErrorCode(str, Enum):
    LOGIN_REQUIRED = "login_required"
    LOGIN_TIMEOUT = "login_timeout"
    SEARCH_TIMEOUT = "search_timeout"
    BROWSER_CRASHED = "browser_crashed"
    UNKNOWN_ERROR = "unknown_error"


# ============================================================
# Envelope 响应格式
# ============================================================

class EnvelopeBuilder:
    """统一的 JSON Envelope 构建器"""

    @staticmethod
    def success(platform: str, tool: str, data: Any) -> str:
        import json
        return json.dumps({
            "ok": True,
            "platform": platform,
            "tool": tool,
            "request_id": str(uuid.uuid4()),
            "data": data,
            "error": None,
        }, ensure_ascii=False)

    @staticmethod
    def error(platform: str, tool: str, code: ErrorCode, message: str) -> str:
        import json
        return json.dumps({
            "ok": False,
            "platform": platform,
            "tool": tool,
            "request_id": str(uuid.uuid4()),
            "data": None,
            "error": {"code": code.value, "message": message},
        }, ensure_ascii=False)


# ============================================================
# 搜索结果数据模型
# ============================================================

class SearchResultItem(BaseModel):
    """单条搜索结果"""
    id: str = ""
    title: str = ""
    url: str = ""
    snippet: str = ""
    cover_url: str = ""
    author: str = ""
    likes: int = 0
    xsec_token: str = ""
    note_type: str = ""  # "normal" | "video"


class SearchData(BaseModel):
    """搜索结果集合"""
    results: List[SearchResultItem] = Field(default_factory=list)
    total_requested: int = 0
    total_returned: int = 0


class LoginData(BaseModel):
    """登录结果"""
    message: str = ""
