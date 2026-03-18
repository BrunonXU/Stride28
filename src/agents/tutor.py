"""
Tutor Agent - 教学 Agent

职责：
1. Free 模式：自由对话，回答学习问题
2. Quiz 模式：进行测验互动
3. 集成 RAG 检索，基于用户资料回答

TODO (Day 5):
- 实现完整的对话管理
- 集成 RAG 检索
- 实现流式输出
"""

import logging
from typing import Optional, List, Dict, Any, Generator

from langsmith import traceable

from src.core.models import SessionMode, Quiz
from src.rag import RAGEngine
from src.providers.base import LLMProvider, Message
from src.specialists.resource_searcher import ResourceSearcher

logger = logging.getLogger(__name__)


class TutorAgent:
    """
    教学 Agent
    
    负责与用户互动学习。
    原 BaseAgent 的 LLM 调用和事件回调逻辑已 inline 到此类中
    （BaseAgent 只有 TutorAgent 一个子类，ABC 抽象对单一子类无意义）。
    """
    
    name = "TutorAgent"
    description = "互动教学，回答问题，进行测验"
    
    _base_system_prompt = """你是一个专业的 AI 学习导师。

**首次对话规则（非常重要）**：
当对话历史为空（即学生第一次发言）时：
- 如果系统提示中包含用户已上传的文档信息，请直接基于文档内容回答学生的问题，不需要再询问学习目标。
- 如果没有文档上下文，不要直接开始教学。你应该：
  1. 简短友好地回应学生提到的主题（用学生自己的话，不要编造主题）
  2. 询问学生的学习目的（为了面试？项目实战？还是纯兴趣了解？）
  3. 询问学生当前的技术水平（零基础？有一定基础？还是想深入？）
  4. 根据学生的回答再开始针对性教学

**后续对话规则**：
当对话历史不为空时，正常进行教学，不需要再次询问目标。

你的教学风格是：
- 耐心、友好、鼓励式教学
- 用简单易懂的语言解释复杂概念
- 善用类比和实例
- 循序渐进，由浅入深
- 鼓励学生思考，而不是直接给答案

当回答问题时：
1. 先确认理解学生的问题
2. 给出清晰的解释
3. 必要时提供示例
4. 检查学生是否理解
5. 鼓励提出更多问题

如果有相关的学习资料作为参考，请基于这些资料回答，并在适当时引用来源。

**重要风格要求（严格执行）**：
绝对不要在回复中使用任何 emoji 表情符号（如 😊、🤖、📝 等）。请始终坚守专业、严谨、简洁的学术解答风格。不要有任何卖萌或多余的情感符号。"""

    @property
    def system_prompt(self) -> str:
        from datetime import datetime
        now = datetime.now()
        weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        time_str = f"{now.strftime('%Y年%m月%d日 %H:%M:%S')} {weekdays[now.weekday()]}"
        return f"【系统提示：当前真实时间是 {time_str}】\n\n" + self._base_system_prompt
    
    def __init__(self, llm_provider: LLMProvider, config: Optional[Dict[str, Any]] = None, on_event=None):
        self.llm = llm_provider
        self.config = config or {}
        self.on_event = on_event
        self.rag_engine: Optional[RAGEngine] = None
        self.current_mode = SessionMode.FREE
        self.current_quiz: Optional[Quiz] = None
        self.quiz_progress = 0
        # 文档元信息：让 tutor 知道用户上传了什么文件
        self.doc_meta: Optional[Dict[str, Any]] = None  # {"filename": "xxx.pdf", "title": "...", "chunks": 270}
        # 资源搜索器（可选注入）
        self._resource_searcher: Optional[ResourceSearcher] = None
        # 当前回复的来源追踪列表
        self._current_sources: List[Dict[str, Any]] = []
    
    def _emit_event(self, event_type: str, name: str, detail: str = ""):
        """事件回调（原 BaseAgent 方法）"""
        if self.on_event:
            try:
                self.on_event(event_type, name, detail)
            except Exception:
                pass

    def _call_llm(self, prompt: str, system_prompt: Optional[str] = None, max_tokens: Optional[int] = None) -> str:
        """便捷 LLM 调用封装（原 BaseAgent 方法）"""
        return self.llm.simple_chat(prompt, system_prompt=system_prompt, max_tokens=max_tokens)

    def set_rag_engine(self, rag_engine: Optional[RAGEngine]):
        """设置 RAG 引擎"""
        self.rag_engine = rag_engine
    
    def set_doc_meta(self, meta: Optional[Dict[str, Any]]):
        """设置已上传文档的元信息，让 tutor 在回答时知道用户有文档"""
        self.doc_meta = meta

    def set_resource_searcher(self, searcher: ResourceSearcher):
        """设置资源搜索器"""
        self._resource_searcher = searcher

    @traceable(name="tutor.generate")
    def generate(self, prompt: str, system_prompt: Optional[str] = None, max_tokens: Optional[int] = None) -> str:
        """纯 LLM 调用，不做任何 prompt 加工。供 PromptBuilder 等外部模块使用。"""
        return self._call_llm(prompt, system_prompt=system_prompt, max_tokens=max_tokens)


    def _reset_sources(self):
        """重置当前回复的来源追踪列表"""
        self._current_sources = []

    def _track_source(self, source: Dict[str, Any]):
        """记录一条来源信息"""
        self._current_sources.append(source)


    @traceable(name="tutor.run")
    def run(
        self,
        user_input: str,
        mode: SessionMode = SessionMode.FREE,
        history: Optional[List[Dict[str, str]]] = None,
        use_rag: bool = True,
        **kwargs
    ) -> str:
        """
        处理用户输入
        
        Args:
            user_input: 用户输入
            mode: 会话模式（FREE/QUIZ）
            history: 对话历史
            use_rag: 是否使用 RAG 检索
            
        Returns:
            回复内容
        """
        self.current_mode = mode
        
        if mode == SessionMode.QUIZ:
            return self._handle_quiz_mode(user_input)
        else:
            return self._handle_free_mode(user_input, history, use_rag)

    def run_with_resources(
        self,
        user_input: str,
        search_results: list,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """处理带搜索结果的用户输入，生成包含资源推荐的回复。

        在搜索完成后调用，将搜索结果注入回复。
        """
        self._reset_sources()

        # 记录搜索来源
        if search_results:
            platforms = list({r.platform for r in search_results})
            self._track_source({
                "type": "search",
                "platforms": platforms,
                "query": user_input,
            })

        prompt = self._build_free_mode_prompt(user_input, history=history, use_rag=True)
        self._emit_event("progress", self.name, "Generating tutor response...")
        response = self._call_llm(prompt)
        self._emit_event("progress", self.name, "Response generated.")

        # 附加搜索结果
        if search_results:
            resource_text = "\n\n🔍 推荐资源：\n"
            for r in search_results:
                resource_text += f"- [{r.title}]({r.url}) ({r.platform})\n"
            response += resource_text

        # 追加参考来源
        response += self._build_reference_section(self._current_sources)

        return response

    
    def _handle_free_mode(
        self,
        user_input: str,
        history: Optional[List[Dict[str, str]]] = None,
        use_rag: bool = True,
    ) -> str:
        """处理自由对话模式，回复末尾追加参考来源区块"""
        # 重置来源追踪
        self._reset_sources()

        prompt = self._build_free_mode_prompt(user_input, history=history, use_rag=use_rag)
        self._emit_event("progress", self.name, "Generating tutor response...")
        response = self._call_llm(prompt)
        self._emit_event("progress", self.name, "Response generated.")

        # 追加参考来源区块
        reference_section = self._build_reference_section(self._current_sources)
        response += reference_section

        return response
    def _build_reference_section(self, sources: list) -> str:
        """
        构建「📎 参考来源」区块

        Args:
            sources: 来源列表，每项为 dict，包含 type（pdf/search/rag/ai）和详情
                - pdf: {"type": "pdf", "filename": "...", "section": "..."}
                - search: {"type": "search", "platforms": [...], "query": "..."}
                - rag: {"type": "rag", "source": "..."}

        Returns:
            格式化的参考来源文本
        """
        if not sources:
            return "\n\n📎 参考来源\n- 基于 AI 通用知识"

        lines = ["\n\n📎 参考来源"]
        for src in sources:
            src_type = src.get("type", "")
            if src_type == "pdf":
                lines.append(f"- PDF: {src.get('filename', '未知文件')}, {src.get('section', '未知章节')}")
            elif src_type == "search":
                platforms = src.get("platforms", [])
                query = src.get("query", "")
                lines.append(f"- 搜索: {', '.join(platforms)} (关键词: \"{query}\")")
            elif src_type == "rag":
                lines.append(f"- RAG: 检索片段来自 {src.get('source', '未知来源')}")
        return "\n".join(lines)


    def _build_free_mode_prompt(
        self,
        user_input: str,
        history: Optional[List[Dict[str, str]]] = None,
        use_rag: bool = True,
        episodic_summary: Optional[str] = None,
    ) -> str:
        """构建 Free 模式 Prompt，供普通调用和流式调用复用。
        
        历史注入策略（滑动窗口 + 摘要压缩）：
        - 最近 2 轮（4 条消息）：完整保留，保证指代词理解
        - 更早的历史：只保留用户消息的前 80 字作为话题摘要，丢弃冗长的 assistant 回复
        - 总共最多回溯 8 轮，避免 token 爆炸
        """
        # 1. 构建对话历史文本（滑动窗口 + 摘要压缩）
        history_text = ""
        if history:
            max_rounds = 16  # 最多 16 条消息（约 8 轮）
            recent_full = 4   # 最近 4 条消息完整保留（约 2 轮）
            
            selected = history[-max_rounds:]
            parts = []
            
            for i, h in enumerate(selected):
                role_label = "学生" if h.get("role") == "user" else "导师"
                content = h.get("content", "")
                
                # 最近 recent_full 条完整保留
                if i >= len(selected) - recent_full:
                    # 但 assistant 回复也做长度限制，避免单条超长
                    if h.get("role") == "assistant" and len(content) > 500:
                        content = content[:500] + "...（回复已截断）"
                    parts.append(f"{role_label}: {content}")
                else:
                    # 较早的历史：用户消息保留前 80 字，assistant 只保留一句话摘要
                    if h.get("role") == "user":
                        summary = content[:80] + ("..." if len(content) > 80 else "")
                        parts.append(f"{role_label}: {summary}")
                    else:
                        # assistant 回复只取第一行或前 60 字
                        first_line = content.split("\n")[0][:60]
                        parts.append(f"{role_label}: {first_line}...")
            
            history_text = "\n".join(parts)

        # 2. RAG 检索上下文
        context = ""
        if use_rag and self.rag_engine:
            self._emit_event("tool_start", self.name, f"Retrieving context for: {user_input[:50]}...")

            query = user_input
            # 当用户输入很短（如"分析""继续"）且有文档时，扩展为全局概述查询
            is_short_doc_request = (
                self.doc_meta
                and len(user_input.strip()) <= 10
                and any(kw in user_input for kw in ["分析", "概述", "总结", "介绍", "看看", "继续"])
            )
            if is_short_doc_request:
                doc_title = self.doc_meta.get("title") or ""
                query = f"{doc_title} summary introduction overview abstract table of contents structure"
            elif any(kw in user_input for kw in ["paper", "document", "this", "论文", "文档", "这", "它"]):
                query += " summary introduction overview abstract"
                if history:
                    last_assistant = [h for h in history if h.get("role") == "assistant"]
                    if last_assistant:
                        query += " " + last_assistant[-1].get("content", "")[:100]

            context = self.rag_engine.build_context(query, k=5)

            self._emit_event("progress", self.name, f"Retrieved {len(context)//100 if context else 0} context chunks")
            self._emit_event("tool_end", self.name, "Context retrieval complete")

            # 来源追踪：记录 RAG 检索结果
            if context:
                if self.doc_meta:
                    # RAG 内容来自用户上传的 PDF
                    self._track_source({
                        "type": "pdf",
                        "filename": self.doc_meta.get("filename", "未知文件"),
                        "section": self.doc_meta.get("title", "相关章节"),
                    })
                else:
                    # RAG 内容来自其他文档
                    self._track_source({
                        "type": "rag",
                        "source": "RAG 知识库",
                    })

        # 3. 组装 prompt（历史 + 上下文 + 当前问题）
        prompt_parts = []

        # 注入 Episodic Memory 摘要（对话历史之前，帮助 LLM 理解学习者背景）
        if episodic_summary:
            prompt_parts.append(
                f"[对话记忆摘要：以下是之前对话的压缩摘要，帮助你理解学习者的背景]\n{episodic_summary}"
            )

        # 首次对话标记：让 LLM 知道是否需要先询问学习目标
        # 但如果有文档上下文（用户上传了 PDF），直接基于文档回答，不问学习目标
        # 有 episodic_summary 说明之前有过对话（只是被清空了），不算首次
        if not history_text and not episodic_summary and not (self.doc_meta and context):
            prompt_parts.append("[系统提示：这是学生的第一条消息，请按照首次对话规则回复，先了解学习目的和水平。]")

        # 文档上下文提示：让 LLM 明确知道用户已上传文档，RAG 内容就是文档内容
        if self.doc_meta and context:
            doc_name = self.doc_meta.get("filename") or self.doc_meta.get("title") or "文档"
            doc_title = self.doc_meta.get("title") or doc_name
            chunks = self.doc_meta.get("chunks", 0)
            pages = self.doc_meta.get("pages", 0)
            hint = (
                f"[系统提示：用户已上传文档 [{doc_title}]（{doc_name}，{pages}页，{chunks} 个知识切片）。"
                f"下方的参考资料全部来自该文档。当用户提到'这个pdf''这个文档''分析''继续'等，"
                f"都是在指这份文档。请直接基于参考资料内容回答，不要说'没有PDF'或'没有文档'。"
            )
            # 如果用户请求"分析"且没有更具体的问题，引导给出文档概述
            if any(kw in user_input for kw in ["分析", "概述", "总结", "介绍", "看看"]) and len(user_input.strip()) <= 15:
                hint += (
                    "\n用户希望了解这份文档的整体内容。请给出结构化的文档概述，包括："
                    "1) 文档的主题和目的 2) 主要章节/模块 3) 核心概念和关键术语 4) 文档的适用场景。"
                )
            hint += "]"
            prompt_parts.append(hint)

        if history_text:
            prompt_parts.append(f"以下是之前的对话记录，请注意理解上下文指代关系：\n\n{history_text}\n")
        if context:
            prompt_parts.append(f"参考以下学习资料回答问题：\n\n{context}\n")
        prompt_parts.append(f"学生最新问题：{user_input}")
        if context:
            prompt_parts.append("\n请基于以上资料和对话历史回答，如果资料中没有相关信息，可以结合你的知识补充。")

        return "\n---\n".join(prompt_parts) if len(prompt_parts) > 1 else prompt_parts[0]
    
    def _handle_quiz_mode(self, user_input: str) -> str:
        """处理测验模式"""
        if self.current_quiz is None:
            return "当前没有进行中的测验。请先开始一个新测验。"
        
        if self.quiz_progress >= len(self.current_quiz.questions):
            return "测验已完成！请查看测验结果。"
        
        # 获取当前题目
        current_question = self.current_quiz.questions[self.quiz_progress]
        
        # 检查答案
        is_correct = user_input.strip().upper() == current_question.correct_answer.strip().upper()
        
        # 构建反馈
        if is_correct:
            feedback = "✅ 回答正确！\n\n"
        else:
            feedback = f"❌ 回答错误。正确答案是：{current_question.correct_answer}\n\n"
        
        if current_question.explanation:
            feedback += f"💡 解析：{current_question.explanation}\n\n"
        
        # 进入下一题
        self.quiz_progress += 1
        
        if self.quiz_progress < len(self.current_quiz.questions):
            next_question = self.current_quiz.questions[self.quiz_progress]
            feedback += f"---\n\n**题目 {self.quiz_progress + 1}**: {next_question.question}\n\n"
            if next_question.options:
                for i, opt in enumerate(next_question.options):
                    feedback += f"{chr(65+i)}. {opt}\n"
        else:
            feedback += "🎉 测验完成！"
        
        return feedback
    
    def start_quiz(self, quiz: Quiz) -> str:
        """开始测验"""
        self.current_quiz = quiz
        self.quiz_progress = 0
        self.current_mode = SessionMode.QUIZ
        
        if not quiz.questions:
            return "测验题目为空。"
        
        # 返回第一题
        first_question = quiz.questions[0]
        response = f"📝 **开始测验：{quiz.topic}**\n\n"
        response += f"共 {len(quiz.questions)} 道题目\n\n"
        response += f"---\n\n**题目 1**: {first_question.question}\n\n"
        
        if first_question.options:
            for i, opt in enumerate(first_question.options):
                response += f"{chr(65+i)}. {opt}\n"
        
        return response
    
    @traceable(name="tutor.stream_response")
    def stream_response(
        self,
        user_input: str,
        history: Optional[List[Dict[str, str]]] = None,
        use_rag: bool = True,
        material_context: Optional[str] = None,
        episodic_summary: Optional[str] = None,
    ) -> Generator[str, None, None]:
        """
        流式输出回复

        Args:
            material_context: 用户附加材料的文本上下文（可选）
            episodic_summary: Episodic Memory 摘要文本（可选）
        """
        prompt = self._build_free_mode_prompt(user_input, history=history, use_rag=use_rag, episodic_summary=episodic_summary)

        # 注入用户附加的材料上下文（放在 prompt 末尾、紧贴用户问题，确保 LLM 优先关注）
        if material_context:
            instruction = (
                "\n\n---\n\n"
                "[重要：用户已将以下学习材料附加到本次对话中。"
                "请忽略之前对话中讨论的其他文件，仅基于以下附加材料回答当前问题。"
                "当用户提到'这个文件''这个材料''这是什么'等指代词时，就是在指这些附加材料。]\n\n"
            )
            prompt = prompt + instruction + material_context

        self._emit_event("progress", self.name, "Generating tutor response (streaming)...")

        messages = [
            Message(role="system", content=self.system_prompt),
            Message(role="user", content=prompt),
        ]

        try:
            for chunk in self.llm.stream(messages):
                if chunk:
                    yield chunk
        except Exception:
            # 流式失败时自动回退到非流式，保证稳定性
            fallback = self._call_llm(prompt)
            if fallback:
                yield fallback
        finally:
            self._emit_event("progress", self.name, "Streaming response complete.")
    
    def answer(
        self,
        question: str,
        rag_engine: Optional[RAGEngine] = None,
        k: int = 3,
    ) -> str:
        """
        RAG 增强问答（便捷方法）
        
        这是 TutorAgent 最常用的方法，整合了 RAG 检索和 LLM 问答。
        
        Args:
            question: 用户问题
            rag_engine: RAG 引擎（可选，使用已设置的）
            k: 检索结果数量
            
        Returns:
            回答内容
            
        面试话术：
        > "answer() 是 TutorAgent 的核心方法。先从 RAG 检索相关内容，
        >  然后把内容注入 Prompt 让 LLM 回答。这样既能利用 LLM 推理，
        >  又能基于用户资料给出个性化回答。"
        
        使用示例：
            tutor = TutorAgent(llm_provider=llm)
            tutor.set_rag_engine(rag_engine)
            answer = tutor.answer("什么是 Self-Attention?")
        """
        # 使用传入的或已设置的 RAG 引擎
        engine = rag_engine or self.rag_engine
        
        if engine:
            self.rag_engine = engine
        
        return self.run(question, use_rag=(engine is not None))

