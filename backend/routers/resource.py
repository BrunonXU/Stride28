"""
资源刷新端点

提供 POST /resource/refresh 端点，用于手动刷新某条搜索结果的详情信息
（正文、评论、图片 URL），并调用 QualityAssessor 重新评估质量。

使用全局 BrowserAgent 单例，避免每次刷新都重新启动浏览器和登录。
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import database

logger = logging.getLogger(__name__)
router = APIRouter(tags=["resource"])

REFRESH_TIMEOUT = 90  # 刷新超时（秒）

# 全局 BrowserAgent 单例，刷新时复用
_global_browser_agent: Optional[Any] = None
_browser_lock: Optional[asyncio.Lock] = None


def _get_lock() -> asyncio.Lock:
    global _browser_lock
    if _browser_lock is None:
        _browser_lock = asyncio.Lock()
    return _browser_lock


class RefreshRequest(BaseModel):
    url: str
    platform: str
    materialId: Optional[str] = None


class RefreshResponse(BaseModel):
    content: str
    contentSummary: str
    comments: List[Dict[str, Any]]
    commentSummary: str
    imageUrls: List[str]
    engagementMetrics: Dict[str, Any]
    qualityScore: float
    recommendationReason: str
    topComments: List[str] = []


async def _get_browser_agent(config):
    """获取或创建全局 BrowserAgent 单例。"""
    global _global_browser_agent

    async with _get_lock():
        if _global_browser_agent is not None and _global_browser_agent._context is not None:
            return _global_browser_agent

        # 需要新建或重建
        from src.specialists.browser_agent import BrowserAgent
        if _global_browser_agent is not None:
            try:
                await _global_browser_agent.close()
            except Exception:
                pass

        agent = BrowserAgent()
        await agent.launch(config)
        _global_browser_agent = agent
        return agent


@router.post("/resource/refresh", response_model=RefreshResponse)
async def refresh_resource(body: RefreshRequest):
    """
    刷新单条资源详情。

    1. 复用全局浏览器实例（无需重新登录）
    2. 导航到目标 URL，提取正文、评论、图片
    3. 调用 QualityAssessor 重新评估质量
    4. 返回完整的刷新结果

    超时 90 秒返回 HTTP 408，URL 不可访问返回 HTTP 422。
    """
    from src.specialists.platform_configs import PLATFORM_CONFIGS

    config = PLATFORM_CONFIGS.get(body.platform)
    if config is None:
        raise HTTPException(status_code=422, detail=f"不支持的平台: {body.platform}")

    try:
        result = await asyncio.wait_for(
            _do_refresh(body, config),
            timeout=REFRESH_TIMEOUT,
        )
        # Persist extra_data to materials table if materialId is provided
        if body.materialId:
            try:
                database.update_material_extra_data(body.materialId, {
                    "contentSummary": result.contentSummary,
                    "commentSummary": result.commentSummary,
                    "imageUrls": result.imageUrls,
                    "topComments": result.topComments,
                    "engagementMetrics": result.engagementMetrics,
                    "qualityScore": result.qualityScore,
                    "recommendationReason": result.recommendationReason,
                })
            except Exception as e:
                logger.warning(f"[resource/refresh] Failed to persist extra_data: {e}")
        return result
    except asyncio.TimeoutError:
        raise HTTPException(status_code=408, detail="刷新超时，请稍后重试")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[resource/refresh] unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"刷新失败: {e}")


async def _do_refresh(body, config) -> RefreshResponse:
    """Execute the refresh logic."""
    from src.specialists.browser_models import RawSearchResult
    from src.specialists.quality_assessor import QualityAssessor

    # 1. 获取全局浏览器实例（复用已有的，不会重新登录）
    try:
        browser_agent = await _get_browser_agent(config)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"无法启动浏览器: {e}")

    # 2. Fetch detail
    detail = await browser_agent.fetch_detail(body.url, config)
    if detail is None:
        raise HTTPException(status_code=422, detail=f"无法访问资源 URL: {body.url}")

    content = detail.content_snippet or ""
    top_comments = detail.top_comments or []
    image_urls = detail.image_urls or []
    engagement_metrics: dict = {}
    if detail.likes > 0:
        engagement_metrics["likes"] = detail.likes
    if detail.favorites > 0:
        engagement_metrics["collected"] = detail.favorites
    if detail.comments_count > 0:
        engagement_metrics["comments_count"] = detail.comments_count
    if detail.extra_metrics:
        engagement_metrics.update(detail.extra_metrics)

    # 3. Build RawSearchResult for QualityAssessor
    raw = RawSearchResult(
        title="",
        url=body.url,
        platform=body.platform,
        resource_type=config.resource_type,
        description="",
        engagement_metrics=engagement_metrics,
        comments=[c.get("text", "") for c in top_comments],
        content_snippet=content,
        top_comments=top_comments,
        image_urls=image_urls,
    )

    # 4. Assess quality (使用 LLM 生成信息整理)
    from src.providers.factory import ProviderFactory
    try:
        llm = ProviderFactory.create_llm()
    except Exception:
        llm = None
    assessor = QualityAssessor(llm_provider=llm)
    if content:
        scored_list = await assessor.assess_batch([(raw, content, top_comments)])
        scored = scored_list[0] if scored_list else await assessor.assess_single_fallback(raw)
    else:
        scored = await assessor.assess_single_fallback(raw)

    # 5. Build response
    # topComments: 纯文本评论列表，供前端 PreviewPopup 展示
    comments_text = [c.get("text", "")[:200] for c in top_comments[:5]]

    return RefreshResponse(
        content=content,
        contentSummary=scored.content_summary,
        comments=top_comments,
        commentSummary=scored.comment_summary,
        imageUrls=image_urls,
        engagementMetrics=engagement_metrics,
        qualityScore=round(scored.quality_score, 2),
        recommendationReason=scored.recommendation_reason,
        topComments=comments_text,
    )


# ------------------------------------------------------------------
# 深度分析端点 — 加入素材后触发
# ------------------------------------------------------------------

class DeepAnalysisRequest(BaseModel):
    """深度分析请求"""
    materialId: str
    title: str
    url: str
    platform: str
    description: str = ""
    contentSummary: str = ""
    commentSummary: str = ""
    topComments: List[str] = []
    engagementMetrics: Dict[str, Any] = {}


class DeepAnalysisResponse(BaseModel):
    """深度分析结果"""
    materialId: str
    keyPoints: List[str] = []
    keyFacts: List[str] = []
    methodology: List[str] = []
    credibility: Dict[str, Any] = {}


DEEP_ANALYSIS_TIMEOUT = 60  # 秒


@router.post("/resource/deep-analysis", response_model=DeepAnalysisResponse)
async def deep_analysis(body: DeepAnalysisRequest):
    """
    对单条已加入素材的资源做深度结构化分析。

    基于搜索阶段已有的 contentSummary、commentSummary、topComments 等数据，
    用 LLM 提取：核心观点、关键数据、方法论/步骤、可信度评估。
    不需要重新爬取，纯 LLM 分析。
    """
    from src.providers.factory import ProviderFactory

    try:
        llm = ProviderFactory.create_llm()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM 初始化失败: {e}")

    try:
        result = await asyncio.wait_for(
            _do_deep_analysis(llm, body),
            timeout=DEEP_ANALYSIS_TIMEOUT,
        )
        # 持久化到 materials 表
        try:
            existing = database.get_material_extra_data(body.materialId) or {}
            existing.update({
                "keyPoints": result.keyPoints,
                "keyFacts": result.keyFacts,
                "methodology": result.methodology,
                "credibility": result.credibility,
            })
            database.update_material_extra_data(body.materialId, existing)
        except Exception as e:
            logger.warning(f"[deep-analysis] Failed to persist: {e}")
        return result
    except asyncio.TimeoutError:
        raise HTTPException(status_code=408, detail="分析超时")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[deep-analysis] error: {e}")
        raise HTTPException(status_code=500, detail=f"分析失败: {e}")


async def _do_deep_analysis(llm, body: DeepAnalysisRequest) -> DeepAnalysisResponse:
    """执行深度分析的 LLM 调用。"""
    import json
    import re

    # 构建评论文本
    comments_text = ""
    if body.topComments:
        comments_text = "\n".join(f"- {c}" for c in body.topComments[:10])

    # 互动数据
    metrics_text = ""
    if body.engagementMetrics:
        parts = []
        for k, v in body.engagementMetrics.items():
            parts.append(f"{k}: {v}")
        metrics_text = ", ".join(parts)

    prompt = f"""请对以下学习资源进行深度结构化分析。

