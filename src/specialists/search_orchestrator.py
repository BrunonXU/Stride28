"""
SearchOrchestrator - 搜索调度器

协调多平台并发搜索、缓存管理和结果聚合。
集成 BrowserAgent、QualityScorer、SearchCache。

核心流程：
1. 检查缓存 → 命中则直接返回
2. 启动浏览器 → 并发搜索各平台
3. 小红书特殊处理：全量搜索 + top_k 详情并行获取
4. QualityScorer 批量评分
5. 按 quality_score 降序排序 → 截断 top_k → 写入缓存
"""

import asyncio
import logging
import os
import re
from collections import defaultdict
from typing import Any, AsyncGenerator, Dict, List, Optional

from src.core.models import SearchResult
from src.specialists.browser_agent import BrowserAgent
from src.specialists.browser_models import RawSearchResult, ScoredResult
from src.specialists.engagement_ranker import EngagementRanker
from src.specialists.pipeline_executor import PipelineExecutor
from src.specialists.platform_configs import PLATFORM_CONFIGS, PlatformConfig
from src.specialists.quality_assessor import QualityAssessor
from src.specialists.quality_scorer import QualityScorer
from src.specialists.resource_collector import ResourceCollector
from src.specialists.search_cache import SearchCache
from src.specialists.bilibili_searcher import BiliBiliSearcher
from src.specialists.github_searcher import GithubSearcher
from src.specialists.zhihu_searcher import ZhihuSearcher
from src.specialists.slot_allocator import SlotAllocator
from src.specialists.xhs_searcher import XhsSearcher

logger = logging.getLogger(__name__)

# 广告关键词（标题降权用）
_AD_KEYWORDS = ["报班", "课程优惠", "限时", "折扣", "免费试听", "领取资料", "加群"]

# 中文字符检测
_CHINESE_RE = re.compile(r'[\u4e00-\u9fff]')

# 需要英文关键词的平台
_ENGLISH_PLATFORMS = {"youtube", "github", "google"}


def _xhs_composite_score(r: RawSearchResult) -> float:
    """小红书综合排序分：评论数×5 + 收藏数×2 + 点赞数×1"""
    m = r.engagement_metrics
    comments = _to_num(m.get("comments_count", 0))
    collected = _to_num(m.get("collected", 0))
    likes = _to_num(m.get("likes", 0))
    return comments * 5 + collected * 2 + likes


def _to_num(v) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


def _is_ad_title(title: str) -> bool:
    """标题是否包含广告关键词。"""
    return any(kw in title for kw in _AD_KEYWORDS)


