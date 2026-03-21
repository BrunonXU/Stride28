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
from src.specialists.arxiv_searcher import ArxivSearcher
from src.specialists.tavily_searcher import TavilySearcher

logger = logging.getLogger(__name__)

# 广告关键词（标题降权用）
_AD_KEYWORDS = ["报班", "课程优惠", "限时", "折扣", "免费试听", "领取资料", "加群"]

# 中文字符检测
_CHINESE_RE = re.compile(r'[\u4e00-\u9fff]')

# _ENGLISH_PLATFORMS 已移除，改用 PLATFORM_SOURCE_MAP 按 source_type 选取 query

# 绕过漏斗的 API 平台（不走 EngagementRanker + PipelineExecutor）
_BYPASS_FUNNEL_PLATFORMS = {"arxiv", "tavily"}

# ------------------------------------------------------------------
# Context-Aware Query Rewrite 常量
# ------------------------------------------------------------------

# 平台 → Source Type 映射
PLATFORM_SOURCE_MAP: Dict[str, str] = {
    "xiaohongshu": "community",
    "zhihu": "community",
    "bilibili": "community",
    "tavily": "broad_web",
    "arxiv": "academic",
    "github": "developer",
}

# 强实体术语集合（包含这些术语的查询强制 light 模式）
SPECIFIC_TERMS: frozenset = frozenset({
    "langgraph", "mcp", "spring ai", "chromadb", "fastapi",
    "langchain", "autogen", "crewai", "llamaindex", "dspy",
    "openai", "anthropic", "huggingface", "pytorch", "tensorflow",
    "kubernetes", "docker", "redis", "postgresql", "mongodb",
})


