"""
资源搜索端点

集成 ResourceSearcher + QualityScorer，按 quality_score 降序排列。
支持每平台独立进度推送（SSE）。
"""

import asyncio
import logging
import uuid
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter
from fastapi.requests import Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(tags=["search"])

VALID_PLATFORMS = {"bilibili", "youtube", "google", "github", "xiaohongshu", "zhihu"}


class SearchRequest(BaseModel):
    query: str
    platforms: Optional[List[str]] = None
    planId: Optional[str] = None


class SearchResultItem(BaseModel):
    id: str
    title: str
    url: str
    platform: str
    type: str = ""          # 资源类型：article/question/video/repo 等
    description: str
    qualityScore: float
    contentSummary: str = ""
    engagementMetrics: Dict[str, Any] = {}
    imageUrls: List[str] = []
    topComments: List[str] = []
    contentText: str = ""


class SearchProgressEvent(BaseModel):
    stage: Literal["searching", "filtering", "extracting", "evaluating", "done", "error"]
    message: str = ""
    platform: Optional[str] = None
    total: Optional[int] = None
    completed: Optional[int] = None
    results: Optional[List[SearchResultItem]] = None
    error: Optional[str] = None


@router.post("/search", response_model=List[SearchResultItem])
async def search_resources(body: SearchRequest):
    """
    同步搜索端点，返回按 quality_score 降序排列的结果列表。
    """
    if not body.query.strip():
        return []

    platforms = [p for p in (body.platforms or [])] if body.platforms else None

    try:
        from src.specialists.resource_searcher import ResourceSearcher
        searcher = ResourceSearcher()

        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None,
            lambda: searcher.search(
                query=body.query,
                platforms=platforms,
                user_selected=bool(platforms),
            )
        )

        items = [
            SearchResultItem(
                id=str(uuid.uuid4()),
                title=r.title,
                url=r.url,
                platform=r.platform,
                type=r.type,
                description=r.description[:120] if r.description else "",
                qualityScore=round(r.quality_score, 2),
            )
            for r in results
        ]
        items.sort(key=lambda x: x.qualityScore, reverse=True)
        return items

    except Exception as e:
        logger.error(f"[search] failed: {e}")
        return []


@router.post("/search/stream")
async def search_stream(body: SearchRequest, request: Request):
    """
    SSE 流式搜索端点，通过 SearchOrchestrator 五阶段漏斗推送进度。
    """
    cancel_event = asyncio.Event()

    async def _generate():
        orchestrator = None
        try:
            if not body.query.strip():
                evt = SearchProgressEvent(stage="done", results=[])
                yield f"data: {evt.model_dump_json()}\n\n"
                return

            platforms = [p for p in (body.platforms or list(VALID_PLATFORMS)) if p in VALID_PLATFORMS]
            if not platforms:
                evt = SearchProgressEvent(stage="error", message="无有效搜索平台")
                yield f"data: {evt.model_dump_json()}\n\n"
                return

            from src.specialists.search_orchestrator import SearchOrchestrator
            from src.providers.factory import ProviderFactory
            try:
                llm = ProviderFactory.create_llm()
            except Exception as e:
                logger.warning(f"LLM provider 创建失败，关键词翻译将不可用: {e}")
                llm = None
            orchestrator = SearchOrchestrator(llm_provider=llm)

            # ---- 构建学习者上下文（个性化质量评估）----
            learner_context = None
            if body.planId:
                try:
                    from src.specialists.quality_assessor import LearnerContext
                    from backend import database

                    # 查询学习者画像
                    profile = database.get_learner_profile(body.planId)
                    # 查询学习进度，构建轻量摘要
                    progress = database.get_progress(body.planId)
                    plan_summary = ""
                    if progress:
                        total_days = len(progress)
                        completed_days = sum(1 for d in progress if d.get("completed"))
                        lines = []
                        for d in progress:
                            day_num = d.get("dayNumber", 0)
                            title = d.get("title", "")
                            done = d.get("completed", False)
                            prefix = "✅" if done else "🔵" if day_num == completed_days + 1 else "  "
                            suffix = "（当前）" if (not done and day_num == completed_days + 1) else ""
                            lines.append(f"{prefix} Day {day_num}: {title}{suffix}")
                        plan_summary = f"进度：第{completed_days}天/共{total_days}天\n" + "\n".join(lines)

                    learner_context = LearnerContext(
                        query=body.query,
                        goal=profile.get("goal", "") if profile else "",
                        level=profile.get("level", "") if profile else "",
                        background=profile.get("background", "") if profile else "",
                        daily_hours=profile.get("dailyHours", "") if profile else "",
                        plan_summary=plan_summary,
                    )
                    logger.info(f"[search] 学习者上下文已构建: goal={learner_context.goal}, level={learner_context.level}")
                except Exception as e:
                    logger.warning(f"[search] 构建学习者上下文失败（降级为通用评估）: {e}")

            try:
                async for event in orchestrator.search_all_platforms_stream(
                    query=body.query,
                    platforms=platforms,
                    cancel_event=cancel_event,
                    learner_context=learner_context,
                ):
                    if await request.is_disconnected():
                        cancel_event.set()
                        break

                    if cancel_event.is_set():
                        break

                    stage = event.get("stage", "")

                    if stage == "done":
                        raw_results = event.get("results", [])
                        items = [
                            _to_search_result_item(r) for r in raw_results
                        ]
                        progress = SearchProgressEvent(stage="done", results=items)
                        yield f"data: {progress.model_dump_json()}\n\n"
                    else:
                        progress = SearchProgressEvent(
                            stage=stage,
                            message=event.get("message", ""),
                            platform=event.get("platform"),
                            total=event.get("total"),
                            completed=event.get("completed"),
                            error=event.get("message") if stage == "error" else None,
                        )
                        yield f"data: {progress.model_dump_json()}\n\n"
            except Exception as e:
                logger.error(f"[search/stream] error: {e}")
                try:
                    err_evt = SearchProgressEvent(stage="error", message=str(e))
                    yield f"data: {err_evt.model_dump_json()}\n\n"
                except Exception:
                    pass
        except (asyncio.CancelledError, ConnectionError, Exception) as e:
            # 客户端断开连接（abort）时，yield 会抛出异常，静默处理
            logger.info(f"[search/stream] client disconnected: {type(e).__name__}")
        finally:
            cancel_event.set()
            if orchestrator:
                try:
                    await orchestrator.close()
                except Exception as e:
                    # Windows 上关闭 Playwright 子进程可能触发 pipe 错误，静默处理
                    logger.debug(f"[search/stream] orchestrator close error (safe to ignore): {e}")

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _to_search_result_item(result_dict: dict) -> SearchResultItem:
    """Convert a SearchResult dict (from orchestrator) to a SearchResultItem for SSE."""
    return SearchResultItem(
        id=result_dict.get("id") or str(uuid.uuid4()),
        title=result_dict.get("title", ""),
        url=result_dict.get("url", ""),
        platform=result_dict.get("platform", ""),
        type=result_dict.get("type", ""),
        description=(result_dict.get("description", "") or "")[:120],
        qualityScore=round(result_dict.get("quality_score", 0.0), 2),
        contentSummary=result_dict.get("content_summary", ""),
        engagementMetrics=result_dict.get("engagement_metrics", {}),
        imageUrls=result_dict.get("image_urls", []),
        topComments=result_dict.get("comments_preview", []),
        contentText=result_dict.get("content_text", ""),
    )
