"""
Episodic Memory — 情景记忆管理器

参考 MemGPT/Letta 的三层 Memory 架构，实现对话摘要的生成、存储和注入。
当对话超过阈值时，用 LLM 将旧对话压缩为结构化摘要，持久化到 SQLite，
后续对话和 Studio 工具生成时注入 prompt，实现跨轮次的上下文延续。

核心设计：
- 异步后台生成：摘要在后台线程池执行，不阻塞当前请求
- 增量式摘要：新摘要 = 旧摘要上下文 + 新对话压缩
- 摘要链深度控制：最多 3 条，超出时合并最早两条
- 质量校验：50-500 字，不合格则丢弃等下次重试
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, List

from backend import database

logger = logging.getLogger(__name__)

# 并发控制：记录正在生成摘要的 plan_id
_summarizing_plans: set = set()

# 配置常量
SUMMARY_TRIGGER_THRESHOLD = 20   # 未摘要消息数阈值（不含 Working Memory）
WORKING_MEMORY_SIZE = 12         # Working Memory 窗口大小（与 chat.py 的 MAX_HISTORY 一致）
MAX_SUMMARY_CHAIN_DEPTH = 3      # 最大摘要链深度
MIN_SUMMARY_LENGTH = 50          # 摘要最小长度（字）
MAX_SUMMARY_LENGTH = 500         # 摘要最大长度（字）
MAX_SUMMARY_INJECT_CHARS = 1000  # 注入 prompt 时的最大字符数


class EpisodicMemory:
    """情景记忆管理器

    职责：
    1. 判断是否需要触发摘要生成（should_trigger）
    2. 调用 LLM 生成摘要（trigger_background_summary / _generate_summary）
    3. 管理摘要链深度（_enforce_chain_depth）
    4. 提供摘要文本供 prompt 注入（get_injectable_summary）
    5. 清空对话时强制摘要（force_summarize_all）
    """

    def __init__(self, llm_provider):
        """
        Args:
            llm_provider: LLMProvider 实例，支持依赖注入（测试时传 mock）
        """
        self._llm = llm_provider

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def get_injectable_summary(self, plan_id: str) -> Optional[str]:
        """获取可注入 prompt 的摘要文本。

        返回最新摘要的 summary_text，截断到 MAX_SUMMARY_INJECT_CHARS。
        无摘要时返回 None。
        """
        try:
            latest = database.get_latest_conversation_summary(plan_id)
            if not latest:
                return None
            text = latest.get("summaryText", "")
            if not text:
                return None
            if len(text) > MAX_SUMMARY_INJECT_CHARS:
                text = text[:MAX_SUMMARY_INJECT_CHARS] + "（摘要已截断）"
            return text
        except Exception as e:
            logger.warning(f"[EpisodicMemory] 获取摘要失败 plan={plan_id}: {e}")
            return None

    def should_trigger(self, plan_id: str) -> bool:
        """检查是否需要触发摘要生成。

        条件：未摘要消息数（不含 Working Memory 窗口）>= 阈值，且没有正在进行的任务。
        """
        if plan_id in _summarizing_plans:
            return False
        try:
            latest = database.get_latest_conversation_summary(plan_id)
            after_id = latest.get("endMessageId") if latest else None
            unsummarized = database.count_messages_after(plan_id, after_id)
            # 可压缩的消息数 = 未摘要总数 - Working Memory 窗口
            compressible = unsummarized - WORKING_MEMORY_SIZE
            return compressible >= SUMMARY_TRIGGER_THRESHOLD
        except Exception as e:
            logger.warning(f"[EpisodicMemory] 触发检查失败 plan={plan_id}: {e}")
            return False

    async def trigger_background_summary(self, plan_id: str) -> None:
        """启动后台摘要生成任务（不阻塞调用方）。

        在线程池中执行同步的 LLM 调用，通过 _summarizing_plans 防止并发重复。
        """
        if plan_id in _summarizing_plans:
            return
        _summarizing_plans.add(plan_id)
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._generate_summary, plan_id)
        except Exception as e:
            logger.warning(f"[EpisodicMemory] 后台摘要生成失败 plan={plan_id}: {e}")
        finally:
            _summarizing_plans.discard(plan_id)

    def force_summarize_all(self, plan_id: str) -> None:
        """强制摘要所有未摘要消息（清空对话时调用）。

        同步执行，exclude_last_n=0（不保留 Working Memory 窗口）。
        失败时静默降级，不影响清空操作。
        """
        try:
            latest = database.get_latest_conversation_summary(plan_id)
            after_id = latest.get("endMessageId") if latest else None
            previous_summary = latest.get("summaryText", "") if latest else ""

            messages = database.get_messages_range(plan_id, after_id, exclude_last_n=0)
            if not messages:
                return

            prompt = self._build_summary_prompt(messages, previous_summary)

            from src.providers.base import Message
            response = self._llm.chat([
                Message(role="system", content="你是一个对话摘要助手。"),
                Message(role="user", content=prompt),
            ], temperature=0.3)
            result = response.content if response else ""

            if result and MIN_SUMMARY_LENGTH <= len(result) <= MAX_SUMMARY_LENGTH:
                summary_record = {
                    "id": str(uuid.uuid4()),
                    "planId": plan_id,
                    "summaryText": result,
                    "messageCount": len(messages),
                    "startMessageId": messages[0]["id"],
                    "endMessageId": messages[-1]["id"],
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                }
                database.insert_conversation_summary(summary_record)
                self._enforce_chain_depth(plan_id)
                logger.info(f"[EpisodicMemory] 强制摘要完成 plan={plan_id} messages={len(messages)}")
            else:
                logger.warning(
                    f"[EpisodicMemory] 强制摘要质量不合格 plan={plan_id} "
                    f"len={len(result) if result else 0}"
                )
        except Exception as e:
            logger.warning(f"[EpisodicMemory] 强制摘要失败 plan={plan_id}: {e}")

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _generate_summary(self, plan_id: str) -> None:
        """同步执行摘要生成（在线程池中调用）"""
        # 1. 获取前序摘要
        latest = database.get_latest_conversation_summary(plan_id)
        after_id = latest.get("endMessageId") if latest else None
        previous_summary = latest.get("summaryText", "") if latest else ""

        # 2. 获取待压缩消息
        messages = database.get_messages_range(
            plan_id, after_id, exclude_last_n=WORKING_MEMORY_SIZE
        )
        if not messages:
            return

        # 3. 构建摘要 prompt
        prompt = self._build_summary_prompt(messages, previous_summary)

        # 4. 调用 LLM
        from src.providers.base import Message
        try:
            response = self._llm.chat([
                Message(role="system", content="你是一个对话摘要助手。"),
                Message(role="user", content=prompt),
            ], temperature=0.3)
            result = response.content if response else ""
        except Exception as e:
            logger.warning(f"[EpisodicMemory] LLM 调用失败 plan={plan_id}: {e}")
            return

        # 5. 质量校验
        if not result or len(result) < MIN_SUMMARY_LENGTH or len(result) > MAX_SUMMARY_LENGTH:
            logger.warning(
                f"[EpisodicMemory] 摘要质量不合格 plan={plan_id} "
                f"len={len(result) if result else 0}，丢弃"
            )
            return

        # 6. 写入 DB
        summary_record = {
            "id": str(uuid.uuid4()),
            "planId": plan_id,
            "summaryText": result,
            "messageCount": len(messages),
            "startMessageId": messages[0]["id"],
            "endMessageId": messages[-1]["id"],
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        try:
            database.insert_conversation_summary(summary_record)
        except Exception as e:
            logger.warning(f"[EpisodicMemory] 摘要写入 DB 失败 plan={plan_id}: {e}")
            return

        logger.info(
            f"[EpisodicMemory] 摘要生成完成 plan={plan_id} "
            f"messages={len(messages)} summary_len={len(result)}"
        )

        # 7. 摘要链深度控制
        self._enforce_chain_depth(plan_id)

    def _enforce_chain_depth(self, plan_id: str) -> None:
        """保持摘要链深度 ≤ MAX_SUMMARY_CHAIN_DEPTH。

        超出时合并最早两条：把第一条文本拼入第二条，删除第一条。
        不重新调 LLM，粗暴拼接截断（最早的摘要信息价值最低）。
        """
        try:
            summaries = database.get_conversation_summaries(plan_id)  # ASC
            while len(summaries) > MAX_SUMMARY_CHAIN_DEPTH:
                oldest = summaries[0]
                second = summaries[1]
                merged_text = f"{oldest['summaryText']}\n\n{second['summaryText']}"
                if len(merged_text) > MAX_SUMMARY_LENGTH:
                    merged_text = merged_text[:MAX_SUMMARY_LENGTH] + "（已合并截断）"
                database.update_conversation_summary_text(
                    second["id"],
                    merged_text,
                    new_start_message_id=oldest.get("startMessageId", ""),
                    new_message_count=oldest.get("messageCount", 0) + second.get("messageCount", 0),
                )
                database.delete_conversation_summary(oldest["id"])
                summaries = summaries[1:]
        except Exception as e:
            logger.warning(f"[EpisodicMemory] 摘要链深度控制失败 plan={plan_id}: {e}")

    @staticmethod
    def _build_summary_prompt(messages: List[dict], previous_summary: str = "") -> str:
        """构建摘要生成的 prompt。

        指示 LLM 提取：关键问题、知识盲区、核心概念、学习偏好。
        单条消息截断到 300 字，避免 prompt 过长。
        """
        parts = [
            "请将以下学习对话压缩为 200-300 字的结构化摘要。",
            "",
            "提取以下信息：",
            "1. 学习者提出的关键问题",
            "2. 暴露的知识盲区",
            "3. 讨论过的核心概念",
            "4. 学习偏好和风格",
            "",
        ]

        if previous_summary:
            parts.append(f"[前序摘要（请在此基础上增量更新）]\n{previous_summary}")
            parts.append("")

        parts.append("[待压缩的对话]")
        for msg in messages:
            role = "学生" if msg.get("role") == "user" else "导师"
            content = msg.get("content", "")
            if len(content) > 300:
                content = content[:300] + "..."
            parts.append(f"{role}: {content}")

        parts.append("")
        parts.append("请直接输出摘要文本，不要加标题或格式标记。")
        return "\n".join(parts)