class SearchOrchestrator:
    """协调多平台搜索任务。

    - 并发搜索所有指定平台
    - 集成缓存、质量评分
    - 小红书平台使用特殊排序权重和并行详情获取
    """

    SEARCH_TIMEOUT = 60.0   # 搜索阶段超时（秒）
    DETAIL_TIMEOUT = 120.0  # 详情阶段超时（秒）
    DEFAULT_TOP_K = 10

    def __init__(self, cache_ttl: int = 3600, llm_provider=None):
        self._cache = SearchCache(ttl=cache_ttl)
        self._browser_agent = BrowserAgent()
        self._quality_scorer = QualityScorer(llm_provider=llm_provider)
        self._bilibili_searcher = BiliBiliSearcher()
        self._xhs_searcher = XhsSearcher()
        self._zhihu_searcher = ZhihuSearcher()
        self._github_searcher = GithubSearcher(
            github_token=os.environ.get("GITHUB_TOKEN"),
        )
        # 搜索体验重设计：两阶段漏斗筛选 + 流水线执行
        self._engagement_ranker = EngagementRanker()
        self._quality_assessor = QualityAssessor(llm_provider=llm_provider)
        self._resource_collector = ResourceCollector()
        # 关键词翻译
        self._llm = llm_provider
        self._translation_cache: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search_all_platforms(
        self,
        query: str,
        platforms: List[str],
        timeout: float = 60.0,
        top_k: int = 10,
        per_platform_limit: Optional[int] = None,
    ) -> List[SearchResult]:
        """并发搜索所有指定平台，聚合、评分、排序后返回。
        
        Args:
            query: 搜索关键词
            platforms: 平台列表
            timeout: 超时时间（秒）
            top_k: 最终返回结果数量
            per_platform_limit: 每平台搜索条数，None 则使用默认值 10
        """
        # 1. 检查缓存
        cached = self._cache.get(query, platforms)
        if cached is not None:
            logger.info(f"缓存命中: {query} ({len(cached)} 条)")
            return cached[:top_k]

        # 2. 过滤有效平台
        valid_platforms = [p for p in platforms if p in PLATFORM_CONFIGS]
        if not valid_platforms:
            logger.warning(f"无有效平台: {platforms}")
            return []

        # 确定每平台搜索条数
        limit = per_platform_limit if per_platform_limit is not None else 10

        all_raw: List[RawSearchResult] = []

        try:
            # 分两批执行：需要登录的平台先串行跑（避免重登录关闭其他平台的浏览器），
            # 然后不需要登录的浏览器平台并发跑。API 平台可以和任何批次并发。
            login_platforms = [p for p in valid_platforms if PLATFORM_CONFIGS[p].requires_login]
            api_platforms = [p for p in valid_platforms if PLATFORM_CONFIGS[p].use_api_search]
            browser_platforms = [
                p for p in valid_platforms
                if not PLATFORM_CONFIGS[p].requires_login and not PLATFORM_CONFIGS[p].use_api_search
            ]

            # API 平台并发启动
            api_tasks = [
                self._search_single_platform(query, PLATFORM_CONFIGS[p], limit)
                for p in api_platforms
            ]

            # 需要登录的平台串行执行（可能触发浏览器重启）
            for p in login_platforms:
                try:
                    config = PLATFORM_CONFIGS[p]
                    result = await self._search_single_platform(query, config, limit)
                    if result:
                        all_raw.extend(result)
                        logger.info(f"{p}: {len(result)} 条结果")
                except Exception as e:
                    logger.warning(f"平台 {p} 搜索失败: {e}")

            # 收集 API 平台结果
            if api_tasks:
                api_results = await asyncio.gather(*api_tasks, return_exceptions=True)
                for i, result in enumerate(api_results):
                    platform_name = api_platforms[i]
                    if isinstance(result, Exception):
                        logger.warning(f"平台 {platform_name} 搜索失败: {result}")
                        continue
                    if result:
                        all_raw.extend(result)
                        logger.info(f"{platform_name}: {len(result)} 条结果")

            # 不需要登录的浏览器平台并发执行（浏览器状态已稳定）
            if browser_platforms:
                browser_tasks = [
                    self._search_single_platform(query, PLATFORM_CONFIGS[p], limit)
                    for p in browser_platforms
                ]
                browser_results = await asyncio.gather(*browser_tasks, return_exceptions=True)
                for i, result in enumerate(browser_results):
                    platform_name = browser_platforms[i]
                    if isinstance(result, Exception):
                        logger.warning(f"平台 {platform_name} 搜索失败: {result}")
                        continue
                    if result:
                        all_raw.extend(result)
                        logger.info(f"{platform_name}: {len(result)} 条结果")

        except Exception as e:
            logger.error(f"搜索执行异常: {e}")

        if not all_raw:
            await self.close()
            return []

        # 4. 质量评分
        try:
            scored = await self._quality_scorer.score_batch(all_raw)
        except Exception as e:
            logger.warning(f"质量评分失败: {e}")
            scored = [
                ScoredResult(raw=r, quality_score=0.0)
                for r in all_raw
            ]

        # 5. 广告降权
        for s in scored:
            if _is_ad_title(s.raw.title):
                s.quality_score *= 0.3

        # 6. 排序 + 截断
        scored.sort(key=lambda s: s.quality_score, reverse=True)
        top_scored = scored[:top_k]

        # 7. 转换为 SearchResult
        final = [self._to_search_result(s) for s in top_scored]

        # 8. 写入缓存
        self._cache.set(query, platforms, final)

        # 9. 关闭浏览器释放资源
        await self.close()

        return final

    async def search_all_platforms_stream(
        self,
        query: str,
        platforms: List[str],
        top_k: int = 10,
        per_platform_limit: Optional[int] = None,
        cancel_event: Optional[asyncio.Event] = None,
        learner_context: Optional[Any] = None,
    ) -> AsyncGenerator[dict, None]:
        """
        流式搜索：通过 yield 推送各阶段进度事件。

        Events:
        - {"stage": "searching", "message": "正在搜索小红书...", "platform": "xiaohongshu"}
        - {"stage": "filtering", "message": "已获取 N 条，正在初筛...", "total": N}
        - {"stage": "extracting", "message": "正在提取详情（3/15）...", "completed": 3, "total": 15}
        - {"stage": "evaluating", "message": "AI 正在评估内容质量..."}
        - {"stage": "done", "results": [...]}
        - {"stage": "error", "message": "..."}

        Flow:
        1. Check cache → hit: yield done directly
        2. Concurrent search all platforms → yield searching progress
        3. EngagementRanker filter → yield filtering
        4. PipelineExecutor extract+assess → yield extracting/evaluating
        5. Sort top_k → write cache → yield done

        Args:
            query: 搜索关键词
            platforms: 平台列表
            top_k: 最终返回结果数量
            per_platform_limit: 每平台搜索条数，None 则使用默认值 10
            cancel_event: 取消信号，设置后中断所有进行中的任务
        """
        PLATFORM_TIMEOUT = 360.0  # 单平台超时（秒），首次登录小红书可能需要 5 分钟

        _cancel = cancel_event or asyncio.Event()

        # ---- 1. 检查缓存 ----
        cached = self._cache.get(query, platforms)
        if cached is not None:
            logger.info(f"缓存命中: {query} ({len(cached)} 条)")
            yield {
                "stage": "done",
                "results": [r.to_dict() for r in cached[:top_k]],
            }
            return

        # ---- 2. 过滤有效平台 ----
        valid_platforms = [p for p in platforms if p in PLATFORM_CONFIGS]
        if not valid_platforms:
            logger.warning(f"无有效平台: {platforms}")
            yield {"stage": "error", "message": "无有效搜索平台"}
            return

        # ---- 2.5 SlotAllocator 配额分配 ----
        allocations = SlotAllocator.allocate(valid_platforms)

        # ---- 2.6 关键词翻译（中文关键词 → 英文平台用翻译结果）----
        translated_query = None
        if _CHINESE_RE.search(query):
            try:
                translated_query = await self._translate_keyword(query)
                if translated_query:
                    logger.info(f"英文平台将使用翻译关键词: '{query}' -> '{translated_query}'")
                else:
                    logger.warning(f"关键词翻译返回 None，英文平台将使用原始中文关键词: '{query}'")
            except Exception as e:
                logger.warning(f"关键词翻译失败，使用原始关键词: {e}")

        # ---- 3. 并发搜索各平台 ----
        all_raw: List[RawSearchResult] = []
        errors: List[str] = []

        for p in valid_platforms:
            if _cancel.is_set():
                await self.close()
                return
            yield {
                "stage": "searching",
                "message": f"正在搜索{PLATFORM_CONFIGS[p].name}...",
                "platform": p,
            }

        async def _search_with_timeout(platform_name: str) -> List[RawSearchResult]:
            config = PLATFORM_CONFIGS[platform_name]
            search_query = translated_query if (platform_name in _ENGLISH_PLATFORMS and translated_query) else query
            if search_query != query:
                logger.info(f"[{platform_name}] 使用翻译关键词: '{search_query}'")
            platform_limit = allocations[platform_name].search_count
            return await asyncio.wait_for(
                self._search_single_platform(search_query, config, platform_limit),
                timeout=PLATFORM_TIMEOUT,
            )

        # 分两批执行：需要登录的平台先串行跑（避免重登录关闭其他平台的浏览器），
        # 然后不需要登录的浏览器平台并发跑。API 平台（bilibili）可以和任何批次并发。
        login_platforms = [p for p in valid_platforms if PLATFORM_CONFIGS[p].requires_login]
        api_platforms = [p for p in valid_platforms if PLATFORM_CONFIGS[p].use_api_search and not PLATFORM_CONFIGS[p].requires_login]
        browser_platforms = [
            p for p in valid_platforms
            if not PLATFORM_CONFIGS[p].requires_login and not PLATFORM_CONFIGS[p].use_api_search
        ]

        # 第一批：API 平台（并发 task）+ 需要登录的平台（串行，可能触发浏览器重启）
        # 用 create_task 确保 API 平台在登录平台串行执行期间也在并发运行
        batch1_tasks = [asyncio.create_task(_search_with_timeout(p)) for p in api_platforms]
        for p in login_platforms:
            if _cancel.is_set():
                await self.close()
                return
            try:
                result = await _search_with_timeout(p)
                if result:
                    all_raw.extend(result)
                    logger.info(f"{p}: {len(result)} 条结果")
            except asyncio.TimeoutError:
                err_msg = f"平台 {p} 搜索超时（{PLATFORM_TIMEOUT}s）"
                logger.warning(err_msg)
                errors.append(err_msg)
            except Exception as e:
                err_msg = f"平台 {p} 搜索失败: {e}"
                logger.warning(err_msg)
                errors.append(err_msg)

        # API 平台结果收集（可能已经完成）
        if batch1_tasks:
            api_results = await asyncio.gather(*batch1_tasks, return_exceptions=True)
            for i, result in enumerate(api_results):
                platform_name = api_platforms[i]
                if isinstance(result, Exception):
                    err_msg = f"平台 {platform_name} 搜索失败: {result}"
                    logger.warning(err_msg)
                    errors.append(err_msg)
                    continue
                if result:
                    all_raw.extend(result)
                    logger.info(f"{platform_name}: {len(result)} 条结果")

        # 登录平台搜索完成后，关闭浏览器释放资源。
        # 这样浏览器平台会启动全新的 headless 浏览器，避免：
        # 1. 重登录后浏览器处于 headless=False 可见模式导致不稳定
        # 2. 旧浏览器上下文残留 Cookie/状态干扰其他平台
        if login_platforms and browser_platforms:
            logger.info("登录平台搜索完成，关闭浏览器以便浏览器平台使用干净实例")
            await self.close()

        # 第二批：不需要登录的浏览器平台并发跑（全新 headless 浏览器）
        if browser_platforms:
            browser_tasks = [_search_with_timeout(p) for p in browser_platforms]
            browser_results = await asyncio.gather(*browser_tasks, return_exceptions=True)
            for i, result in enumerate(browser_results):
                platform_name = browser_platforms[i]
                if isinstance(result, Exception):
                    err_msg = f"平台 {platform_name} 搜索失败: {result}"
                    logger.warning(err_msg)
                    errors.append(err_msg)
                    continue
                if result:
                    all_raw.extend(result)
                    logger.info(f"{platform_name}: {len(result)} 条结果")

        if not all_raw:
            await self.close()
            error_detail = "；".join(errors) if errors else "所有平台均无结果"
            yield {"stage": "error", "message": f"搜索失败: {error_detail}"}
            return

        if _cancel.is_set():
            await self.close()
            return

        # ---- 4. EngagementRanker 初筛 ----
        yield {
            "stage": "filtering",
            "message": f"已获取 {len(all_raw)} 条，正在初筛...",
            "total": len(all_raw),
        }

        # 按平台分组，每个平台内独立排序取各自配额内的 top 候选
        by_platform = defaultdict(list)
        for r in all_raw:
            by_platform[r.platform].append(r)

        candidates = []
        top_k_slots = SlotAllocator.allocate_top_k(allocations, top_k)
        for platform, results in by_platform.items():
            platform_top_k = top_k_slots.get(platform, 0)
            ranked = self._engagement_ranker.rank(results, top_n=platform_top_k)
            candidates.extend(ranked)

        total_candidates = len(candidates)

        if _cancel.is_set():
            await self.close()
            return

        # ---- 5. PipelineExecutor 提取 + 评估 ----
        pipeline = PipelineExecutor(
            browser_agent=self._browser_agent,
            resource_collector=self._resource_collector,
            quality_assessor=self._quality_assessor,
            cancel_event=_cancel,
            learner_context=learner_context,
        )

        # We need to yield extracting events during pipeline execution.
        # Use a shared list to collect progress events, then yield after pipeline.
        extract_events: List[dict] = []

        async def _progress_callback(completed: int, total: int) -> None:
            extract_events.append({
                "stage": "extracting",
                "message": f"正在提取详情（{completed}/{total}）...",
                "completed": completed,
                "total": total,
            })

        yield {
            "stage": "extracting",
            "message": f"正在提取详情（0/{total_candidates}）...",
            "completed": 0,
            "total": total_candidates,
        }

        scored_results: List[ScoredResult] = []
        try:
            scored_results = await pipeline.execute(
                candidates, progress_callback=_progress_callback
            )
        except Exception as e:
            logger.error(f"流水线执行异常: {e}")

        # Yield accumulated extracting progress events
        for evt in extract_events:
            if _cancel.is_set():
                await self.close()
                return
            yield evt

        # ---- 6. 关闭浏览器（提取完成后，LLM 评估前）----
        await self.close()

        if _cancel.is_set():
            return

        # ---- 7. 处理评估结果 ----
        if not scored_results:
            # LLM 整体失败降级：使用互动数据排序结果（需求 5.9）
            logger.warning("流水线无结果，使用互动数据排序降级")
            scored_results = [
                ScoredResult(raw=r, quality_score=0.0)
                for r in candidates
            ]

        yield {
            "stage": "evaluating",
            "message": "AI 正在评估内容质量...",
        }

        # ---- 8. 按平台比例选取 top_k ----
        actual_counts = {
            p: len([s for s in scored_results if s.raw.platform == p])
            for p in valid_platforms
        }
        final_slots = SlotAllocator.redistribute(allocations, actual_counts, top_k)

        top_scored = []
        for platform, slots in final_slots.items():
            platform_results = sorted(
                [s for s in scored_results if s.raw.platform == platform],
                key=lambda s: s.quality_score, reverse=True,
            )
            top_scored.extend(platform_results[:slots])

        # 最终按质量评分排序
        top_scored.sort(key=lambda s: s.quality_score, reverse=True)

        # ---- 9. 转换为 SearchResult ----
        final = [self._to_search_result_extended(s) for s in top_scored]

        # ---- 10. 写入缓存 ----
        self._cache.set(query, platforms, final)

        # ---- 11. yield done ----
        yield {
            "stage": "done",
            "results": [r.to_dict() for r in final],
        }

    @staticmethod
    def _to_search_result_extended(scored: ScoredResult) -> SearchResult:
        """将 ScoredResult（含摘要字段）转换为 SearchResult。"""
        raw = scored.raw
        comments_preview = []
        if raw.top_comments:
            comments_preview = [
                c.get("text", "")[:200] for c in raw.top_comments[:5]
            ]
        elif raw.comments:
            comments_preview = [c[:200] for c in raw.comments[:5]]

        return SearchResult(
            title=raw.title,
            url=raw.url,
            platform=raw.platform,
            type=raw.resource_type,
            description=(
                raw.description
                or (raw.content_snippet[:200] if raw.content_snippet else "")
            ),
            quality_score=scored.quality_score,
            engagement_metrics=raw.engagement_metrics,
            comments_preview=comments_preview,
            content_summary=scored.content_summary,
            image_urls=list(raw.image_urls) if raw.image_urls else [],
            content_text=raw.content_snippet or "",
        )

    async def _translate_keyword(self, query: str) -> Optional[str]:
        """使用 LLM 将中文关键词翻译为英文搜索词。

        结果缓存在 self._translation_cache 中，同一 query 仅翻译一次。
        翻译失败时记录 WARNING 并返回 None 作为降级。

        Args:
            query: 原始搜索关键词（包含中文）
        Returns:
            翻译后的英文搜索词，翻译失败时返回 None
        """
        # 缓存命中
        if query in self._translation_cache:
            return self._translation_cache[query]

        if self._llm is None:
            logger.warning("关键词翻译失败: LLM provider 未配置")
            return None

        try:
            # simple_chat 是同步方法，放到线程池执行避免阻塞事件循环
            loop = asyncio.get_event_loop()
            translated = await loop.run_in_executor(
                None,
                lambda: self._llm.simple_chat(
                    f"将以下中文搜索关键词翻译为简洁的英文搜索词，只输出翻译结果，不要解释：\n{query}",
                    system_prompt="你是一个搜索关键词翻译助手。将中文关键词翻译为适合英文搜索引擎的简洁英文搜索词。只输出翻译结果。",
                ),
            )
            translated = translated.strip()
            if translated:
                self._translation_cache[query] = translated
                logger.info(f"关键词翻译: '{query}' -> '{translated}'")
                return translated
            logger.warning(f"关键词翻译返回空结果: '{query}'")
            return None
        except Exception as e:
            logger.warning(f"关键词翻译失败，使用原始关键词: {e}")
            return None

    def expand_keywords(self, query: str) -> List[str]:
        """[TODO: 未来实现] 使用 LLM 扩展搜索关键词。MVP 返回原始关键词。"""
        return [query]

    async def close(self) -> None:
        """关闭浏览器资源。"""
        await self._browser_agent.close()
        await self._xhs_searcher.close()
        await self._zhihu_searcher.close()
        await self._github_searcher.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _search_single_platform(
        self, query: str, config: PlatformConfig, limit: int = 10
    ) -> List[RawSearchResult]:
        """搜索单个平台，小红书使用专用 XhsSearcher。
        
        Args:
            query: 搜索关键词
            config: 平台配置
            limit: 搜索结果数量限制
        """
        try:
            # API 搜索平台
            if config.use_api_search:
                if config.name == "bilibili":
                    return await self._bilibili_searcher.search(query, limit)
                elif config.name == "zhihu":
                    return await self._zhihu_searcher.search(query, limit)
                elif config.name == "github":
                    return await self._github_searcher.search(query, limit)
                else:
                    logger.warning(f"平台 {config.name} 配置了 use_api_search 但无对应搜索器")
                    return []

            # 小红书：使用 XhsSearcher（MediaCrawler 签名 + httpx）
            if config.name == "xiaohongshu":
                results = await self._xhs_searcher.search(query, limit)
                if results:
                    results.sort(key=_xhs_composite_score, reverse=True)
                    results = results[:limit]
                return results
            
            # 其他平台：浏览器搜索
            async with self._browser_agent._get_launch_lock():
                if self._browser_agent._browser is None:
                    await self._browser_agent.launch(config, allow_interactive_login=False)
                    if self._browser_agent._browser is None:
                        logger.error(f"浏览器启动失败，无法搜索 {config.name}")
                        return []

            results = await self._browser_agent.search_platform(query, config)
            return results

        except Exception as e:
            logger.error(f"搜索平台 {config.name} 失败: {e}")
            return []

    def _deduplicate_comments(self, comments: List[dict]) -> List[dict]:
        """使用前 30 字指纹去重评论。"""
        seen_fingerprints = set()
        unique = []
        for comment in comments:
            text = comment.get("text", "")
            fingerprint = text[:30] if text else ""
            if fingerprint and fingerprint not in seen_fingerprints:
                seen_fingerprints.add(fingerprint)
                unique.append(comment)
        return unique

    @staticmethod
    def _to_search_result(scored: ScoredResult) -> SearchResult:
        """将 ScoredResult 转换为 SearchResult。"""
        raw = scored.raw
        comments_preview = []
        if raw.top_comments:
            comments_preview = [
                c.get("text", "")[:200] for c in raw.top_comments[:5]
            ]
        elif raw.comments:
            comments_preview = [c[:200] for c in raw.comments[:5]]

        return SearchResult(
            title=raw.title,
            url=raw.url,
            platform=raw.platform,
            type=raw.resource_type,
            description=raw.description or raw.content_snippet[:200] if raw.content_snippet else raw.description,
            quality_score=scored.quality_score,
            engagement_metrics=raw.engagement_metrics,
            comments_preview=comments_preview,
        )
