"""
多源资源搜索专家模块

职责：
1. 统一资源搜索器（ResourceSearcher）
2. 统一返回 SearchResult 列表
3. 使用 SearchOrchestrator 协调多平台并发搜索
4. 弹性搜索量策略：根据用户选择的平台数量调整每平台搜索条数
"""

import logging
from typing import List, Optional

from src.core.models import SearchResult

logger = logging.getLogger(__name__)


class ResourceSearcher:
    """统一资源搜索器。

    提供 search(query, platforms, user_selected) 同步接口。
    内部使用 asyncio.run() 包装异步调用，保持同步接口。
    
    弹性搜索量策略：
    - 未选平台（默认全搜）：每平台 10 条
    - 选了 1 个平台：该平台 60 条
    - 选了多个平台：40 条均分
    """

    PLATFORMS = ["xiaohongshu", "google", "youtube", "bilibili", "github"]
    TIMEOUT = 60
    DEFAULT_TOP_K = 10

    def __init__(self, llm_provider=None):
        from src.specialists.search_orchestrator import SearchOrchestrator

        self._orchestrator = SearchOrchestrator(llm_provider=llm_provider)

    def search(
        self,
        query: str,
        platforms: Optional[List[str]] = None,
        user_selected: bool = False,
    ) -> List[SearchResult]:
        """搜索学习资源。

        Args:
            query: 搜索关键词
            platforms: 指定平台列表，None 表示全部
            user_selected: 用户是否主动选择了平台（影响搜索深度）

        Returns:
            按 quality_score 降序排列的 SearchResult 列表（最多 10 条）
        """
        if not query or not query.strip():
            return []

        target_platforms = platforms if platforms else self.PLATFORMS
        per_platform_limit = self._calculate_limit(target_platforms, user_selected)

        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果已在异步上下文中，创建新线程运行
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(
                        asyncio.run,
                        self._orchestrator.search_all_platforms(
                            query,
                            target_platforms,
                            per_platform_limit=per_platform_limit,
                            top_k=self.DEFAULT_TOP_K,
                        ),
                    )
                    return future.result(timeout=self.TIMEOUT + 30)
            else:
                return loop.run_until_complete(
                    self._orchestrator.search_all_platforms(
                        query,
                        target_platforms,
                        per_platform_limit=per_platform_limit,
                        top_k=self.DEFAULT_TOP_K,
                    )
                )
        except RuntimeError:
            # 没有事件循环，直接 asyncio.run
            return asyncio.run(
                self._orchestrator.search_all_platforms(
                    query,
                    target_platforms,
                    per_platform_limit=per_platform_limit,
                    top_k=self.DEFAULT_TOP_K,
                )
            )
        except Exception as e:
            logger.error(f"[ResourceSearcher] search failed: {e}")
            return []

    def _calculate_limit(self, platforms: List[str], user_selected: bool) -> int:
        """计算每平台搜索条数。
        
        弹性搜索量策略：
        - 未选平台（默认全搜）：每平台 10 条
        - 选了 1 个平台：该平台 60 条
        - 选了多个平台：40 条均分（最少 10 条）
        """
        if not user_selected:
            return 10
        if len(platforms) == 1:
            return 60
        return max(10, 40 // len(platforms))
