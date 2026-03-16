"""
QualityScorer - LLM 驱动的资源质量评估

使用 LLM 对搜索到的资源进行多维度质量评估：
- 互动指标（engagement）
- 内容深度（depth）
- 评论质量（comments）
- 时效性（freshness）

当 LLM 不可用时，使用基于平台配置的评分策略作为降级方案：
- 小红书：deduplicated_comment_count × 5 + 收藏数 × 2 + 点赞数 × 1
- B站：播放量 × 1 + 弹幕数 × 3 + 收藏数 × 2 + 点赞数 × 1
- YouTube：观看数 × 1 + 点赞数 × 2 + 评论数 × 3
- Google：启发式评分（有摘要 +0.3，知名站点 +0.3，标题相关度 +0.4）
"""

import json
import logging
import re
from typing import List, Optional, Tuple

from src.specialists.browser_models import RawSearchResult, ScoredResult
from src.specialists.platform_configs import PLATFORM_CONFIGS

logger = logging.getLogger(__name__)

# 知名技术站点列表（用于 Google 结果启发式评分）
KNOWN_TECH_SITES = [
    "developer.mozilla.org",  # MDN
    "stackoverflow.com",
    "github.com",
    "docs.python.org",
    "docs.microsoft.com",
    "learn.microsoft.com",
    "developer.android.com",
    "developer.apple.com",
    "reactjs.org",
    "vuejs.org",
    "angular.io",
    "nodejs.org",
    "rust-lang.org",
    "go.dev",
    "kotlinlang.org",
    "typescriptlang.org",
    "w3schools.com",
    "geeksforgeeks.org",
    "medium.com",
    "dev.to",
    "freecodecamp.org",
    "csdn.net",
    "juejin.cn",
    "zhihu.com",
    "segmentfault.com",
]


