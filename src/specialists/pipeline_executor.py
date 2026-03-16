"""
PipelineExecutor - 流水线执行器

协调详情提取与 LLM 评估的流水线并行调度。
提取完一条立即送入评估队列，实现真正的流水线并行。

核心机制：
- asyncio.Queue 连接提取和评估两个阶段
- asyncio.Semaphore 控制并发 tab 数为 5
- 3 秒凑批超时平衡延迟和 LLM 调用效率
- cancel_event 支持随时中断所有 worker
"""

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from src.specialists.browser_models import RawSearchResult, ScoredResult
from src.specialists.platform_configs import PLATFORM_CONFIGS

logger = logging.getLogger(__name__)

# Sentinel object to signal that extraction is done
_SENTINEL = object()


class PipelineExecutor:
    """流水线执行器：详情提取 → LLM 评估的并行调度"""

    MAX_CONCURRENT_TABS = 5       # 最大并发浏览器 tab
    SINGLE_EXTRACT_TIMEOUT = 30   # 单条提取超时（秒）
    BATCH_WAIT_TIMEOUT = 3.0      # 批次凑批超时（秒）
    BATCH_MAX_SIZE = 5            # 批次上限（5 条平衡延迟和 LLM 调用效率）

    def __init__(
        self,
        browser_agent: Any,
        resource_collector: Any,
        quality_assessor: Any,
        cancel_event: Optional[asyncio.Event] = None,
        learner_context: Optional[Any] = None,
    ):
        self._browser_agent = browser_agent
        self._resource_collector = resource_collector
        self._quality_assessor = quality_assessor
        self._cancel = cancel_event or asyncio.Event()
        self._learner_context = learner_context

    async def execute(
        self,
        candidates: List[RawSearchResult],
        progress_callback: Optional[Callable[[int, int], Awaitable[None]]] = None,
    ) -> List[ScoredResult]:
        """
        执行流水线：并行提取详情 → 实时送入评估队列 → 批量 LLM 评估。

        Args:
            candidates: 初筛后的候选结果
            progress_callback: 进度回调 (completed, total)
        Returns:
            评估完成的 ScoredResult 列表
        """
        if not candidates:
            return []

        if self._cancel.is_set():
            return []

        total = len(candidates)
        completed_count = 0

        # 1. Create asyncio.Queue for extracted items
        queue: asyncio.Queue = asyncio.Queue()

        # 2. Semaphore to limit concurrent tabs
        semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_TABS)

        # Results list for the batch assessor
        results: List[ScoredResult] = []

        # Progress tracking wrapper
        async def extract_with_progress(raw: RawSearchResult) -> None:
            nonlocal completed_count
            await self._extract_worker(queue, raw, semaphore)
            completed_count += 1
            if progress_callback:
                try:
                    await progress_callback(completed_count, total)
                except Exception:
                    pass

        # 3. Start _batch_assessor consumer task
        assessor_task = asyncio.create_task(
            self._batch_assessor(queue, results)
        )

        # 4. Start extraction workers for all candidates concurrently
        extract_tasks = [
            asyncio.create_task(extract_with_progress(raw))
            for raw in candidates
        ]

        # 5. Wait for all extraction to complete
        await asyncio.gather(*extract_tasks, return_exceptions=True)

        # 6. Signal assessor that extraction is done (sentinel)
        await queue.put(_SENTINEL)

        # 7. Wait for assessor to finish
        await assessor_task

        return results

    async def _extract_worker(
        self,
        queue: asyncio.Queue,
        result: RawSearchResult,
        semaphore: asyncio.Semaphore,
    ) -> None:
        """
        单条提取 worker：
        1. 检查 cancel_event
        2. 获取信号量（控制并发 tab 数）
        3. 提取正文 + 评论 + 图片，超时 30 秒
        4. 提取完成后立即放入评估队列
        5. 超时或失败时放入降级 fallback 项
        """
        # Check cancel before acquiring semaphore
        if self._cancel.is_set():
            return

        async with semaphore:
            # Check cancel again after acquiring semaphore
            if self._cancel.is_set():
                return

            content = ""
            comments: List[Dict] = []
            image_urls: List[str] = []

            try:
                extracted = await asyncio.wait_for(
                    self._do_extract(result),
                    timeout=self.SINGLE_EXTRACT_TIMEOUT,
                )
                content = extracted.get("content", "")
                comments = extracted.get("comments", [])
                image_urls = extracted.get("image_urls", [])
            except asyncio.TimeoutError:
                logger.warning(
                    f"提取超时（{self.SINGLE_EXTRACT_TIMEOUT}s），跳过: {result.title[:40]}"
                )
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning(f"提取失败: {result.title[:40]} - {e}")

            # Check cancel before putting into queue
            if self._cancel.is_set():
                return

            # Update result with extracted data
            if content:
                result.content_snippet = content
            if image_urls:
                result.image_urls = image_urls
            if comments:
                result.top_comments = comments

            # Put into assessment queue: (raw, content, comments)
            await queue.put((result, content, comments))

    async def _do_extract(self, result: RawSearchResult) -> Dict[str, Any]:
        """
        执行实际的内容提取。

        使用 BrowserAgent 打开新 tab，通过 ResourceCollector 提取正文、评论和图片。
        对于已有完整数据的结果（如小红书 API 返回），直接使用已有数据，跳过浏览器提取。
        """
        content = ""
        comments: List[Dict] = []
        image_urls: List[str] = list(result.image_urls or [])

        # 如果结果已经有完整内容（XhsSearcher 等 API 搜索器已提取），直接使用
        has_rich_data = (
            result.content_snippet
            and len(result.content_snippet) > 50
            and (result.top_comments or result.engagement_metrics)
        )
        if has_rich_data:
            return {
                "content": result.content_snippet or "",
                "comments": result.top_comments or [],
                "image_urls": image_urls,
            }

        # Get platform config for this result
        config = PLATFORM_CONFIGS.get(result.platform)

        # Try using BrowserAgent's fetch_detail if browser context is available
        if self._browser_agent._context and config:
            try:
                detail = await self._browser_agent.fetch_detail(result.url, config)
                if detail:
                    content = detail.content_snippet or ""
                    if detail.top_comments:
                        comments = detail.top_comments
                    if detail.image_urls:
                        image_urls = detail.image_urls
                    return {
                        "content": content,
                        "comments": comments,
                        "image_urls": image_urls,
                    }
            except Exception as e:
                logger.debug(f"BrowserAgent fetch_detail failed: {e}")

        # Fallback: use existing content_snippet and comments from the raw result
        content = result.content_snippet or result.description or ""
        comments = result.top_comments or []

        return {
            "content": content,
            "comments": comments,
            "image_urls": image_urls,
        }

    async def _batch_assessor(
        self,
        queue: asyncio.Queue,
        results: List[ScoredResult],
    ) -> None:
        """
        批量评估消费者：
        1. 从队列中取出已提取的结果
        2. 凑批（上限 15 条，超时 3 秒无新数据则立即发起 LLM 调用）
        3. 调用 QualityAssessor.assess_batch()
        4. 收到 sentinel 后处理剩余批次并退出
        """
        batch: List[Tuple[RawSearchResult, str, List[Dict]]] = []
        done = False

        while not done:
            if self._cancel.is_set():
                return

            # Phase 1: Wait for at least one item (block indefinitely)
            if not batch:
                item = await queue.get()
                if item is _SENTINEL:
                    return  # Nothing left to process
                raw, content, comments = item
                batch.append((raw, content, comments))

            # Phase 2: Try to fill batch up to BATCH_MAX_SIZE with BATCH_WAIT_TIMEOUT
            while len(batch) < self.BATCH_MAX_SIZE:
                if self._cancel.is_set():
                    return
                try:
                    item = await asyncio.wait_for(
                        queue.get(), timeout=self.BATCH_WAIT_TIMEOUT
                    )
                    if item is _SENTINEL:
                        done = True
                        break
                    raw, content, comments = item
                    batch.append((raw, content, comments))
                except asyncio.TimeoutError:
                    # 3 seconds with no new items — flush current batch
                    break

            # Phase 3: Flush the batch
            if batch:
                if self._cancel.is_set():
                    return
                await self._flush_batch(batch, results)
                batch = []


    async def _flush_batch(
        self,
        batch: List[Tuple[RawSearchResult, str, List[Dict]]],
        results: List[ScoredResult],
    ) -> None:
        """Flush a batch through the quality assessor."""
        if not batch:
            return

        try:
            scored = await self._quality_assessor.assess_batch(batch, self._learner_context)
            results.extend(scored)
        except Exception as e:
            logger.warning(f"批量评估失败，使用降级评估: {e}")
            # Fallback: assess each item individually
            for raw, content, comments in batch:
                try:
                    fallback = await self._quality_assessor.assess_single_fallback(raw)
                    results.append(fallback)
                except Exception as inner_e:
                    logger.warning(f"降级评估也失败: {inner_e}")
                    # Last resort: create a minimal scored result
                    results.append(ScoredResult(
                        raw=raw,
                        quality_score=1.0,
                        content_summary="",
                        extracted_content=content,
                    ))
