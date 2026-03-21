"""
LLM-as-Judge — 搜索结果相关性自动评分

复用项目现有的 LLM Provider，不引入额外依赖。
单条评分一次 LLM 调用，返回 1-5 分 + 理由。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


class LLMJudge:
    """LLM-as-Judge 封装，复用项目 ProviderFactory。"""

    def __init__(self, llm_provider=None):
        if llm_provider is None:
            from src.providers.factory import ProviderFactory
            llm_provider = ProviderFactory.create_llm()
        self._llm = llm_provider

    def score_search_result(
        self,
        query: str,
        title: str,
        description: str,
        content_summary: str,
        learning_goal: str = "",
        learning_level: str = "",
    ) -> dict:
        """对单条搜索结果打分。

        Returns:
            {"score": 1-5, "reason": "..."}
            解析失败时返回 {"score": 0, "reason": "parse_error"}
        """
        goal_ctx = f"\n学习目标: {learning_goal}" if learning_goal else ""
        level_ctx = f"\n学习者水平: {learning_level}" if learning_level else ""

        prompt = f"""你是一个学习资源评估专家。请评估以下搜索结果对学习者的帮助程度。

搜索查询: {query}{goal_ctx}{level_ctx}

搜索结果:
- 标题: {title}
- 描述: {description[:300]}
- 内容摘要: {content_summary[:500] if content_summary else '(无)'}

评分标准:
1分 = 完全无关，与查询主题不匹配
2分 = 略有关联，但对学习帮助很小
3分 = 有一定帮助，但不够深入或不够针对
4分 = 很有帮助，内容相关且有学习价值
5分 = 非常有帮助，高度相关、内容优质、适合学习者水平

请严格按以下 JSON 格式输出，不要输出其他内容:
{{"score": <1-5的整数>, "reason": "<一句话理由>"}}"""

        return self._call_and_parse(prompt)

    def score_rag_context(
        self,
        query: str,
        retrieved_passages: list[str],
    ) -> dict:
        """评估 RAG 检索结果的整体相关性。

        Returns:
            {"score": 1-5, "reason": "..."}
        """
        passages_text = ""
        for i, p in enumerate(retrieved_passages[:5], 1):
            passages_text += f"\n[段落{i}] {p[:300]}"

        prompt = f"""你是一个检索质量评估专家。请评估以下检索结果对回答查询的帮助程度。

查询: {query}

检索到的段落:{passages_text}

评分标准:
1分 = 检索结果与查询完全无关
2分 = 有少量相关信息，但大部分无关
3分 = 部分相关，能提供一些有用信息
4分 = 高度相关，能很好地支撑回答
5分 = 完美匹配，检索结果直接回答了查询

请严格按以下 JSON 格式输出，不要输出其他内容:
{{"score": <1-5的整数>, "reason": "<一句话理由>"}}"""

        return self._call_and_parse(prompt)

    def _call_and_parse(self, prompt: str) -> dict:
        """调用 LLM 并解析 JSON 响应。"""
        try:
            response = self._llm.simple_chat(prompt, max_tokens=200)
            return self._parse_score(response)
        except Exception as e:
            logger.warning(f"LLM Judge 调用失败: {e}")
            return {"score": 0, "reason": f"llm_error: {e}"}

    @staticmethod
    def _parse_score(text: str) -> dict:
        """从 LLM 响应中解析 score + reason。"""
        # 尝试直接 JSON 解析
        try:
            # 提取 JSON 块
            match = re.search(r'\{[^}]+\}', text)
            if match:
                data = json.loads(match.group())
                score = int(data.get("score", 0))
                if 1 <= score <= 5:
                    return {
                        "score": score,
                        "reason": str(data.get("reason", "")),
                    }
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

        # 降级：正则提取数字
        match = re.search(r'["\']?score["\']?\s*[:=]\s*(\d)', text)
        if match:
            score = int(match.group(1))
            if 1 <= score <= 5:
                return {"score": score, "reason": "parsed_from_regex"}

        return {"score": 0, "reason": "parse_error"}