class QualityScorer:
    """使用 LLM 进行资源质量评估"""

    DIMENSIONS = ["engagement", "depth", "comments", "freshness"]

    def __init__(self, llm_provider=None):
        """
        初始化 QualityScorer

        Args:
            llm_provider: LLM Provider 实例，为 None 时使用启发式评分
        """
        self._llm = llm_provider

    async def score_batch(
        self, results: List[RawSearchResult]
    ) -> List[ScoredResult]:
        """
        批量评估资源质量，返回带评分的结果。

        Args:
            results: 原始搜索结果列表

        Returns:
            带评分的 ScoredResult 列表（评分已归一化到 [0, 1]）
        """
        scored = []
        for result in results:
            score, reason = await self._score_single(result)
            scored.append(
                ScoredResult(
                    raw=result,
                    quality_score=score,
                    recommendation_reason=reason,
                )
            )
        
        # 归一化评分到 [0, 1] 区间
        return self._normalize_scores(scored)

    def _normalize_scores(self, scored: List[ScoredResult]) -> List[ScoredResult]:
        """将各平台评分归一化到 [0, 1] 区间。
        
        归一化后，最高分结果的 quality_score == 1.0。
        """
        if not scored:
            return scored
        
        max_score = max(s.quality_score for s in scored)
        if max_score > 0:
            for s in scored:
                s.quality_score = s.quality_score / max_score
        
        return scored

    async def _score_single(self, result: RawSearchResult) -> Tuple[float, str]:
        """评估单条资源，优先 LLM，降级到启发式。"""
        if self._llm is not None:
            try:
                prompt = self._build_scoring_prompt(result)
                response = self._llm.simple_chat(
                    prompt,
                    system_prompt=(
                        "你是一个学习资源质量评估专家。请根据提供的资源信息，"
                        "从互动指标、内容深度、评论质量、时效性四个维度综合评分。"
                        "严格按照指定的 JSON 格式输出。"
                    ),
                )
                return self._parse_score_response(response)
            except Exception as e:
                logger.warning(f"LLM scoring failed for '{result.title}': {e}")
                return 0.0, ""

        # 无 LLM 时使用启发式评分
        return self._heuristic_score(result)

    def _build_scoring_prompt(self, result: RawSearchResult) -> str:
        """
        构建包含四个维度的评分 prompt。

        四个维度：
        1. engagement - 互动指标（点赞、收藏、评论数）
        2. depth - 内容深度与实用性
        3. comments - 评论质量
        4. freshness - 时效性
        """
        metrics = result.engagement_metrics
        missing_dims: List[str] = []

        # 互动指标
        if result.platform == "github":
            # GitHub 特有指标
            stars = metrics.get("stars", None)
            forks = metrics.get("forks", None)
            open_issues = metrics.get("open_issues", None)
            language = metrics.get("language", "")
            updated_at = metrics.get("updated_at", "")
            author = metrics.get("author", "未知")

            engagement_parts = []
            if stars is not None:
                engagement_parts.append(f"Stars: {stars}")
            if forks is not None:
                engagement_parts.append(f"Forks: {forks}")
            if open_issues is not None:
                engagement_parts.append(f"Open Issues: {open_issues}")
            if language:
                engagement_parts.append(f"语言: {language}")
            if updated_at:
                engagement_parts.append(f"最近更新: {updated_at[:10]}")
        else:
            likes = metrics.get("likes", None)
            collected = metrics.get("collected", None)
            comments_count = metrics.get("comments_count", None)
            share_count = metrics.get("share_count", None)
            author = metrics.get("author", "未知")

            engagement_parts = []
            if likes is not None:
                engagement_parts.append(f"点赞数: {likes}")
            if collected is not None:
                engagement_parts.append(f"收藏数: {collected}")
            if comments_count is not None:
                engagement_parts.append(f"评论数: {comments_count}")
            if share_count is not None:
                engagement_parts.append(f"分享数: {share_count}")

        if not engagement_parts:
            missing_dims.append("互动指标")
        engagement_text = ", ".join(engagement_parts) if engagement_parts else "无互动数据"

        # 内容深度
        snippet = result.content_snippet or result.description
        if not snippet:
            missing_dims.append("内容深度")
        depth_text = snippet[:500] if snippet else "无内容摘要"

        # 评论质量
        comments_text = ""
        if result.top_comments:
            comment_lines = []
            for c in result.top_comments[:5]:
                text = c.get("text", "")
                c_likes = c.get("likes", 0)
                comment_lines.append(f"  [{c_likes}赞] {text[:100]}")
            comments_text = "\n".join(comment_lines)
        elif result.comments:
            comments_text = "\n".join(
                f"  - {c[:100]}" for c in result.comments[:5]
            )
        else:
            missing_dims.append("评论质量")
            comments_text = "无评论数据"

        missing_note = ""
        if missing_dims:
            missing_note = (
                f"\n注意：以下维度数据缺失，请基于可用维度评估，"
                f"并在推荐理由中注明：{', '.join(missing_dims)}"
            )

        prompt = f"""请评估以下学习资源的质量，从 0.0 到 1.0 打分，并给出中文推荐理由。

## 资源信息
- 标题: {result.title}
- 平台: {result.platform}
- 类型: {result.resource_type}
- 作者: {author}

## 互动指标
{engagement_text}

## 内容摘要
{depth_text}

## 评论区精选
{comments_text}
{missing_note}

请严格按以下 JSON 格式输出，不要输出其他内容：
```json
{{"score": 0.75, "reason": "推荐理由（中文，一句话说明资源优势和适用场景）"}}
```"""
        return prompt

    def _parse_score_response(self, response: str) -> Tuple[float, str]:
        """
        解析 LLM 返回的评分和推荐理由。

        Returns:
            (quality_score, recommendation_reason)
            解析失败时返回 (0.0, "")
        """
        try:
            # 尝试直接解析 JSON
            clean = response.strip()
            if clean.startswith("```"):
                clean = re.sub(r"^```(?:json)?\s*", "", clean)
                clean = re.sub(r"\s*```$", "", clean)

            # 尝试从文本中提取 JSON 对象
            json_match = re.search(r"\{[^{}]*\}", clean)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = json.loads(clean)

            score = float(data.get("score", 0.0))
            reason = str(data.get("reason", ""))

            # 确保 score 在 [0.0, 1.0] 范围内
            score = max(0.0, min(1.0, score))

            return score, reason

        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(f"Failed to parse LLM score response: {e}")
            return 0.0, ""

    def _heuristic_score(self, result: RawSearchResult) -> Tuple[float, str]:
        """
        基于平台配置的启发式评分（LLM 不可用时的降级方案）。

        各平台评分策略：
        - 小红书：deduplicated_comment_count × 5 + 收藏数 × 2 + 点赞数 × 1
        - B站：播放量 × 1 + 弹幕数 × 3 + 收藏数 × 2 + 点赞数 × 1
        - YouTube：观看数 × 1 + 点赞数 × 2 + 评论数 × 3
        - Google：启发式评分（有摘要 +0.3，知名站点 +0.3，标题相关度 +0.4）
        """
        score = self._platform_score(result)
        reason = self._build_heuristic_reason(result)
        return score, reason

    def _platform_score(self, result: RawSearchResult) -> float:
        """根据平台类型计算原始互动分。"""
        platform = result.platform
        config = PLATFORM_CONFIGS.get(platform)
        
        # Google 使用特殊的启发式评分
        if platform == "google":
            return self._google_heuristic_score(result)
        
        # GitHub：stars 作为核心信号，sigmoid 映射到 [0, 1]
        if platform == "github":
            return self._github_heuristic_score(result)
        
        # 有配置的平台使用 scoring_weights
        if config and config.scoring_weights:
            return self._weighted_score(result, config.scoring_weights)
        
        # 无配置的平台使用通用启发式评分
        return self._generic_heuristic_score(result)

    def _weighted_score(self, result: RawSearchResult, weights: dict) -> float:
        """根据权重配置计算加权互动分。"""
        metrics = result.engagement_metrics
        score = 0.0
        
        # 小红书特殊处理：使用去重评论数
        if result.platform == "xiaohongshu":
            # 优先使用 deduplicated_comment_count
            comments = result.deduplicated_comment_count
            if comments == 0:
                comments = _safe_num(metrics.get("comments_count", 0))
            score += comments * weights.get("comments", 0)
            score += _safe_num(metrics.get("collected", 0)) * weights.get("collected", 0)
            score += _safe_num(metrics.get("likes", 0)) * weights.get("likes", 0)
        elif result.platform == "bilibili":
            # B站：播放量 × 1 + 弹幕数 × 3 + 收藏数 × 2 + 点赞数 × 1
            score += _safe_num(metrics.get("views", metrics.get("play", 0))) * weights.get("views", 0)
            score += _safe_num(metrics.get("danmaku", 0)) * weights.get("danmaku", 0)
            score += _safe_num(metrics.get("collected", metrics.get("favorites", 0))) * weights.get("collected", 0)
            score += _safe_num(metrics.get("likes", metrics.get("like", 0))) * weights.get("likes", 0)
        elif result.platform == "youtube":
            # YouTube：观看数 × 1 + 点赞数 × 2 + 评论数 × 3
            score += _safe_num(metrics.get("views", 0)) * weights.get("views", 0)
            score += _safe_num(metrics.get("likes", 0)) * weights.get("likes", 0)
            score += _safe_num(metrics.get("comments", metrics.get("comments_count", 0))) * weights.get("comments", 0)
        else:
            # 通用加权计算
            for metric_key, weight in weights.items():
                score += _safe_num(metrics.get(metric_key, 0)) * weight
        
        return score

    def _github_heuristic_score(self, result: RawSearchResult) -> float:
        """GitHub 仓库启发式评分。

        Stars 作为核心信号，sigmoid 映射到 [0, 1]。
        有 README（content_snippet）额外加分。
        """
        metrics = result.engagement_metrics
        stars = _safe_num(metrics.get("stars", 0))

        # sigmoid 映射：stars / (stars + 1000)，1000 stars 得 0.5 分
        score = stars / (stars + 1000) if stars > 0 else 0.0

        # 有 README 内容加分
        if result.content_snippet:
            score = min(1.0, score + 0.1)

        return score

    def _google_heuristic_score(self, result: RawSearchResult) -> float:
        """Google 结果启发式评分。
        
        评分规则：
        - 有内容摘要 +0.3
        - 来自知名技术站点 +0.3
        - 标题与查询相关度 +0.4（基于标题长度和关键词密度）
        """
        score = 0.0
        
        # 有内容摘要 +0.3
        if result.description or result.content_snippet:
            score += 0.3
        
        # 来自知名技术站点 +0.3
        url = result.url.lower()
        for site in KNOWN_TECH_SITES:
            if site in url:
                score += 0.3
                break
        
        # 标题相关度 +0.4（简化实现：标题长度适中且非空）
        title = result.title
        if title:
            # 标题长度在 10-100 字符之间得分较高
            title_len = len(title)
            if 10 <= title_len <= 100:
                score += 0.4
            elif title_len > 0:
                score += 0.2
        
        return score


    def _github_heuristic_score(self, result: RawSearchResult) -> float:
        """GitHub 仓库启发式评分。

        Stars 作为核心信号，sigmoid 映射到 [0, 1]。
        有 README（content_snippet）额外加分。
        """
        metrics = result.engagement_metrics
        stars = _safe_num(metrics.get("stars", 0))

        # sigmoid 映射：stars / (stars + 1000)，1000 stars 得 0.5 分
        score = stars / (stars + 1000) if stars > 0 else 0.0

        # 有 README 内容加分
        if result.content_snippet:
            score = min(1.0, score + 0.1)

        return score


    def _generic_heuristic_score(self, result: RawSearchResult) -> float:
        """通用启发式评分（无平台配置时使用）。"""
        metrics = result.engagement_metrics
        likes = _safe_num(metrics.get("likes", 0))
        collected = _safe_num(metrics.get("collected", 0))
        comments_count = _safe_num(metrics.get("comments_count", 0))

        # 通用公式：评论数×5 + 收藏数×2 + 点赞数×1
        composite = comments_count * 5 + collected * 2 + likes

        # 归一化：使用 sigmoid-like 映射
        if composite > 0:
            score = composite / (composite + 5000)
        else:
            score = 0.0

        # 内容加分
        if result.comments or result.top_comments:
            score += 0.1
        if result.content_snippet or result.description:
            score += 0.1

        return min(1.0, score)

    def _build_heuristic_reason(self, result: RawSearchResult) -> str:
        """构建启发式评分的推荐理由。"""
        metrics = result.engagement_metrics
        reason_parts = []
        missing_dims = []

        platform = result.platform
        
        if platform == "xiaohongshu":
            likes = _safe_num(metrics.get("likes", 0))
            collected = _safe_num(metrics.get("collected", 0))
            comments = result.deduplicated_comment_count or _safe_num(metrics.get("comments_count", 0))
            if likes or collected or comments:
                reason_parts.append(f"互动数据：👍{int(likes)} ⭐{int(collected)} 💬{int(comments)}")
            else:
                missing_dims.append("互动指标")
        elif platform == "bilibili":
            views = _safe_num(metrics.get("views", metrics.get("play", 0)))
            danmaku = _safe_num(metrics.get("danmaku", 0))
            if views or danmaku:
                reason_parts.append(f"播放{int(views)} 弹幕{int(danmaku)}")
            else:
                missing_dims.append("互动指标")
        elif platform == "youtube":
            views = _safe_num(metrics.get("views", 0))
            likes = _safe_num(metrics.get("likes", 0))
            if views or likes:
                reason_parts.append(f"观看{int(views)} 点赞{int(likes)}")
            else:
                missing_dims.append("互动指标")
        elif platform == "google":
            if result.description:
                reason_parts.append("有内容摘要")
            url = result.url.lower()
            for site in KNOWN_TECH_SITES:
                if site in url:
                    reason_parts.append(f"来自{site}")
                    break
        elif platform == "github":
            stars = _safe_num(metrics.get("stars", 0))
            forks = _safe_num(metrics.get("forks", 0))
            language = metrics.get("language", "")
            parts = []
            if stars:
                parts.append(f"⭐{int(stars)}")
            if forks:
                parts.append(f"🍴{int(forks)}")
            if language:
                parts.append(language)
            if parts:
                reason_parts.append(" ".join(parts))
            else:
                missing_dims.append("互动指标")
        else:
            likes = _safe_num(metrics.get("likes", 0))
            collected = _safe_num(metrics.get("collected", 0))
            comments_count = _safe_num(metrics.get("comments_count", 0))
            if likes or collected or comments_count:
                reason_parts.append(f"互动数据：👍{int(likes)} ⭐{int(collected)} 💬{int(comments_count)}")
            else:
                missing_dims.append("互动指标")

        if result.content_snippet:
            reason_parts.append("有内容摘要")
        elif platform not in ["google", "github"]:
            missing_dims.append("内容深度")

        if result.top_comments:
            reason_parts.append(f"有{len(result.top_comments)}条高赞评论")
        elif result.comments:
            reason_parts.append(f"有{len(result.comments)}条评论")
        elif platform not in ["google", "bilibili", "github"]:
            missing_dims.append("评论质量")

        if missing_dims:
            reason_parts.append(f"（缺失维度：{', '.join(missing_dims)}）")

        reason = "；".join(reason_parts) if reason_parts else "数据不足，无法评估"
        return reason


def _safe_num(value) -> float:
    """安全地将值转换为数字。"""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0
