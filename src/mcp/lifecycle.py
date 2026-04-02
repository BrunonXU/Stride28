"""MCP 平台生命周期管理器

管理各平台搜索器的创建、销毁、锁、失败计数。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, Optional

from src.mcp.adapter import XhsBrowserSearcher
from src.mcp.zhihu_adapter import ZhihuBrowserSearcher

logger = logging.getLogger(__name__)

_MAX_FAILURES = 3


class LifecycleManager:
    """平台适配器生命周期管理"""

    def __init__(self):
        self._searchers: Dict[str, object] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._failures: Dict[str, int] = {}

    def get_lock(self, platform: str) -> asyncio.Lock:
        if platform not in self._locks:
            self._locks[platform] = asyncio.Lock()
        return self._locks[platform]

    async def get_searcher(self, platform: str):
        if platform not in self._searchers:
            if platform == "xiaohongshu":
                self._searchers[platform] = XhsBrowserSearcher()
            elif platform == "zhihu":
                self._searchers[platform] = ZhihuBrowserSearcher()
            else:
                raise ValueError(f"未知平台: {platform}")
            logger.info("平台 %s 搜索器已创建", platform)
        return self._searchers[platform]

    async def destroy_searcher(self, platform: str):
        searcher = self._searchers.pop(platform, None)
        if searcher:
            await searcher.close()
            logger.info("平台 %s 搜索器已销毁", platform)

    def record_failure(self, platform: str):
        self._failures[platform] = self._failures.get(platform, 0) + 1

    def reset_failures(self, platform: str):
        self._failures[platform] = 0

    def is_crashed(self, platform: str) -> bool:
        return self._failures.get(platform, 0) >= _MAX_FAILURES

    async def cleanup(self):
        """关闭所有搜索器"""
        for platform in list(self._searchers.keys()):
            await self.destroy_searcher(platform)
