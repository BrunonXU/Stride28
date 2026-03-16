"""
QualityAssessor - LLM 质量评估器

使用 LLM 对提取的正文和评论进行内容质量评估，
单次调用同时生成评分、推荐理由、内容摘要、评论结论。

降级策略：
- 正文 < 50 字：直接使用原文作为摘要
- 正文提取失败：基于标题+描述+互动数据降级评估，推荐理由标注"正文未提取"
- LLM 调用失败：启发式降级（正文前 150 字、评论结论置空、互动数据估算评分）
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple

from src.specialists.browser_models import RawSearchResult, ScoredResult

logger = logging.getLogger(__name__)


def _safe_num(v) -> float:
    """安全转换为数值。"""
    if v is None:
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


@dataclass
class LearnerContext:
    """搜索评估的学习者上下文，用于个性化质量评估。"""
    query: str = ""                     # 搜索关键词
    goal: str = ""                      # 学习目标
    level: str = ""                     # 当前水平
    background: str = ""               # 背景
    daily_hours: str = ""              # 每日可用时间
    plan_summary: str = ""             # 学习规划摘要（来自 progress 表）


@dataclass
class AssessmentResult:
    """LLM 质量评估结果"""
    quality_score: float = 0.0          # 1-10 分
    content_summary: str = ""           # AI 内容整理（markdown 格式）


class QualityAssessor:
    """LLM 质量评估器"""

    def __init__(self, llm_provider=None):
        """
        初始化 QualityAssessor。

        Args:
            llm_provider: LLM Provider 实例（具有 simple_chat 方法），
                          为 None 时所有评估走启发式降级。
        """
        self._llm = llm_provider

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    async def assess_batch(
        self,
        items: List[Tuple[RawSearchResult, str, List[Dict]]],
        learner_context: Optional[LearnerContext] = None,
    ) -> List[ScoredResult]:
        """
        批量评估：将多条结果打包为一个 prompt 进行单次 LLM 调用。

        Args:
            items: [(raw_result, extracted_content, top_comments), ...]
                   extracted_content 为提取的正文文本
                   top_comments 为高赞评论列表 [{text, likes, author}, ...]
            learner_context: 学习者上下文（profile + query + plan_summary），
                             为 None 时退化为通用评估
        Returns:
            评估后的 ScoredResult 列表（含摘要、评论结论等扩展字段）
        """
        if not items:
            return []

        # 尝试 LLM 批量评估
        if self._llm is not None:
            try:
                prompt = self._build_batch_prompt(items, learner_context)
                response = self._llm.simple_chat(
                    prompt,
                    system_prompt=(
                        "你是一个学习资源评估专家，服务于一个智能学习规划平台。"
                        "平台的用户是想学习某个领域知识的人，系统帮他们搜索高质量资源并制定学习规划。"
                        "你的任务是从学习者视角评估资源，提取对学习者真正有用的知识点和可操作建议。"
                        "忽略作者自我介绍、引流话术、关注点赞等无关内容。"
                        "严格按照指定的 JSON 格式输出。"
                    ),
                )
                results = self._parse_batch_response(response, items)
                if results is not None:
                    return results
            except Exception as e:
                logger.warning(f"LLM batch assessment failed: {e}")

        # LLM 失败 → 启发式降级
        return self._batch_heuristic_fallback(items)

    async def assess_single_fallback(
        self, raw: RawSearchResult
    ) -> ScoredResult:
        """
        降级评估：正文提取失败时，基于标题、描述和互动数据评估。
        """
        assessment = self._heuristic_fallback(raw)
        return ScoredResult(
            raw=raw,
            quality_score=assessment.quality_score,
            content_summary=assessment.content_summary,
            extracted_content="",
        )

    # ------------------------------------------------------------------
    # Prompt 构建
    # ------------------------------------------------------------------

    def _build_batch_prompt(
        self,
        items: List[Tuple[RawSearchResult, str, List[Dict]]],
        learner_context: Optional[LearnerContext] = None,
    ) -> str:
        """
        构建批量评估 prompt。

        输出结构简化为 quality_score + content_summary（markdown 格式）。
        对于正文 < 50 字的条目，直接使用原文作为摘要。
        """
        # ---- 学习者上下文块 ----
        learner_block = ""
        if learner_context:
            parts = []
            if learner_context.query:
                parts.append(f"本次搜索关键词：「{learner_context.query}」")
            profile_lines = []
            if learner_context.goal:
                profile_lines.append(f"- 学习目标：{learner_context.goal}")
            if learner_context.level:
                profile_lines.append(f"- 当前水平：{learner_context.level}")
            if learner_context.background:
                profile_lines.append(f"- 背景：{learner_context.background}")
            if learner_context.daily_hours:
                profile_lines.append(f"- 每日学习时间：{learner_context.daily_hours}小时")
            if profile_lines:
                parts.append("学习者画像：\n" + "\n".join(profile_lines))
            if learner_context.plan_summary:
                parts.append(f"当前学习规划：\n{learner_context.plan_summary}")
            if parts:
                learner_block = "\n\n".join(parts) + "\n\n" + (
                    "请结合学习者的水平、目标和搜索意图来评估每条资源的匹配度。\n"
                    "对学习者当前水平来说太难或太简单的资源应适当降低评分。\n"
                    "与搜索意图不相关的资源应降低评分。\n"
                    "注意：规划信息仅作为参考，不要因为资源超出当前规划范围就降分——"
                    "稍有挑战性的资源对学习者的成长可能更有价值。\n"
                )

        entries: List[str] = []
        for idx, (raw, content, comments) in enumerate(items):
            short_content = len(content) < 50
            comments_text = self._format_comments(comments)

            entry_lines = [
                f"### 条目 {idx + 1}",
                f"- 标题: {raw.title}",
                f"- 平台: {raw.platform}",
                f"- 描述: {raw.description[:200] if raw.description else '无'}",
            ]

            if short_content:
                entry_lines.append(f"- 正文（短文，直接作为摘要）: {content}")
                entry_lines.append("- 注意: 正文较短，无需生成 content_summary，将直接使用原文")
            else:
                entry_lines.append(f"- 正文: {content}")

            entry_lines.append(f"- 评论区精选:\n{comments_text}")

            # 互动数据（按平台展示不同指标）
            m = raw.engagement_metrics
            if raw.platform == "github":
                stars = m.get("stars", 0)
                forks = m.get("forks", 0)
                open_issues = m.get("open_issues", 0)
                language = m.get("language", "")
                updated_at = m.get("updated_at", "")
                meta = f"Stars {stars}, Forks {forks}, Issues {open_issues}"
                if language:
                    meta += f", 语言 {language}"
                if updated_at:
                    meta += f", 更新 {updated_at[:10]}"
                entry_lines.append(f"- 互动数据: {meta}")
            else:
                likes = m.get("likes", 0)
                collected = m.get("collected", 0)
                comments_count = m.get("comments_count", 0)
                entry_lines.append(f"- 互动数据: 点赞 {likes}, 收藏 {collected}, 评论 {comments_count}")

            entries.append("\n".join(entry_lines))

        items_block = "\n\n".join(entries)

        platform_guidance = """评分公平性指引：
    - 小红书：有正文+评论+图片，数据最丰富，可做精准判断
    - B站/YouTube：主要依据标题+描述+互动数据，视频内容无法直接评估
    - GitHub：依据标题+描述+README，关注项目实用性和学习价值
    - Google：仅有标题+描述+页面摘要，信息最少

    重要：不同平台数据丰富度不同，但评分标准统一。
    数据少的平台不应因信息不足而被系统性低估。
    评估维度：知识密度、实用性、教学质量、可操作性。
    不要因为互动数据高就给高分，关注内容本身的学习价值。"""

        prompt = f"""请逐条评估以下 {len(items)} 条学习资源的质量，从学习者视角提取有用信息。

    {learner_block}{platform_guidance}

    {items_block}

    请严格按以下 JSON 格式输出，不要输出其他内容：
    ```json
    [
      {{
    "quality_score": 7.5,
    "content_summary": "markdown 格式的内容整理（见下方要求）"
      }}
    ]
    ```

    content_summary 要求（最重要的字段，在前端用 markdown 渲染）：
    - 目标：让学习者不看原文就能充分了解"这篇资源讲了什么、有哪些干货、值不值得看"
    - 完全忽略作者自我介绍、引流话术、"点赞关注"等废话，只提取知识干货
    - 对**关键术语**、**工具名**、**项目名**、**核心结论**使用 markdown 加粗
    - 如果有评论区数据，将评论区有价值的补充观点融入对应段落中
    - 信息密度要高：每个回答/段落至少提取 3-5 个要点，覆盖核心论点、关键案例/数据、结论

    格式要求（使用 markdown）：
    ## 整体评价
    2-3 段话概括这篇资源的核心价值、讨论方向和综合结论。
    帮助用户快速判断是否值得深入阅读，以及适合什么水平的读者。

    ## 内容整理
    按自然段落展开具体的知识点、学习路线、工具推荐、或可操作建议。
    每个段落要有足够的信息量，不要只写一句话概括。
    段落之间用换行分隔，像写一篇详细的读书笔记。

    知乎多回答聚合内容的特殊格式：
    如果正文包含多个【回答N·赞X】标记，说明这是一个知乎问题下的多条高赞回答聚合。
    请按以下格式整理：
    ## 整体评价
    2-3 段话概括这个问题的核心讨论方向、各方观点分歧和综合结论。
    ### 回答1（赞X）
    详细提取该回答的核心观点和干货，至少 3-5 个要点。
    包括：主要论点是什么、用了什么案例/数据支撑、得出了什么结论、有什么可操作建议。
    用自然段落写，不要只写一句话概括。
    ### 回答2（赞X）
    同上，每个回答都要详细展开。
    ### 回答3（赞X）
    同上。

    如果评论区有补充观点，在对应回答段落末尾用"评论区补充：..."的形式融入。

    不同类型资源的提取重点：
    - 学习路线/攻略类：提取完整路线步骤和推荐资源名称
    - 教程类：列出教的核心技术点和前置知识
    - 经验分享类：提取关键结论和可操作建议，包括具体案例
    - 项目介绍类：列出技术栈、核心功能、适合什么水平的学习者
    - 论文/深度文章类：提取核心论点、方法论和实验结论
    - 面经/求职类：提取具体面试题目、考察重点和准备建议

    各平台专属评估引导：
    【GitHub 仓库】
    - 用户看不到原文 README，你的总结是唯一信息来源，必须写清楚
    - 整体评价：一句话说清这个项目是什么、解决什么问题
    - 内容整理：技术栈、核心功能、项目亮点、适合什么水平的学习者
    - 如果 README 包含 Quick Start / Getting Started，提取关键步骤
    - 明确说明"推荐理由"：为什么这个项目值得学习者关注

    【知乎】
    - 多回答聚合时按回答拆分整理，每条回答独立展开
    - 重点提取：核心观点、论据/案例、可操作建议
    - 评论区有价值的补充融入对应段落

    【小红书】
    - 图文笔记为主，关注实操性和可复现性
    - 提取：具体步骤、工具推荐、踩坑经验
    - 评论区经常有作者补充和用户反馈，注意提取

    【B站 / YouTube】
    - 视频内容无法直接评估，主要依据标题+描述+互动数据
    - 重点判断：是否是系统性教程、适合什么水平、时长是否合理

    【Google 搜索结果】
    - 信息最少，仅有标题+描述+页面摘要
    - 重点判断：是否是官方文档、权威教程、还是低质量内容农场

    若条目标注"正文较短"则 content_summary 填空字符串。
    数组长度必须等于 {len(items)}，顺序与条目一一对应。
    quality_score 范围 1-10，整数或一位小数。"""

        return prompt


    # ------------------------------------------------------------------
    # 响应解析
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_json(text: str) -> str:
        """修复 LLM 输出中常见的 JSON 格式问题。

        处理：
        1. JSON string value 内的 raw 换行/回车 → 转义为 \\n / \\r
        2. 非法控制字符（\\x00-\\x1f 中除 \\t 外的，在 string 外部直接删除）
        3. 尾逗号（,] 或 ,}）
        """
        # 策略：逐字符扫描，在 JSON string 内部将 raw \n \r 转义，
        # 删除其他控制字符；在 string 外部删除所有控制字符
        result = []
        in_string = False
        escape_next = False

        for ch in text:
            if escape_next:
                result.append(ch)
                escape_next = False
                continue

            if ch == '\\' and in_string:
                result.append(ch)
                escape_next = True
                continue

            if ch == '"' and not escape_next:
                in_string = not in_string
                result.append(ch)
                continue

            if in_string:
                # JSON string 内部：raw 换行/回车必须转义
                if ch == '\n':
                    result.append('\\n')
                elif ch == '\r':
                    result.append('\\r')
                elif ch == '\t':
                    result.append('\\t')
                elif ord(ch) < 0x20:
                    # 其他控制字符直接删除
                    pass
                else:
                    result.append(ch)
            else:
                # string 外部：保留空白（\n\r\t\space），删除其他控制字符
                if ch in ('\n', '\r', '\t', ' ') or ord(ch) >= 0x20:
                    result.append(ch)

        sanitized = ''.join(result)
        # 去尾逗号：,\s*] 或 ,\s*}
        sanitized = re.sub(r',\s*([}\]])', r'\1', sanitized)
        return sanitized

    def _parse_batch_response(
        self,
        response: str,
        items: List[Tuple[RawSearchResult, str, List[Dict]]],
    ) -> Optional[List[ScoredResult]]:
        """解析 LLM 批量评估响应，返回 None 表示解析失败。"""
        try:
            clean = response.strip()
            if clean.startswith("```"):
                clean = re.sub(r"^```(?:json)?\s*", "", clean)
                clean = re.sub(r"\s*```$", "", clean)

            # 尝试提取 JSON 数组
            arr_match = re.search(r"\[[\s\S]*\]", clean)
            json_str = arr_match.group() if arr_match else clean

            # 先尝试直接解析，失败后用 sanitize 修复再试
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                sanitized = self._sanitize_json(json_str)
                data = json.loads(sanitized)
                logger.info("JSON sanitize 修复成功")

            if not isinstance(data, list) or len(data) != len(items):
                logger.warning(
                    f"LLM response array length mismatch: "
                    f"expected {len(items)}, got {len(data) if isinstance(data, list) else 'non-list'}"
                )
                return None

            results: List[ScoredResult] = []
            for idx, (raw, content, _comments) in enumerate(items):
                entry = data[idx] if isinstance(data[idx], dict) else {}
                score = max(1.0, min(10.0, float(entry.get("quality_score", 5.0))))

                # 短正文：直接使用原文作为摘要
                if len(content) < 50:
                    summary = content
                else:
                    summary = str(entry.get("content_summary", ""))

                results.append(ScoredResult(
                    raw=raw,
                    quality_score=score,
                    content_summary=summary,
                    extracted_content=content,
                ))

            return results

        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(f"Failed to parse LLM batch response: {e}")
            return None

    # ------------------------------------------------------------------
    # 降级策略
    # ------------------------------------------------------------------

    def _heuristic_fallback(self, raw: RawSearchResult) -> AssessmentResult:
        """
        LLM 调用失败时的启发式降级：
        - 内容摘要 = 空（截断原文不是 AI 整理，不应冒充）
        - 评论结论 = 空
        - 质量评分 = 基于互动数据估算
        """
        quality_score = self._estimate_score_from_engagement(raw)

        return AssessmentResult(
            quality_score=quality_score,
            content_summary="",
        )

    def _batch_heuristic_fallback(
        self,
        items: List[Tuple[RawSearchResult, str, List[Dict]]],
    ) -> List[ScoredResult]:
        """批量启发式降级：不生成伪摘要，content_summary 留空。"""
        results: List[ScoredResult] = []
        for raw, content, _comments in items:
            score = self._estimate_score_from_engagement(raw)

            results.append(ScoredResult(
                raw=raw,
                quality_score=score,
                content_summary="",
                extracted_content=content,
            ))
        return results

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _estimate_score_from_engagement(self, raw: RawSearchResult) -> float:
        """基于互动数据估算质量评分 (1-10)。"""
        m = raw.engagement_metrics
        likes = _safe_num(m.get("likes", 0))
        collected = _safe_num(m.get("collected", 0))
        comments_count = _safe_num(m.get("comments_count", 0))

        # 加权互动分
        engagement = comments_count * 3 + collected * 2 + likes
        # sigmoid 映射到 1-10
        if engagement > 0:
            score = 1 + 9 * (engagement / (engagement + 500))
        else:
            score = 1.0

        return round(min(10.0, max(1.0, score)), 1)

    def _build_fallback_reason(self, raw: RawSearchResult) -> str:
        """构建降级推荐理由。"""
        m = raw.engagement_metrics
        parts: List[str] = []
        likes = _safe_num(m.get("likes", 0))
        collected = _safe_num(m.get("collected", 0))
        comments_count = _safe_num(m.get("comments_count", 0))

        if likes or collected or comments_count:
            parts.append(f"👍{int(likes)} ⭐{int(collected)} 💬{int(comments_count)}")

        if raw.content_snippet:
            parts.append("有内容摘要")

        return "；".join(parts) if parts else "数据不足"

    @staticmethod
    def _format_comments(comments: List[Dict]) -> str:
        """格式化评论列表为文本。"""
        if not comments:
            return "  无评论数据"
        lines: List[str] = []
        for c in comments[:10]:
            text = c.get("text", "")
            c_likes = c.get("likes", 0)
            author = c.get("author", "匿名")
            lines.append(f"  [{c_likes}赞] {author}: {text[:100]}")
        return "\n".join(lines)
