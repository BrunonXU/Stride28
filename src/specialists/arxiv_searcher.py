"""
arXiv 学术论文搜索器

使用 arxiv Python 包（同步 API）搜索论文，通过 asyncio.run_in_executor 异步化。
返回 RawSearchResult 列表，字段映射遵循四层架构 Schema。

设计决策：
- arxiv 包是同步的，用线程池包装避免阻塞事件循环
- engagement_metrics 保持空 dict，不污染 UGC 互动数据语义
- 学术元数据（authors/categories/pdf_url 等）存入 source_metadata
- 失败时静默降级返回空列表，不影响其他平台搜索
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import List

from src.specialists.browser_models import RawSearchResult

logger = logging.getLogger(__name__)


class ArxivSearcher:
    """arXiv 学术论文搜索器"""

    TIMEOUT = 60  # 秒，arXiv API 对热门关键词响应极慢（重试机制 + 大结果集）
    DEFAULT_LIMIT = 10
    MAX_RESULTS_CAP = 15  # arXiv API 请求上限，避免大量结果导致超时

    def __init__(self, api_cache=None):
        self._api_cache = api_cache

    async def search(self, query: str, limit: int = 10) -> List[RawSearchResult]:
        """搜索 arXiv 论文，返回 RawSearchResult 列表。

        使用 arxiv.Client + arxiv.Search，在线程池中执行（arxiv 包是同步的）。
        失败时返回空列表（静默降级）。
        limit 会被 MAX_RESULTS_CAP 截断，避免请求过多结果导致 API 超时。
        """
        # arXiv API 请求量大时非常慢，限制上限
        effective_limit = min(limit, self.MAX_RESULTS_CAP)

        # APICache 查询
        if self._api_cache:
            cached = self._api_cache.get("arxiv_search", query=query, limit=effective_limit)
            if cached is not None:
                logger.debug(f"arXiv 缓存命中: query={query[:30]}")
                return cached

        try:
            import arxiv

            loop = asyncio.get_event_loop()
            results = await asyncio.wait_for(
                loop.run_in_executor(None, self._search_sync, query, effective_limit),
                timeout=self.TIMEOUT,
            )
            if results:
                logger.info(f"arXiv 搜索成功: {len(results)} 条结果")
                # 写入缓存
                if self._api_cache:
                    self._api_cache.set("arxiv_search", results, query=query, limit=effective_limit)
            return results
        except asyncio.TimeoutError:
            logger.warning(f"arXiv 搜索超时 ({self.TIMEOUT}s): {query}")
            return []
        except Exception as e:
            logger.warning(f"arXiv 搜索失败: {e}")
            return []

    def _search_sync(self, query: str, limit: int) -> List[RawSearchResult]:
        """同步搜索（在线程池中执行）。"""
        import arxiv

        search = arxiv.Search(
            query=query,
            max_results=limit,
            sort_by=arxiv.SortCriterion.Relevance,
        )
        client = arxiv.Client(
            page_size=limit,
            delay_seconds=0.5,  # 遵守 arXiv API rate limit
        )

        results = []
        for paper in client.results(search):
            parsed = self._parse_result(paper)
            if parsed:
                results.append(parsed)

        return results

    def _parse_result(self, result) -> RawSearchResult:
        """将 arxiv.Result 转换为 RawSearchResult。

        字段映射：
        - title → title
        - entry_id → url（arXiv 论文页）
        - summary → description + content_snippet
        - authors[0] → author（第一作者）
        - published → publish_time
        - categories/pdf_url/arxiv_id → source_metadata
        """
        now_utc = datetime.now(timezone.utc).isoformat()

        # 作者列表
        authors = [a.name for a in result.authors] if result.authors else []
        first_author = authors[0] if authors else ""

        # arXiv ID：从 entry_id 提取（如 http://arxiv.org/abs/2301.12345v1 → 2301.12345v1）
        arxiv_id = result.entry_id.split("/abs/")[-1] if "/abs/" in result.entry_id else result.entry_id

        return RawSearchResult(
            title=result.title.strip(),
            url=result.entry_id,
            platform="arxiv",
            resource_type="paper",
            description=result.summary.strip() if result.summary else "",
            content_snippet=result.summary.strip() if result.summary else "",
            engagement_metrics={},  # 不污染 UGC 互动数据语义
            source_tier="academic",
            author=first_author,
            publish_time=result.published.isoformat() if result.published else "",
            fetched_at=now_utc,
            extraction_mode="arxiv_api",
            source_metadata={
                "authors": authors,
                "categories": list(result.categories) if result.categories else [],
                "published": result.published.isoformat() if result.published else "",
                "updated": result.updated.isoformat() if result.updated else "",
                "pdf_url": result.pdf_url or "",
                "arxiv_id": arxiv_id,
            },
        )

    async def close(self):
        """接口一致性，无需清理资源。"""
        pass