def _determine_rewrite_mode(
    query: str,
    learner_context: Optional[Any],
    plan_id: Optional[str] = None,
) -> str:
    """判定 query rewrite 模式：contextual 或 light。

    仅依赖显式输入参数的纯函数，无副作用。
    contextual 的前提：learner_context 存在且 goal 非空且 plan_id 存在。

    判定优先级：
    1. 无 learner_context / goal 为空 / 无 plan_id → light
    2. 包含 SPECIFIC_TERMS 中的强实体术语 → light
    3. 短查询（去空格 ≤15 字符 且 分段 ≤3）→ contextual
    4. 其他 → light

    词边界匹配策略：
    - 单词术语（如 redis）：先按空格/标点分词为 token 列表，检查术语是否在 token 中
    - 多词术语（如 spring ai）：在 normalized query 中做子串匹配
    """
    # 1. 无上下文 → light
    if not learner_context or not getattr(learner_context, "goal", ""):
        return "light"
    if not plan_id:
        return "light"

    # 2. 强实体匹配（词边界感知）
    normalized = query.lower()
    # 按空格和常见标点分词，避免 substring 误判
    tokens = re.split(r'[\s,;/\\()\[\]{}]+', normalized)
    tokens = [t for t in tokens if t]
    for term in SPECIFIC_TERMS:
        if " " in term:
            # 多词术语：检查是否作为连续子串出现
            if term in normalized:
                return "light"
        else:
            # 单词术语：检查是否在 token 列表中
            if term in tokens:
                return "light"

    # 3. 长度判断
    stripped = query.replace(" ", "")
    segments = query.split()
    if len(stripped) <= 15 and len(segments) <= 3:
        return "contextual"

    return "light"


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
        self._arxiv_searcher = ArxivSearcher()
        self._tavily_searcher = TavilySearcher()
        # 搜索体验重设计：两阶段漏斗筛选 + 流水线执行
        self._engagement_ranker = EngagementRanker()
        self._quality_assessor = QualityAssessor(llm_provider=llm_provider)
        self._resource_collector = ResourceCollector()
        # 关键词翻译 → 上下文感知 query rewrite
        self._llm = llm_provider
        self._rewrite_cache: Dict[str, Dict] = {}  # key=SHA-256(query|platforms|plan_id)

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
        plan_id: Optional[str] = None,
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
        context_key = plan_id or ""
        cached = self._cache.get(query, platforms, context_key=context_key)
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

        # ---- 2.6 Context-Aware Query Rewrite ----
        rewrite_result = None
        try:
            rewrite_result = await self._rewrite_query(
                query=query,
                learner_context=learner_context,
                valid_platforms=valid_platforms,
                plan_id=plan_id,
            )
            if rewrite_result:
                queries_log = " | ".join(
                    f"{k}='{v}'" for k, v in rewrite_result.get("queries", {}).items()
                )
                logger.info(
                    "Query rewrite 完成 [%s]: '%s' | %s",
                    rewrite_result.get("rewrite_mode", "unknown"),
                    query,
                    queries_log,
                )
            else:
                logger.info("Query rewrite 返回 None，所有平台将使用原始关键词: '%s'", query)
        except Exception as e:
            logger.warning("Query rewrite 失败，使用原始关键词: %s", e)

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
            # 按 source_type 从 rewrite_result 选取 query
            search_query = query  # 默认用原始 query
            if rewrite_result and rewrite_result.get("queries"):
                source_type = PLATFORM_SOURCE_MAP.get(platform_name)
                sq = rewrite_result["queries"].get(source_type, "")
                if sq and sq.strip():
                    search_query = sq
            if search_query != query:
                logger.info(f"[{platform_name}] 使用 rewrite 关键词: '{search_query}'")
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
            if errors:
                # 有错误信息：搜索失败
                error_detail = "；".join(errors)
                yield {"stage": "error", "message": f"搜索失败: {error_detail}"}
            else:
                # 搜索成功但无结果：返回空 done
                yield {"stage": "done", "results": []}
            return

        if _cancel.is_set():
            await self.close()
            return

        # ---- 3.5 分离绕过漏斗的平台和 UGC 结果 ----
        # arXiv / Tavily 绕过 EngagementRanker + PipelineExecutor
        arxiv_raw = [r for r in all_raw if r.platform == "arxiv"]
        tavily_raw = [r for r in all_raw if r.platform == "tavily"]
        ugc_raw = [r for r in all_raw if r.platform not in _BYPASS_FUNNEL_PLATFORMS]

        # ---- 4. EngagementRanker 初筛（仅 UGC）----
        yield {
            "stage": "filtering",
            "message": f"已获取 {len(all_raw)} 条，正在初筛...",
            "total": len(all_raw),
        }

        # 按平台分组，每个平台内独立排序取各自配额内的 top 候选
        by_platform = defaultdict(list)
        for r in ugc_raw:
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

        # ---- 5. PipelineExecutor 提取 + 评估（仅 UGC）----
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
        if not scored_results and candidates:
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

        # ---- 7.5 绕过漏斗平台的 LLM 评估 ----

        # arXiv：专用 prompt（中文翻译 + 个性化推荐 + 评分）
        arxiv_to_assess = arxiv_raw[:top_k]
        arxiv_scored: List[ScoredResult] = []
        if arxiv_to_assess:
            arxiv_scored = await self._quality_assessor.assess_arxiv_batch(
                arxiv_to_assess, learner_context=learner_context
            )
            evaluated_count = sum(1 for s in arxiv_scored if s.quality_score > 0)
            logger.info(
                f"arXiv 评估完成: {len(arxiv_scored)} 条结果"
                f"（{evaluated_count} 条已评估，截断至 top_k={top_k}）"
            )

        # Tavily：用通用 assess_batch（正文已由 /extract 提取，无评论）
        tavily_to_assess = tavily_raw[:top_k]
        tavily_scored: List[ScoredResult] = []
        if tavily_to_assess:
            tavily_items = [
                (r, r.content_snippet or r.description or "", [])
                for r in tavily_to_assess
            ]
            tavily_scored = await self._quality_assessor.assess_batch(
                tavily_items, learner_context=learner_context
            )
            evaluated_count = sum(1 for s in tavily_scored if s.quality_score > 0)
            logger.info(
                f"Tavily 评估完成: {len(tavily_scored)} 条结果"
                f"（{evaluated_count} 条已评估，截断至 top_k={top_k}）"
            )

        # ---- 8. 混排：已评估在前（按分降序）+ 未评估在后（保持 relevance 顺序）----
        # 对 UGC 结果按平台比例选取 top_k
        ugc_platforms = [p for p in valid_platforms if p not in _BYPASS_FUNNEL_PLATFORMS]
        if ugc_platforms and scored_results:
            actual_counts = {
                p: len([s for s in scored_results if s.raw.platform == p])
                for p in ugc_platforms
            }
            final_slots = SlotAllocator.redistribute(allocations, actual_counts, top_k)

            ugc_top = []
            for platform, slots in final_slots.items():
                platform_results = sorted(
                    [s for s in scored_results if s.raw.platform == platform],
                    key=lambda s: s.quality_score, reverse=True,
                )
                ugc_top.extend(platform_results[:slots])
        else:
            ugc_top = []

        # 混排规则：
        # 1. 已评估结果（UGC + arXiv + Tavily，quality_score > 0）按分降序
        # 2. 未评估结果（quality_score == 0）保持原始顺序，排在末尾
        all_results = ugc_top + arxiv_scored + tavily_scored
        evaluated = sorted(
            [s for s in all_results if s.quality_score > 0],
            key=lambda s: s.quality_score, reverse=True,
        )
        unevaluated = [s for s in all_results if s.quality_score == 0]
        top_scored = evaluated + unevaluated

        # ---- 9. 转换为 SearchResult ----
        final = [self._to_search_result_extended(s) for s in top_scored]

        # ---- 10. 写入缓存 ----
        self._cache.set(query, platforms, final, context_key=context_key)

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
            # 四层架构新增字段
            source_tier=raw.source_tier,
            author=raw.author,
            publish_time=raw.publish_time,
            fetched_at=raw.fetched_at,
            extraction_mode=raw.extraction_mode,
            source_metadata=dict(raw.source_metadata) if raw.source_metadata else {},
        )

    async def _rewrite_query(
        self,
        query: str,
        learner_context: Optional[Any] = None,
        valid_platforms: Optional[List[str]] = None,
        plan_id: Optional[str] = None,
    ) -> Optional[Dict]:
        """上下文感知 query rewrite：意图消歧 + 按 source_type 生成专用查询。

        两步逻辑（intent normalization → source-specific rendering），
        单次 LLM 调用实现。contextual 模式注入学习上下文消歧，light 模式仅纠错+翻译。

        返回 QueryRewriteResult 字典：
        {
            "rewrite_mode": "contextual" | "light",
            "canonical_intent": "..." | None,
            "queries": {"community": "...", "broad_web": "...", ...},
            "reason": "..." | None,
        }
        失败返回 None，调用方降级为原始 query。
        """
        # 计算 target_sources
        target_sources = set()
        for p in (valid_platforms or []):
            st = PLATFORM_SOURCE_MAP.get(p)
            if st:
                target_sources.add(st)
        if not target_sources:
            return None

        # 检查 rewrite 缓存
        cache_key = self._make_rewrite_cache_key(query, valid_platforms or [], plan_id)
        if cache_key in self._rewrite_cache:
            return self._rewrite_cache[cache_key]

        if self._llm is None:
            logger.warning("Query rewrite 失败: LLM provider 未配置")
            return None

        # 判定模式
        mode = _determine_rewrite_mode(query, learner_context, plan_id)
        sources_str = ", ".join(sorted(target_sources))

        # 尝试 rewrite（contextual 失败 → 降级 light → 失败 → None）
        result = None
        if mode == "contextual":
            result = await self._call_rewrite_llm(
                query, "contextual", target_sources, sources_str, learner_context
            )
            if result is None:
                logger.warning(
                    "Query rewrite 降级 [contextual→light]: '%s', 原因: contextual LLM 调用或解析失败",
                    query,
                )
                mode = "light"

        if result is None:
            result = await self._call_rewrite_llm(
                query, "light", target_sources, sources_str, learner_context
            )
            if result is None:
                logger.warning(
                    "Query rewrite 降级 [light→原始查询]: '%s', 原因: light LLM 调用或解析失败",
                    query,
                )
                return None

        # 写入缓存
        self._rewrite_cache[cache_key] = result

        # 日志
        queries_log = " | ".join(
            f"{k}='{v}'" for k, v in result.get("queries", {}).items()
        )
        logger.info(
            "Query rewrite [%s]: '%s' -> intent='%s' | %s",
            result.get("rewrite_mode", "unknown"),
            query,
            result.get("canonical_intent") or "N/A",
            queries_log,
        )
        return result

    async def _call_rewrite_llm(
        self,
        query: str,
        mode: str,
        target_sources: set,
        sources_str: str,
        learner_context: Optional[Any] = None,
    ) -> Optional[Dict]:
        """构建 prompt 并调用 LLM，返回解析后的 QueryRewriteResult 或 None。"""
        try:
            if mode == "contextual":
                prompt = self._build_contextual_prompt(
                    query, sources_str, learner_context
                )
                system = (
                    "你是搜索关键词优化助手。根据学习者的上下文对搜索词做意图消歧，"
                    "然后按搜索源类型生成针对性查询。\n\n"
                    "核心原则：搜索的目的始终是找学习资料（教程、文档、课程、技术文章），"
                    "learning_goal 只用来确定技术领域和难度方向，不要把 goal 本身的描述"
                    "（如求职、面试等）作为搜索意图。\n\n"
                    "规则：\n"
                    "1. canonical_intent 用中文，一句话总结消歧后的用户意图（必须是学习/技术相关）\n"
                    "2. community 查询用中文口语化表达（适合小红书/知乎/B站）\n"
                    "3. broad_web / academic / developer 查询用英文专业术语\n"
                    "4. 每个查询 ≤ 8 个词，保持搜索词简洁\n"
                    "5. 不要过度扩写，保持与原始查询的语义距离\n"
                    "6. level 只影响查询的难度倾向，不改变主题"
                )
            else:
                prompt = self._build_light_prompt(query, sources_str)
                system = (
                    "你是搜索关键词优化助手。对搜索词做拼写纠错、术语规范化，"
                    "并按搜索源类型生成中英文查询。\n"
                    "不要改变查询的主题和意图，只做格式优化。\n\n"
                    "规则：\n"
                    "1. community 查询用中文\n"
                    "2. broad_web / academic / developer 查询用英文\n"
                    "3. 保持原始查询的语义，不要扩写或消歧\n"
                    "4. 每个查询 ≤ 8 个词"
                )

            loop = asyncio.get_event_loop()
            raw_response = await loop.run_in_executor(
                None,
                lambda: self._llm.simple_chat(prompt, system_prompt=system),
            )
            return self._parse_rewrite_response(raw_response, target_sources, mode)
        except Exception as e:
            logger.warning("Query rewrite LLM 调用失败 [%s]: %s", mode, e)
            return None

    def _build_contextual_prompt(
        self, query: str, sources_str: str, learner_context: Optional[Any]
    ) -> str:
        """构建 contextual 模式的 user prompt。"""
        # 提取 plan_summary 前 3 行
        plan_summary = ""
        if learner_context and getattr(learner_context, "plan_summary", ""):
            lines = learner_context.plan_summary.strip().split("\n")
            plan_summary = "\n".join(lines[:3])

        goal = getattr(learner_context, "goal", "") if learner_context else ""
        level = getattr(learner_context, "level", "") if learner_context else ""

        parts = [
            f"rewrite_mode: contextual",
            f"query: {query}",
            f"learning_goal: {goal}",
        ]
        if plan_summary:
            parts.append(f"current_progress: {plan_summary}")
        if level:
            parts.append(f"level: {level}")
        parts.append(f"target_sources: [{sources_str}]")
        parts.append("")
        parts.append(self._json_output_hint(sources_str, contextual=True))

        return "\n".join(parts)

    def _build_light_prompt(self, query: str, sources_str: str) -> str:
        """构建 light 模式的 user prompt。"""
        parts = [
            f"rewrite_mode: light",
            f"query: {query}",
            f"target_sources: [{sources_str}]",
            "",
            self._json_output_hint(sources_str, contextual=False),
        ]
        return "\n".join(parts)

    @staticmethod
    def _json_output_hint(sources_str: str, contextual: bool) -> str:
        """生成 JSON 输出格式提示。"""
        # 动态生成 queries 示例
        sources = [s.strip() for s in sources_str.split(",")]
        queries_example = ", ".join(f'"{s}": "..."' for s in sources)
        intent = '"..."' if contextual else "null"
        reason = '"..."' if contextual else "null"
        mode = "contextual" if contextual else "light"
        return (
            f'输出 JSON（不要 markdown 包裹）：\n'
            f'{{\n'
            f'  "rewrite_mode": "{mode}",\n'
            f'  "canonical_intent": {intent},\n'
            f'  "queries": {{{queries_example}}},\n'
            f'  "reason": {reason}\n'
            f'}}'
        )

    def _parse_rewrite_response(
        self, response: str, target_sources: set, mode: str
    ) -> Optional[Dict]:
        """解析 LLM rewrite 响应。失败返回 None。

        校验规则：
        1. 必须是合法 JSON
        2. 必须包含 rewrite_mode 和 queries 字段
        3. queries 中的 key 必须是合法 source_type
        4. 空字符串 value 视为缺失（调用方会用原始 query 替代）
        """
        try:
            clean = response.strip()
            # 去 markdown 包裹
            if clean.startswith("```"):
                clean = re.sub(r"^```(?:json)?\s*", "", clean)
                clean = re.sub(r"\s*```$", "", clean)

            # 尝试提取 JSON 对象
            obj_match = re.search(r"\{[\s\S]*\}", clean)
            json_str = obj_match.group() if obj_match else clean

            import json
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                # 尝试修复常见问题（尾逗号等）
                sanitized = re.sub(r',\s*([}\]])', r'\1', json_str)
                data = json.loads(sanitized)

            if not isinstance(data, dict):
                logger.warning("Query rewrite 响应不是 JSON 对象")
                return None

            queries = data.get("queries")
            if not isinstance(queries, dict):
                logger.warning("Query rewrite 响应缺少 queries 字段")
                return None

            # 过滤非法 key，保留合法 source_type
            valid_source_types = {"community", "broad_web", "academic", "developer"}
            filtered_queries = {}
            for k, v in queries.items():
                if k in valid_source_types and isinstance(v, str) and v.strip():
                    filtered_queries[k] = v.strip()

            return {
                "rewrite_mode": mode,
                "canonical_intent": data.get("canonical_intent") if mode == "contextual" else None,
                "queries": filtered_queries,
                "reason": data.get("reason") if mode == "contextual" else None,
            }
        except Exception as e:
            logger.warning("Query rewrite 响应解析失败: %s", e)
            return None

    @staticmethod
    def _make_rewrite_cache_key(
        query: str, platforms: List[str], plan_id: Optional[str]
    ) -> str:
        """生成 rewrite 缓存键：SHA-256(query|sorted_platforms|plan_id)。"""
        import hashlib
        raw = f"{query}|{'|'.join(sorted(platforms))}|{plan_id or ''}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def expand_keywords(self, query: str) -> List[str]:
        """[TODO: 未来实现] 使用 LLM 扩展搜索关键词。MVP 返回原始关键词。"""
        return [query]

    async def close(self) -> None:
        """关闭浏览器资源。"""
        await self._browser_agent.close()
        await self._xhs_searcher.close()
        await self._zhihu_searcher.close()
        await self._github_searcher.close()
        await self._arxiv_searcher.close()
        await self._tavily_searcher.close()

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
                elif config.name == "arxiv":
                    return await self._arxiv_searcher.search(query, limit)
                elif config.name == "tavily":
                    return await self._tavily_searcher.search(query, limit)
                else:
                    logger.warning(f"平台 {config.name} 配置了 use_api_search 但无对应搜索器")
                    return []

            # 小红书：使用 XhsSearcher（MediaCrawler 签名 + httpx）
            if config.name == "xiaohongshu":
                logger.warning("[XHS-TRIGGER] search_single_platform 触发小红书搜索: query='%s', limit=%d", query, limit)
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
