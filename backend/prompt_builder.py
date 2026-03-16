"""
PromptBuilder — 为每个 Studio 工具类型构建富上下文 prompt。

PromptBuilder 拥有 prompt 构建的全部所有权：
- 自己调 rag_engine.build_context() 做 RAG 检索
- 自己从 database.get_messages() 拿历史并截断
- 自己把 allDays 进度数据格式化注入
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from langsmith import traceable

from backend import database

logger = logging.getLogger(__name__)


@dataclass
class PromptTemplate:
    role_instruction: str       # system_prompt (role persona)
    generation_instruction: str # tool-specific generation instructions
    output_format: str          # output format instructions


# ---------------------------------------------------------------------------
# Duration 兼容解析（string → number 迁移期间的 fallback）
# ---------------------------------------------------------------------------

# 旧格式中文字符串 → 天数映射
_DURATION_LEGACY_MAP: dict[str, int] = {
    "1周": 7,
    "2周": 14,
    "1个月": 28,
    "2个月": 28,
    "3个月": 28,
    "半年": 28,
}

# 合法天数范围
_DURATION_MIN = 3
_DURATION_MAX = 28
_DURATION_DEFAULT = 14


def safe_parse_duration(raw) -> int:
    """兼容旧格式中文字符串，返回天数（clamp 到 3-28）。

    支持的输入：
    - int / float：直接取整并 clamp
    - 数字字符串（如 "14"）：转 int 并 clamp
    - 旧格式中文（如 "1周"、"1个月"）：查映射表
    - None / 空字符串 / 未知字符串：返回默认值 14

    Returns:
        int: 3-28 范围内的天数
    """
    # None / 非字符串非数字 → 默认值
    if raw is None:
        return _DURATION_DEFAULT

    # 已经是数字类型（int / float）
    if isinstance(raw, (int, float)):
        try:
            val = int(raw)
        except (ValueError, OverflowError):
            # NaN / Infinity 无法转 int
            return _DURATION_DEFAULT
        return max(_DURATION_MIN, min(_DURATION_MAX, val))

    # 字符串处理
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return _DURATION_DEFAULT

        # 尝试数字字符串
        try:
            return max(_DURATION_MIN, min(_DURATION_MAX, int(raw)))
        except ValueError:
            pass

        # 旧格式中文 fallback
        return _DURATION_LEGACY_MAP.get(raw, _DURATION_DEFAULT)

    # 其他类型 → 默认值
    return _DURATION_DEFAULT


def _find_day(all_days: list[dict], day_number: int | None) -> dict | None:
    """Find a day dict by dayNumber."""
    if day_number is None:
        return None
    for d in all_days:
        if d.get("dayNumber") == day_number:
            return d
    return None


# ---------------------------------------------------------------------------
# Prompt templates for all 7 tool types
# ---------------------------------------------------------------------------

_TEMPLATES: dict[str, PromptTemplate] = {
    "study-guide": PromptTemplate(
        role_instruction=(
            "你是一位资深学习策略顾问。你的职责是分析学习者的背景、目标、已有材料和学习困惑，"
            "制定个性化的宏观学习路线图。你擅长构建知识体系、识别学习瓶颈、推荐高质量学习资源。\n"
            "你的输出是战略层面的指导——回答「学什么、按什么顺序学、怎么判断学会了」，"
            "而不是每日任务分解（那是学习计划的职责）。"
        ),
        generation_instruction=(
            # 基础指令，会被 _build_study_guide_instruction() 动态替换
            "请基于以下上下文，生成一份个性化的宏观学习路线图。"
        ),
        output_format=(
            "请使用 Markdown 大纲格式输出，包含清晰的标题层级。\n"
            "必须包含以下章节：学习路线图（分阶段，每阶段含里程碑）、知识体系、补充资源推荐。\n"
            "如果从对话历史中发现了用户的困惑点，在相关知识点旁用 ⚠️ 标注。\n"
            "不要输出 JSON 格式。"
        ),
    ),
    "learning-plan": PromptTemplate(
        role_instruction=(
            "你是一位课程设计师，擅长将学习目标拆解为可执行的每日任务序列。\n"
            "你的职责是战术层面的任务分解——回答「每天具体做什么、做多少、怎么验证做完了」。\n"
            "你不负责宏观知识体系梳理（那是学习指南的职责），也不负责知识点测验（那是测验的职责）。\n"
            "你生成的每一天都必须是可执行的：有明确的任务列表、验证标准和预计时长。"
        ),
        generation_instruction=(
            # 基础指令，会被 _build_learning_plan_instruction() 动态替换
            "请基于以下材料和学习进度，生成一份按天拆分的详细学习计划。"
        ),
        output_format=(
            "请严格输出紧凑 JSON（无缩进、无换行），结构如下：\n"
            '{"days":[{"dayNumber":1,"title":"...","tasks":[{"id":"t1","type":"reading","title":"..."}],'
            '"learningObjectives":"...","verificationCriteria":"...","knowledgePoints":["...","..."]}]}\n'
            "【关键约束】\n"
            "- 不要输出 JSON 以外的任何内容（不要 markdown code fence，不要解释文字）\n"
            "- 不要格式化 JSON（不要缩进、不要换行美化），直接输出单行紧凑 JSON\n"
            "- 不要包含 methodology 字段\n"
            "- 不要包含 tomorrowPreview 字段\n"
            "- 每个 day 只保留：dayNumber, title, tasks, learningObjectives, verificationCriteria, knowledgePoints"
        ),
    ),
    "flashcards": PromptTemplate(
        role_instruction=(
            "你是一位记忆训练师，擅长将知识点转化为高效的问答卡片，帮助学习者通过主动回忆巩固记忆。\n"
            "你的职责是生成适合间隔重复的短问答对——每张卡片聚焦一个概念，问题精准，答案简洁。\n"
            "你不负责综合测验（那是测验的职责），也不负责知识结构梳理（那是思维导图的职责）。\n"
            "卡片应覆盖定义、概念辨析、关键术语、易混淆点，粒度要小，适合快速翻阅。"
        ),
        generation_instruction=(
            # 基础指令，会被 _build_flashcards_instruction() 动态替换
            "请基于以下材料和学习进度，生成 10-15 张闪卡（问答对）。"
        ),
        output_format=(
            "每张卡片格式：\nQ: 问题\nA: 答案\n\n"
            "卡片之间用 --- 分隔。\n"
            "覆盖核心概念、定义、原理等关键知识点。"
        ),
    ),
    "quiz": PromptTemplate(
        role_instruction=(
            "你是一位考试出题专家，擅长设计能检验真实理解程度的测验题目。\n"
            "你的职责是生成阶段性综合测验——题目应覆盖已学知识点，侧重理解和应用而非死记硬背。\n"
            "你不负责日常记忆训练（那是闪卡的职责），也不负责学习进度分析（那是进度报告的职责）。\n"
            "题目应包含多种题型，难度梯度合理，每道题附带详细解析帮助学习者理解错误原因。"
        ),
        generation_instruction=(
            # 基础指令，会被 _build_quiz_instruction() 动态替换
            "请基于以下材料和学习进度，生成一份正式测验。"
        ),
        output_format=(
            "请严格输出 JSON 格式，结构如下：\n"
            '{"questions":[{"question":"题目文字","type":"single/multiple/truefalse/short",'
            '"options":["A. xxx","B. xxx","C. xxx","D. xxx"],'
            '"answer":"正确答案（如 C / AC / 对 / 简答文字）",'
            '"explanation":"错题解析文字"}]}\n'
            "【关键约束】\n"
            "- 不要输出 JSON 以外的任何内容\n"
            "- type 取值：single（单选）、multiple（多选）、truefalse（判断）、short（简答）\n"
            "- 判断题 options 固定为 [\"对\", \"错\"]\n"
            "- 简答题 options 为空数组 []\n"
            "- 不要包含评分标准字段\n"
            "- 每道题必须有 explanation（解析）"
        ),
    ),
    "progress-report": PromptTemplate(
        role_instruction=(
            "你是一位学习数据分析师，擅长从进度数据中提取洞察并给出可执行的改进建议。\n"
            "你的职责是基于 allDays 完成状态做纯数据分析——完成率、薄弱环节识别、学习节奏评估。\n"
            "你不负责内容生成或知识讲解，只负责数据驱动的分析和建议。\n"
            "分析必须基于实际数据，不要编造未发生的学习行为或虚构进度。"
        ),
        generation_instruction=(
            # 基础指令，会被 _build_progress_report_instruction() 动态替换
            "请基于以下学习进度数据，进行纯数据分析。"
        ),
        output_format=(
            "请严格输出 JSON 格式，结构如下：\n"
            '{"summary": {"completedDays": 0, "totalDays": 0, "percentage": 0}, '
            '"knowledgeGraph": [{"node": "...", "connections": ["..."]}], '
            '"timeline": [{"day": 1, "title": "...", "status": "...", "score": 0}], '
            '"weakPoints": ["..."], '
            '"nextSteps": ["..."]}\n'
            "不要输出 JSON 以外的任何内容。"
        ),
    ),
    "mind-map": PromptTemplate(
        role_instruction=(
            "你是一位知识结构化专家，擅长将零散的知识点组织为层次清晰的树状结构。\n"
            "你的职责是生成适合可视化的知识结构图——用 Markdown 标题层级表达概念的从属和关联关系。\n"
            "你不负责学习路线规划（那是学习指南的职责），也不负责知识点测验（那是测验的职责）。\n"
            "输出必须适配 markmap.js 渲染，层级不宜过深（建议 3-4 层），每个节点简洁有力。"
        ),
        generation_instruction=(
            # 基础指令，会被 _build_mind_map_instruction() 动态替换
            "请基于以下材料和学习进度，生成一份知识结构思维导图。"
        ),
        output_format=(
            "请使用 Markdown 标题层级格式输出（#/##/###/-），适合 markmap.js 渲染。\n"
            "不要使用 JSON 格式。\n"
            "用标题层级表达知识的层次关系和从属关系。"
        ),
    ),
    "day-summary": PromptTemplate(
        role_instruction=(
            "你是一位学习教练，擅长在每天学习结束后给予个性化的回顾、鼓励和前瞻性建议。\n"
            "你的职责是总结当天学习成果、分析与之前知识的关联、给出真诚的鼓励和明日预告。\n"
            "你不负责全局进度分析（那是进度报告的职责），也不负责知识点测验（那是测验的职责）。\n"
            "你的语气应该像一个了解学习者的教练——肯定努力、指出亮点、温和提醒薄弱点。"
        ),
        generation_instruction=(
            # 基础指令，会被 _build_day_summary_instruction() 动态替换
            "请基于以下学习进度和材料，总结当天的学习内容。"
        ),
        output_format=(
            "请使用 Markdown 格式输出，包含以下章节：\n"
            "## 知识回顾\n## 关联分析\n## 复习建议\n## 明日预告"
        ),
    ),
}


# ---------------------------------------------------------------------------
# PromptBuilder class
# ---------------------------------------------------------------------------

class PromptBuilder:
    """为每个 Studio 工具类型构建富上下文 prompt。

    PromptBuilder 拥有 prompt 构建的全部所有权：
    - 自己调 rag_engine.build_context() 做 RAG 检索
    - 自己从 database.get_messages() 拿历史并截断
    - 自己把 allDays 进度数据格式化注入
    """

    _templates = _TEMPLATES

    def __init__(self, rag_engine=None):
        self.rag_engine = rag_engine

    @traceable(name="prompt_builder.build")
    def build(self, content_type: str, learning_context) -> tuple[str, str]:
        """构建完整 prompt 和 system_prompt，可直接发给 LLM。

        Args:
            content_type: Tool type (e.g. "study-guide", "learning-plan").
            learning_context: Object with planId, allDays, currentDayNumber, learnerProfile attrs.

        Returns:
            (user_prompt, system_prompt) tuple.
        """
        template = self._templates[content_type]

        # Safely extract fields from learning_context (duck-typed)
        plan_id = getattr(learning_context, "planId", "") or ""
        all_days = getattr(learning_context, "allDays", None) or []
        current_day_number = getattr(learning_context, "currentDayNumber", None)
        learner_profile = getattr(learning_context, "learnerProfile", None)

        # 1. RAG retrieval with targeted query
        rag_context = self._retrieve_rag(content_type, learning_context)
        # 2. Formatted progress text（按工具类型差异化注入粒度）
        progress_text = self._format_progress(all_days, current_day_number, content_type)
        # 3. Formatted learner profile
        profile_text = self._format_learner_profile(learner_profile)

        # 4. 对话历史互斥注入：有摘要 → 只用摘要；无摘要 → fallback 到 6 轮原文
        episodic_summary = self._get_episodic_summary(plan_id)
        if episodic_summary:
            chat_history: list[dict] = []  # 摘要覆盖更广，不塞原文
        else:
            chat_history = self._get_truncated_history(plan_id, rounds=6)

        user_prompt = self._assemble(
            template, rag_context, chat_history, progress_text, profile_text,
            content_type=content_type,
            all_days=all_days,
            current_day_number=current_day_number,
            episodic_summary=episodic_summary,
        )
        
        # 6. role_instruction as system_prompt with current time
        from datetime import datetime
        now = datetime.now()
        weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        time_str = f"{now.strftime('%Y年%m月%d日 %H:%M:%S')} {weekdays[now.weekday()]}"
        system_prompt = f"【系统提示：当前真实时间是 {time_str}】\n\n{template.role_instruction}"
        
        return (user_prompt, system_prompt)

    def _retrieve_rag(self, content_type: str, ctx) -> str:
        """根据工具类型构造针对性 RAG 查询词并检索。

        progress-report 不做 RAG 检索。
        quiz 走专用多次检索路径（per-day top-2 合并去重）。
        """
        if not self.rag_engine or content_type == "progress-report":
            return ""

        # quiz 专用：per-day 多次检索
        if content_type == "quiz":
            all_days = getattr(ctx, "allDays", None) or []
            return self._build_quiz_rag_context(all_days)

        query = self._build_rag_query(content_type, ctx)
        if not query:
            return ""
        try:
            return self.rag_engine.build_context(query, k=5)
        except Exception as e:
            logger.warning("[PromptBuilder] RAG retrieval failed: %s", e)
            return ""

    def _get_truncated_history(self, plan_id: str, rounds: int = 6) -> list[dict]:
        """从数据库获取消息并截断到最近 N 轮（N*2 条）。"""
        if not plan_id:
            return []
        try:
            messages = database.get_messages(plan_id)
            return messages[-(rounds * 2):]
        except Exception as e:
            logger.warning("[PromptBuilder] Failed to get messages: %s", e)
            return []

    def _get_episodic_summary(self, plan_id: str) -> str:
        """从 DB 读取最新 episodic memory 摘要，截断到 1000 字符。"""
        if not plan_id:
            return ""
        try:
            latest_summary = database.get_latest_conversation_summary(plan_id)
            if latest_summary:
                text = latest_summary.get("summaryText", "")
                if len(text) > 1000:
                    text = text[:1000] + "（摘要已截断）"
                return text
        except Exception:
            pass  # 摘要获取失败不影响 Studio 生成
        return ""

    # 需要完整 task 详情的工具类型（迭代更新/当日总结需要看具体任务）
    _FULL_PROGRESS_TYPES = {"learning-plan", "day-summary"}

    def _format_progress(self, all_days: list[dict], current_day_number: int | None, content_type: str = "") -> str:
        """将 allDays 格式化为可注入 prompt 的文本。

        content_type 在 _FULL_PROGRESS_TYPES 中时展开每天的 task 列表，
        其余工具只输出 day 级别摘要（Day N: Title [状态]），节省 ~1500-2000 tokens。
        """
        if not all_days:
            return ""
        expand_tasks = content_type in self._FULL_PROGRESS_TYPES
        lines = []
        for day in all_days:
            day_num = day.get("dayNumber", "?")
            title = day.get("title", "未命名")
            completed = day.get("completed", False)
            status = "✅ 已完成" if completed else "⬜ 未完成"
            marker = " ← 当前" if day_num == current_day_number else ""
            lines.append(f"Day {day_num}: {title} [{status}]{marker}")

            # 仅对需要 task 详情的工具展开
            if expand_tasks:
                tasks = day.get("tasks", [])
                for task in tasks:
                    task_title = task.get("title", "")
                    task_done = "✅" if task.get("completed") else "⬜"
                    if task_title:
                        lines.append(f"  - {task_done} {task_title}")

        return "\n".join(lines)

    def _assemble(
        self,
        template: PromptTemplate,
        rag_context: str,
        chat_history: list[dict],
        progress_text: str,
        profile_text: str = "",
        content_type: str = "",
        all_days: list[dict] | None = None,
        current_day_number: int | None = None,
        episodic_summary: str = "",
    ) -> str:
        """Compose final user_prompt from sections separated by ---."""
        sections: list[str] = []

        # 0. Learner profile (highest priority context)
        if profile_text:
            sections.append(f"[学习者画像]\n{profile_text}")

        # 0.5 Episodic Memory 摘要（画像之后、材料之前）
        if episodic_summary:
            sections.append(f"[对话记忆摘要]\n{episodic_summary}")

        # 1. RAG context (skip for progress-report — already handled by empty rag_context)
        if rag_context:
            sections.append(f"[材料上下文：RAG 检索结果]\n{rag_context}")

        # 2. Learning progress
        if progress_text:
            sections.append(f"[学习进度上下文]\n{progress_text}")

        # 3. Chat history
        if chat_history:
            rounds = len(chat_history) // 2
            history_lines = []
            for msg in chat_history:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                history_lines.append(f"{role}: {content}")
            sections.append(f"[对话历史上下文：最近 {rounds} 轮]\n" + "\n".join(history_lines))

        # 4. Output format instruction（前移，让生成指令占据 recency bias 最高权重）
        sections.append(f"[输出格式指令]\n{template.output_format}")

        # 5. Tool-specific generation instruction（动态路由：约定优于配置）
        method_name = f"_build_{content_type.replace('-', '_')}_instruction"
        builder_method = getattr(self, method_name, None)

        if builder_method is not None:
            try:
                dynamic_instruction = builder_method(
                    all_days=all_days or [],
                    rag_context=rag_context,
                    profile_text=profile_text,
                    chat_history=chat_history,
                    current_day_number=current_day_number,
                    episodic_summary=episodic_summary,
                )
                sections.append(f"[工具专属生成指令]\n{dynamic_instruction}")
            except Exception as e:
                logger.warning("[PromptBuilder] Dynamic instruction failed for %s: %s", content_type, e)
                sections.append(f"[工具专属生成指令]\n{template.generation_instruction}")
        else:
            sections.append(f"[工具专属生成指令]\n{template.generation_instruction}")

        return "\n---\n".join(sections)

    def _format_learner_profile(self, profile) -> str:
        """将学习者画像格式化为可注入 prompt 的文本。"""
        if not profile:
            return ""
        lines = []
        goal = getattr(profile, "goal", "") or ""
        raw_duration = getattr(profile, "duration", None)
        level = getattr(profile, "level", "") or ""
        background = getattr(profile, "background", "") or ""
        daily_hours = getattr(profile, "dailyHours", "") or getattr(profile, "daily_hours", "") or ""

        if goal:
            lines.append(f"学习目的：{goal}")
        if raw_duration is not None and raw_duration != "":
            days = safe_parse_duration(raw_duration)
            lines.append(f"学习周期：{days} 天")
        if level:
            lines.append(f"当前水平：{level}")
        if background:
            lines.append(f"个人背景：{background}")
        if daily_hours:
            lines.append(f"每日可用时间：{daily_hours}")

        return "\n".join(lines) if lines else ""

    # ------------------------------------------------------------------
    # 辅助方法：动态指令通用逻辑
    # ------------------------------------------------------------------

    def _build_conversation_thread_principle(
        self,
        chat_history: list[dict],
        episodic_summary: str,
        principle_num: int,
        context_description: str,
    ) -> tuple[str, int]:
        """Three_Way_Branch：根据 chat_history 和 episodic_summary 的四种组合生成对话线索原则。

        Args:
            chat_history: 最近对话历史（互斥注入后可能为空列表）
            episodic_summary: episodic memory 摘要文本
            principle_num: 当前原则编号
            context_description: 工具特定的上下文描述，如 "闪卡生成范围" / "出题方向"

        Returns:
            (原则文本, 下一个 principle_num)。无对话线索时返回空字符串。
        """
        has_recent_chat = bool(chat_history)
        has_memory = bool(episodic_summary)

        if has_recent_chat and has_memory:
            text = (
                f"{principle_num}. **对话线索**：从最近对话和对话记忆摘要中提取用户提过的问题、"
                f"困惑点、感兴趣的方向，将这些线索纳入{context_description}。"
            )
            return text, principle_num + 1
        elif has_recent_chat:
            text = (
                f"{principle_num}. **聊天历史为线索**：从最近对话中提取用户提过的问题、困惑点、"
                f"感兴趣的方向，将这些线索纳入{context_description}。"
            )
            return text, principle_num + 1
        elif has_memory:
            text = (
                f"{principle_num}. **对话记忆为线索**：从对话记忆摘要中提取之前讨论过的问题、"
                f"困惑点和感兴趣的方向，将这些线索纳入{context_description}。"
            )
            return text, principle_num + 1

        # 都没有 → 不生成对话线索原则
        return "", principle_num

    def _get_learning_stage(self, all_days: list[dict]) -> str:
        """根据 completed/total 比例判断学习阶段。

        Returns:
            "no_plan" / "early" / "middle" / "late"
        """
        total = len(all_days)
        if total == 0:
            return "no_plan"
        completed_count = len([d for d in all_days if d.get("completed")])
        ratio = completed_count / total
        if ratio < 0.33:
            return "early"
        elif ratio < 0.67:
            return "middle"
        else:
            return "late"

    def _build_learning_plan_instruction(
        self,
        all_days: list[dict],
        rag_context: str,
        profile_text: str,
        chat_history: list[dict],
        current_day_number: int | None,
        episodic_summary: str = "",
    ) -> str:
        """动态拼接 learning-plan 的 generation_instruction。

        课程设计师视角：战术层面每日任务分解，与 study-guide 的战略层面互补。
        """
        parts: list[str] = []
        parts.append("请基于以下上下文，生成一份按天拆分的个性化学习计划。")

        # --- 核心原则 ---
        parts.append("\n## 核心原则\n")
        n = 1

        # 材料角色
        if rag_context:
            parts.append(
                f"{n}. **材料为骨架**：围绕提供的学习材料拆分每日任务，"
                "材料覆盖的知识点决定任务内容。不要脱离材料自由发挥。"
            )
        else:
            parts.append(
                f"{n}. **无材料模式**：当前没有学习材料，生成通用学习计划。"
                "在第一天的任务中建议用户上传材料以获得更精准的计划。"
            )
        n += 1

        # 对话线索（Three_Way_Branch）
        thread_text, n = self._build_conversation_thread_principle(
            chat_history, episodic_summary, n, "计划侧重点调整"
        )
        if thread_text:
            parts.append(thread_text)

        # 画像约束
        if profile_text:
            parts.append(
                f"{n}. **画像为约束**：根据学习者的目的、水平、"
                "可用时间调整计划的深度、节奏和任务量。"
            )
            n += 1

            # 解析画像中的具体字段做细粒度指令
            self._inject_learning_plan_profile_instructions(parts, profile_text, n)
        else:
            parts.append(
                f"{n}. **无画像模式**：当前没有学习者画像，"
                "生成 14 天的通用计划。在开头提示「建议填写学习者画像以获得个性化定制」。"
            )

        # --- 场景判断 ---
        completed_days = [d for d in all_days if d.get("completed")]
        total_days = len(all_days)

        if total_days > 0 and len(completed_days) > 0 and len(completed_days) < total_days:
            parts.append(
                f"\n## 当前场景：迭代更新（已完成 {len(completed_days)}/{total_days} 天）\n"
                "保留已完成天数的内容不变，只重新规划未完成部分。\n"
                "根据已完成天数暴露的问题调整后续任务难度和侧重。"
            )
        elif total_days > 0 and len(completed_days) == total_days:
            parts.append(
                f"\n## 当前场景：重新生成（{total_days} 天全部已完成）\n"
                "所有天数已完成，这是一次全新的计划生成。\n"
                "可以提升难度、拓展广度或深入之前的薄弱环节。"
            )
        else:
            parts.append(
                "\n## 当前场景：首次生成\n"
                "从零开始生成完整的学习计划。"
            )

        # --- 硬约束 ---
        parts.append(
            "\n## 不可违反的硬约束\n"
            "你的职责是生成可执行的每日任务清单，不要写宏观路线图或知识体系概述（那是学习指南的职责）。\n"
            "每天的 tasks 必须是具体的、可勾选的行动项，而不是抽象的学习方向。\n"
            "每天必须包含 learningObjectives（学习目标）、verificationCriteria（验证标准）和 knowledgePoints（知识点列表）。\n"
            "【输出 token 优化】输出紧凑 JSON（无缩进无换行），不要包含 methodology 和 tomorrowPreview 字段。"
        )

        return "\n".join(parts)

    def _inject_learning_plan_profile_instructions(
        self, parts: list[str], profile_text: str, start_num: int
    ) -> None:
        """从 profile_text 中提取字段，注入 learning-plan 专属的细粒度指令。"""
        n = start_num

        # duration → 周期策略
        if "学习周期" in profile_text:
            # 从 profile_text 中提取天数（格式："学习周期：X 天"）
            import re
            match = re.search(r"学习周期：(\d+)\s*天", profile_text)
            if match:
                duration = int(match.group(1))
                if duration <= 7:
                    strategy = "短周期密集模式：聚焦核心内容，每天高密度任务，不安排复习日"
                elif duration <= 14:
                    strategy = "中周期正常模式：正常节奏，可安排 1-2 个练习/复习日"
                else:
                    strategy = "长周期深入模式：含复习日、实践日和阶段性回顾"
                parts.append(
                    f"{n}. **周期策略**：{strategy}。"
                    f"你必须生成恰好 {duration} 天的计划，dayNumber 从 1 到 {duration}，不多不少。"
                )
                n += 1

        # dailyHours → 任务量（提取具体数值，约束任务粒度）
        if "每日可用时间" in profile_text:
            import re
            hours_match = re.search(r"每日可用时间：(.+?)(?:\n|$)", profile_text)
            hours_str = hours_match.group(1).strip() if hours_match else ""
            parts.append(
                f"{n}. **任务量与粒度约束**：学习者每日可用时间为「{hours_str}」。\n"
                f"   - 每天安排 2-4 个主任务，每个任务预计 30-90 分钟\n"
                f"   - 禁止拆成 15 分钟以下的碎片任务（如「精读 XX（15分钟）」这种太碎了）\n"
                f"   - 所有任务的预计时长之和应接近学习者的每日可用时间\n"
                f"   - 任务描述中不要标注具体分钟数，用任务本身的深度和广度来体现时长"
            )
            n += 1

        # level → 难度梯度
        if "当前水平" in profile_text:
            parts.append(
                f"{n}. **难度梯度**：根据学习者当前水平调整任务难度。"
                "初学者需要更多前置知识铺垫和基础练习，进阶者可以直接进入核心内容。"
            )
            n += 1

        # goal → 自由文本注入
        if "学习目的" in profile_text:
            # 提取 goal 原文
            import re
            goal_match = re.search(r"学习目的：(.+?)(?:\n|$)", profile_text)
            if goal_match:
                goal = goal_match.group(1).strip()
                parts.append(
                    f"{n}. **学习目的为导向**：学习者的目的是「{goal}」，"
                    "请根据这个目的调整内容的侧重方向、深度和实用性。"
                )

    def _build_study_guide_instruction(
        self,
        all_days: list[dict],
        rag_context: str,
        profile_text: str,
        chat_history: list[dict],
        current_day_number: int | None,
        episodic_summary: str = "",
    ) -> str:
        """动态拼接 study-guide 的 generation_instruction。

        根据上下文丰富程度（材料/画像/进度/记忆摘要）拼出明确的场景指令，
        LLM 不需要自己做条件判断。
        """
        parts: list[str] = []

        parts.append("请基于以下上下文，生成一份个性化的宏观学习路线图。")

        # --- 核心原则 ---
        parts.append("\n## 核心原则\n")

        # 材料角色
        principle_num = 1
        if rag_context:
            parts.append(
                f"{principle_num}. **材料为骨架**：路线图必须围绕提供的学习材料展开，"
                "材料覆盖的知识点是学习范围的核心。不要脱离材料自由发挥无关内容。"
            )
        else:
            parts.append(
                f"{principle_num}. **无材料模式**：当前没有学习材料，请基于学习者画像或对话主题"
                "生成通用路线图。在开头明确提示「建议上传学习材料以获得更精准的路线图」。"
            )
        principle_num += 1

        # 对话线索角色（chat_history 和 episodic_summary 联动）
        has_recent_chat = bool(chat_history)
        has_memory = bool(episodic_summary)
        if has_recent_chat and has_memory:
            parts.append(
                f"{principle_num}. **对话线索**：从最近对话和对话记忆摘要中提取用户提过的问题、"
                "困惑点、感兴趣的方向，在路线图相关知识点旁用 ⚠️ 标注，并给出针对性建议。"
            )
            principle_num += 1
        elif has_recent_chat:
            parts.append(
                f"{principle_num}. **聊天历史为线索**：从最近对话中提取用户提过的问题、困惑点、"
                "感兴趣的方向，在路线图相关知识点旁用 ⚠️ 标注，并给出针对性建议。"
            )
            principle_num += 1
        elif has_memory:
            parts.append(
                f"{principle_num}. **对话记忆为线索**：从对话记忆摘要中提取之前讨论过的问题、"
                "困惑点和感兴趣的方向，在路线图相关知识点旁用 ⚠️ 标注，并给出针对性建议。"
            )
            principle_num += 1

        # 画像角色
        if profile_text:
            parts.append(
                f"{principle_num}. **画像为约束**：根据学习者的目的、水平、"
                "可用时间调整路线图的深度、广度和节奏。"
            )
        else:
            parts.append(
                f"{principle_num}. **无画像模式**：当前没有学习者画像，"
                "生成通用深度的路线图。在开头提示「建议填写学习者画像"
                "（学习目的、当前水平、可用时间）以获得个性化定制」。"
            )

        # --- 场景判断（Python 层已判断，直接给 LLM 明确指令）---
        completed_days = [d for d in all_days if d.get("completed")]
        total_days = len(all_days)

        if total_days > 0 and len(completed_days) > 0:
            parts.append(
                f"\n## 当前场景：迭代更新（已完成 {len(completed_days)}/{total_days} 天）\n"
                "这是一次路线图更新，不是从零开始。\n"
                "- 对已完成内容做简要回顾和掌握度评估\n"
                "- 重点展开未完成部分\n"
                "- 根据学习过程中暴露的问题调整后续路线"
            )
        else:
            parts.append(
                "\n## 当前场景：首次生成\n"
                "生成完整的从零开始路线图。"
            )

        # 当前天数重点
        if current_day_number is not None:
            current_day = _find_day(all_days, current_day_number)
            if current_day and current_day.get("title"):
                parts.append(
                    f"\n当前学习进度在 Day {current_day_number}：{current_day['title']}，"
                    "请重点覆盖该主题相关的知识点。"
                )

        # --- 路线图结构要求 ---
        parts.append(
            "\n## 路线图结构要求\n"
            "路线图必须包含以下阶段（根据材料内容调整具体名称）：\n"
            "- **入门基础**：前置知识和核心概念入门\n"
            "- **核心深入**：材料的主体内容，系统性掌握\n"
            "- **进阶应用**：综合运用、项目实践或高级主题\n"
            "每个阶段必须有一个**里程碑**：明确描述「学完这个阶段后，你应该能做到什么」。"
        )

        # --- 补充资源推荐 ---
        parts.append(
            "\n## 补充资源推荐\n"
            "在路线图末尾推荐 3-5 个高质量学习资源，优先推荐：\n"
            "- 官方文档（如 Python 官方教程、React 官方文档）\n"
            "- 经典书籍（如《CSAPP》《SICP》《设计模式》等领域公认经典）\n"
            "- 知名系统性教程（如 freeCodeCamp、MIT OCW、Coursera 热门课程）\n"
            "- 权威技术博客或系列文章（如 MDN Web Docs、Real Python）\n"
            "只推荐你确信真实存在的资源，不要编造链接或虚构书名。"
        )

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Task 3: flashcards 动态指令
    # ------------------------------------------------------------------

    def _build_flashcards_instruction(
        self,
        all_days: list[dict],
        rag_context: str,
        profile_text: str,
        chat_history: list[dict],
        current_day_number: int | None,
        episodic_summary: str = "",
    ) -> str:
        """动态拼接 flashcards 的 generation_instruction。"""
        parts: list[str] = []
        parts.append("请基于以下上下文，生成 10-15 张高质量闪卡（问答对）。")

        parts.append("\n## 核心原则\n")
        n = 1

        # 对话线索
        thread_text, n = self._build_conversation_thread_principle(
            chat_history, episodic_summary, n, "闪卡生成范围（将困惑点、感兴趣的概念纳入闪卡）"
        )
        if thread_text:
            parts.append(thread_text)

        # level 难度
        if "当前水平" in profile_text:
            if "初学" in profile_text or "入门" in profile_text or "零基础" in profile_text:
                parts.append(f"{n}. **难度定位**：初学者模式——侧重定义、术语辨析和基础概念，避免高级应用题。")
            else:
                parts.append(f"{n}. **难度定位**：进阶者模式——侧重原理解释、应用场景和概念对比，减少纯定义卡。")
            n += 1

        # goal 注入
        if "学习目的" in profile_text:
            import re
            goal_match = re.search(r"学习目的：(.+?)(?:\n|$)", profile_text)
            if goal_match:
                parts.append(
                    f"{n}. **学习目的为导向**：学习者的目的是「{goal_match.group(1).strip()}」，"
                    "请根据这个目的调整内容的侧重方向、深度和实用性。"
                )
                n += 1

        # 主题聚焦
        current_day = _find_day(all_days, current_day_number)
        completed = [d for d in all_days if d.get("completed")]
        if current_day and current_day.get("title"):
            recent_titles = [current_day["title"]]
            for d in completed[-2:]:
                if d.get("title") and d["title"] != current_day["title"]:
                    recent_titles.append(d["title"])
            parts.append(
                f"\n## 主题聚焦\n"
                f"优先为以下主题生成闪卡：{', '.join(recent_titles)}。"
            )
        elif completed:
            recent_titles = [d["title"] for d in completed[-3:] if d.get("title")]
            if recent_titles:
                parts.append(f"\n## 主题聚焦\n优先为最近完成的主题生成闪卡：{', '.join(recent_titles)}。")

        # 学习阶段策略
        stage = self._get_learning_stage(all_days)
        stage_map = {
            "early": "学习初期——侧重基础概念卡：定义、术语、核心概念辨析。",
            "middle": "学习中期——侧重关联对比卡：概念间的异同、因果关系、适用场景对比。",
            "late": "学习后期——侧重综合应用卡：跨主题关联、实际应用场景、常见陷阱。",
        }
        if stage in stage_map:
            parts.append(f"\n## 学习阶段策略\n{stage_map[stage]}")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Task 4: quiz 动态指令
    # ------------------------------------------------------------------

    def _build_quiz_instruction(
        self,
        all_days: list[dict],
        rag_context: str,
        profile_text: str,
        chat_history: list[dict],
        current_day_number: int | None,
        episodic_summary: str = "",
    ) -> str:
        """动态拼接 quiz 的 generation_instruction。"""
        parts: list[str] = []
        parts.append("请基于以下上下文，生成一份阶段性综合测验。")

        parts.append("\n## 核心原则\n")
        n = 1

        # 对话线索
        thread_text, n = self._build_conversation_thread_principle(
            chat_history, episodic_summary, n, "重点出题方向（将用户困惑的知识点作为重点出题方向）"
        )
        if thread_text:
            parts.append(thread_text)

        # episodic_summary 困惑线索加权
        if episodic_summary and ("困惑" in episodic_summary or "不理解" in episodic_summary or "不懂" in episodic_summary):
            parts.append(f"{n}. **困惑点加权**：对话记忆中包含用户困惑线索，请对这些困惑点增加出题比重。")
            n += 1

        # 已完成天数 vs 全未完成
        completed = [d for d in all_days if d.get("completed")]
        if completed:
            titles = [d["title"] for d in completed if d.get("title")]
            parts.append(
                f"\n## 出题范围\n"
                f"基于已完成的 {len(completed)} 天内容出题，覆盖以下主题：{', '.join(titles)}。"
            )
        else:
            parts.append(
                "\n## 出题范围\n"
                "所有天数均未完成，基于 RAG 材料整体内容生成基础测验。"
            )

        # level 难度分布
        if "当前水平" in profile_text:
            if "初学" in profile_text or "入门" in profile_text or "零基础" in profile_text:
                parts.append(
                    "\n## 难度分布\n"
                    "初学者模式：判断题和单选题为主（约 70%），少量多选题，不出简答题。"
                )
            else:
                parts.append(
                    "\n## 难度分布\n"
                    "进阶者模式：增加多选题和简答题比重（约 40%），减少纯判断题。"
                )

        # goal 注入
        if "学习目的" in profile_text:
            import re
            goal_match = re.search(r"学习目的：(.+?)(?:\n|$)", profile_text)
            if goal_match:
                parts.append(
                    f"\n## 学习目的\n学习者的目的是「{goal_match.group(1).strip()}」，"
                    "请根据这个目的调整测验内容的侧重方向。"
                )

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Task 5: mind-map 动态指令
    # ------------------------------------------------------------------

    def _build_mind_map_instruction(
        self,
        all_days: list[dict],
        rag_context: str,
        profile_text: str,
        chat_history: list[dict],
        current_day_number: int | None,
        episodic_summary: str = "",
    ) -> str:
        """动态拼接 mind-map 的 generation_instruction。"""
        parts: list[str] = []
        parts.append("请基于以下上下文，生成一份知识结构思维导图。")

        parts.append("\n## 核心原则\n")
        n = 1

        # 对话线索
        thread_text, n = self._build_conversation_thread_principle(
            chat_history, episodic_summary, n, "知识节点标注（在用户讨论过的重点旁做标注）"
        )
        if thread_text:
            parts.append(thread_text)

        # currentDay 重点展开
        current_day = _find_day(all_days, current_day_number)
        if current_day and current_day.get("title"):
            parts.append(
                f"{n}. **当前天重点展开**：当前学习进度在 Day {current_day_number}：{current_day['title']}，"
                "请对该主题的知识节点做更深层级的展开。"
            )
            n += 1

        # goal 注入
        if "学习目的" in profile_text:
            import re
            goal_match = re.search(r"学习目的：(.+?)(?:\n|$)", profile_text)
            if goal_match:
                parts.append(
                    f"{n}. **学习目的为导向**：学习者的目的是「{goal_match.group(1).strip()}」，"
                    "请根据这个目的调整思维导图的侧重方向和广度。"
                )
                n += 1

        # level 层级深度
        if "当前水平" in profile_text:
            if "初学" in profile_text or "入门" in profile_text or "零基础" in profile_text:
                parts.append(
                    f"{n}. **层级深度**：初学者模式——结构更扁平（2-3 层），重基础概念，避免过深的细节分支。"
                )
            else:
                parts.append(
                    f"{n}. **层级深度**：进阶者模式——可以更深（3-4 层），包含原理、关联和高级概念。"
                )
            n += 1

        # 输出约束
        parts.append(
            "\n## 输出约束\n"
            "使用 Markdown 标题层级格式（# / ## / ### / -），适配 markmap.js 渲染。\n"
            "每个节点简洁有力，不要写长段落。"
        )

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Task 6: day-summary 动态指令
    # ------------------------------------------------------------------

    def _build_day_summary_instruction(
        self,
        all_days: list[dict],
        rag_context: str,
        profile_text: str,
        chat_history: list[dict],
        current_day_number: int | None,
        episodic_summary: str = "",
    ) -> str:
        """动态拼接 day-summary 的 generation_instruction。"""
        parts: list[str] = []
        parts.append("请基于以下上下文，生成当天的学习总结。")

        parts.append("\n## 核心原则\n")
        n = 1

        # 对话线索
        thread_text, n = self._build_conversation_thread_principle(
            chat_history, episodic_summary, n, "总结内容（将当天讨论过的问题和收获纳入总结）"
        )
        if thread_text:
            parts.append(thread_text)

        # AI 鼓励
        parts.append(
            f"{n}. **个性化鼓励**：根据当天完成情况生成真诚的鼓励语，"
            "肯定学习者的努力和进步，语气温暖但不浮夸。"
        )
        n += 1

        # 知识关联增强
        completed = [d for d in all_days if d.get("completed")]
        current_day = _find_day(all_days, current_day_number)
        if current_day and len(completed) > 1:
            prev_titles = [d["title"] for d in completed if d.get("title") and d.get("dayNumber") != current_day_number]
            if prev_titles:
                parts.append(
                    f"{n}. **跨天知识关联**：分析当天学习内容与之前已完成天数的知识关联，"
                    f"特别是与以下主题的关联：{', '.join(prev_titles[-3:])}。"
                    "例如「今天学的 X 概念是 Day 2 学的 Y 概念的延伸」。"
                )
                n += 1

        # 明日预告
        if all_days and current_day_number is not None:
            next_day = _find_day(all_days, current_day_number + 1)
            if next_day and next_day.get("title") and not next_day.get("completed"):
                parts.append(
                    f"{n}. **明日预告**：明天的主题是「{next_day['title']}」，"
                    "结合今天的知识关联给出预习建议。"
                )
                n += 1

        # goal 注入
        if "学习目的" in profile_text:
            import re
            goal_match = re.search(r"学习目的：(.+?)(?:\n|$)", profile_text)
            if goal_match:
                parts.append(
                    f"{n}. **学习目的为导向**：学习者的目的是「{goal_match.group(1).strip()}」，"
                    "请根据这个目的调整鼓励语的侧重方向。"
                )

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Task 7: progress-report 动态指令
    # ------------------------------------------------------------------

    def _build_progress_report_instruction(
        self,
        all_days: list[dict],
        rag_context: str,
        profile_text: str,
        chat_history: list[dict],
        current_day_number: int | None,
        episodic_summary: str = "",
    ) -> str:
        """动态拼接 progress-report 的 generation_instruction。"""
        parts: list[str] = []
        parts.append("请基于以下学习进度数据，生成一份数据驱动的学习分析报告。")

        parts.append("\n## 核心原则\n")
        n = 1

        # 对话线索
        thread_text, n = self._build_conversation_thread_principle(
            chat_history, episodic_summary, n,
            "分析报告的 weakPoints 和 nextSteps（将用户表达过的学习感受融入分析）"
        )
        if thread_text:
            parts.append(thread_text)

        # 不做 RAG
        parts.append(f"{n}. **纯数据分析**：不参考学习材料内容，仅基于 allDays 进度数据进行分析。")
        n += 1

        # allDays 为空或全未完成
        completed = [d for d in all_days if d.get("completed")]
        if not all_days or not completed:
            parts.append(
                f"\n## 当前场景：尚无学习数据\n"
                "allDays 为空或所有天数均未完成，生成最小化报告：\n"
                "- summary 中 completedDays=0\n"
                "- weakPoints 和 nextSteps 给出「开始学习」的建议\n"
                "- 不要编造任何学习行为或虚构进度"
            )
        else:
            total = len(all_days)
            parts.append(
                f"\n## 数据概览\n"
                f"已完成 {len(completed)}/{total} 天（{round(len(completed)/total*100)}%）。\n"
                "请基于此数据分析完成率趋势、薄弱环节和学习节奏。"
            )

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Task 10: quiz RAG 多次检索（Optional）
    # ------------------------------------------------------------------

    def _build_quiz_rag_context(self, all_days: list[dict]) -> str:
        """quiz 专用：每个已完成天单独检索 top-2，合并去重，上限 10 chunks。

        替代单次大 query 检索，提升多天场景下的检索精度。
        """
        if not self.rag_engine:
            return ""

        completed = [d for d in all_days if d.get("completed") and d.get("title")]
        if not completed:
            # 无已完成天 → fallback 到通用 query
            try:
                return self.rag_engine.build_context("测验 知识点", k=5)
            except Exception as e:
                logger.warning("[PromptBuilder] Quiz RAG fallback failed: %s", e)
                return ""

        seen_contents: set[str] = set()
        all_chunks = []

        for day in completed:
            try:
                chunks = self.rag_engine.retrieve(day["title"], k=2)
                for chunk in chunks:
                    # 用 content 前 200 字符做去重 key
                    dedup_key = chunk.content[:200]
                    if dedup_key not in seen_contents:
                        seen_contents.add(dedup_key)
                        all_chunks.append(chunk)
            except Exception as e:
                logger.warning("[PromptBuilder] Quiz per-day RAG failed for '%s': %s", day["title"], e)
                continue

        if not all_chunks:
            return ""

        # 按相关度排序（score 越小越相似，ChromaDB L2 距离），截断到 10
        all_chunks.sort(key=lambda c: c.score)
        top_chunks = all_chunks[:10]

        context_parts = []
        for i, chunk in enumerate(top_chunks, 1):
            source = chunk.metadata.get("source", "未知来源")
            context_parts.append(f"[来源 {i}: {source}]\n{chunk.content}")
        return "\n\n---\n\n".join(context_parts)

    def _build_rag_query(self, content_type: str, ctx) -> str:
        """根据工具类型和学习上下文构造 RAG 查询词。"""
        all_days = getattr(ctx, "allDays", None) or []
        current = getattr(ctx, "currentDayNumber", None)

        if content_type == "study-guide":
            titles = [d.get("title", "") for d in all_days if d.get("title")]
            return (" ".join(titles) + " 知识体系 学习路线") if titles else "学习指南 知识体系 学习路线"

        elif content_type == "learning-plan":
            titles = [d.get("title", "") for d in all_days if d.get("title")]
            return " ".join(titles) if titles else "学习计划 核心概念"

        elif content_type == "flashcards":
            topics: list[str] = []
            day = _find_day(all_days, current)
            if day and day.get("title"):
                topics.append(day["title"])
            completed = [d for d in all_days if d.get("completed")]
            for d in completed[-2:]:
                if d.get("title"):
                    topics.append(d["title"])
            return " ".join(topics) if topics else "闪卡 知识点"

        elif content_type == "quiz":
            completed = [d.get("title", "") for d in all_days if d.get("completed") and d.get("title")]
            return " ".join(completed) if completed else "测验 知识点"

        elif content_type == "mind-map":
            titles = [d.get("title", "") for d in all_days if d.get("title")]
            return (" ".join(titles) + " 知识结构 概念关系") if titles else "思维导图 知识结构"

        elif content_type == "day-summary":
            topics = []
            day = _find_day(all_days, current)
            if day and day.get("title"):
                topics.append(f"Day {current}: {day['title']}")
            completed = [d for d in all_days if d.get("completed")]
            for d in completed[-3:]:
                if d.get("title"):
                    topics.append(d["title"])
            return " ".join(topics) if topics else "知识总结"

        return ""