资源信息：
- 标题: {body.title}
- 平台: {body.platform}
- 描述: {body.description[:300] if body.description else '无'}
- 互动数据: {metrics_text or '无'}

AI 信息整理（已有摘要）：
{body.contentSummary or '无'}

评论结论：
{body.commentSummary or '无'}

高赞评论：
{comments_text or '无'}

请严格按以下 JSON 格式输出，不要输出其他内容：
```json
{{
  "key_points": ["核心观点1", "核心观点2", "核心观点3"],
  "key_facts": ["关键数据或事实1", "关键数据或事实2"],
  "methodology": ["步骤1", "步骤2"],
  "credibility": {{
    "timeliness": 8,
    "authority": 7,
    "accuracy": 9,
    "objectivity": 6,
    "timeliness_note": "一句话理由",
    "authority_note": "一句话理由",
    "accuracy_note": "一句话理由",
    "objectivity_note": "一句话理由"
  }}
}}
```

key_points（核心观点，3-5条）：
- 提取最重要的核心观点或结论，每条≤30字

key_facts（关键数据/事实）：
- 提取具体数据、数字、事实（融资金额、用户数、性能指标等）
- 没有具体数据则返回空数组

methodology（方法论/步骤）：
- 如果包含操作步骤、学习路线、实施方法，提取为有序列表，每条≤40字
- 没有则返回空数组

