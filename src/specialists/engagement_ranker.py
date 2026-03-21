"""
EngagementRanker — 互动数据初筛排序器

基于评论/点赞比例、标题关键词加权和广告降权，
对跨平台搜索结果进行初筛排序。不调 LLM，纯数值计算。

公式：comment_like_ratio × (1 + title_boost) × ad_penalty
GitHub 特殊处理：直接用 stars 排序。

调用方：SearchOrchestrator.search_all_platforms_stream()
"""

import logging
from typing import List

from src.specialists.browser_models import RawSearchResult

logger = logging.getLogger(__name__)

# 复用 search_orchestrator 中的广告关键词
_AD_KEYWORDS = ["报班", "课程优惠", "限时", "折扣", "免费试听", "领取资料", "加群"]


def _to_num(v) -> float:
    """安全转换为数值。"""
    if v is None:
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


class EngagementRanker:
    """互动数据初筛排序器"""

    BOOST_KEYWORDS: List[str] = ["经验贴", "面经", "攻略", "踩坑", "总结", "实战"]

    def rank(self, results: List[RawSearchResult], top_n: int = 20) -> List[RawSearchResult]:
        """
        对全部搜索结果进行互动数据初筛排序。

        排序逻辑：
        1. 计算评论/点赞比例作为核心指标
        2. 标题包含 BOOST_KEYWORDS 的文章额外加权
        3. 广告关键词降权（复用现有 _AD_KEYWORDS）
        4. 返回 top_n 条（结果总数 < 20 时返回全部）

        Args:
            results: 所有平台汇总的原始搜索结果
            top_n: 初筛保留数量，默认 20
        Returns:
            排序后的 top_n 条结果
        """
        if not results:
            return []

        # 写入临时 _engagement_score 字段，供 PipelineExecutor 读取后写入 trace
        for r in results:
            r.engagement_metrics["_engagement_score"] = self._engagement_score(r)

        scored = sorted(results, key=lambda r: r.engagement_metrics.get("_engagement_score", 0), reverse=True)

        if len(scored) < 20:
            return scored

        return scored[:top_n]

    def _engagement_score(self, result: RawSearchResult) -> float:
        """
        计算单条结果的互动分。

        公式：comment_like_ratio * (1 + title_boost) * ad_penalty
        - comment_like_ratio = comments / max(likes, 1)
        - title_boost = 0.3 if 标题包含加权关键词
        - ad_penalty = 0.3 if 标题包含广告关键词, else 1.0

        GitHub 特殊处理：直接用 stars 作为互动分（API 已按 stars 降序排列）。
        """
        # GitHub：直接用 stars 排序，不走 comment_like_ratio 公式
        if result.platform == "github":
            return _to_num(result.engagement_metrics.get("stars", 0))

        m = result.engagement_metrics
        comments = _to_num(m.get("comments_count", 0))
        likes = _to_num(m.get("likes", 0))

        # 核心指标：评论/点赞比例
        comment_like_ratio = comments / max(likes, 1)

        # 标题加权
        title_boost = 0.3 if any(kw in result.title for kw in self.BOOST_KEYWORDS) else 0.0

        # 广告降权
        ad_penalty = 0.3 if any(kw in result.title for kw in _AD_KEYWORDS) else 1.0

        return comment_like_ratio * (1 + title_boost) * ad_penalty