credibility（可信度评估，各维度0-10分）：
- timeliness（时效性）：内容是否过时
- authority（权威性）：来源是否可信
- accuracy（准确性）：数据是否有出处、论述是否自洽
- objectivity（客观性）：是否有广告/带货倾向
- 每个维度附带 _note 字段，一句话理由（≤20字）"""

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: llm.simple_chat(
            prompt,
            system_prompt=(
                "你是一个学习资源深度分析专家。"
                "基于已有的资源摘要和评论数据，提取结构化知识和可信度评估。"
                "严格按照 JSON 格式输出。"
            ),
        ),
    )

    # 解析响应
    try:
        clean = response.strip()
        if clean.startswith("```"):
            clean = re.sub(r"^```(?:json)?\s*", "", clean)
            clean = re.sub(r"\s*```$", "", clean)

        obj_match = re.search(r"\{[\s\S]*\}", clean)
        if obj_match:
            data = json.loads(obj_match.group())
        else:
            data = json.loads(clean)

        key_points = [str(p)[:30] for p in data.get("key_points", []) if p][:5]
        key_facts = [str(f)[:60] for f in data.get("key_facts", []) if f][:5]
        methodology = [str(s)[:40] for s in data.get("methodology", []) if s][:8]

        cred_raw = data.get("credibility", {})
        credibility: Dict[str, Any] = {}
        if isinstance(cred_raw, dict):
            for dim in ("timeliness", "authority", "accuracy", "objectivity"):
                try:
                    credibility[dim] = max(0, min(10, int(float(cred_raw.get(dim, 5)))))
                except (ValueError, TypeError):
                    credibility[dim] = 5
                credibility[f"{dim}_note"] = str(cred_raw.get(f"{dim}_note", ""))[:20]

        return DeepAnalysisResponse(
            materialId=body.materialId,
            keyPoints=key_points,
            keyFacts=key_facts,
            methodology=methodology,
            credibility=credibility,
        )
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning(f"[deep-analysis] Failed to parse LLM response: {e}")
        return DeepAnalysisResponse(materialId=body.materialId)
