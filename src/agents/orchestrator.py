"""
Orchestrator - 协调器

职责：
1. 意图识别（用户想做什么）
2. 模式选择（单独/协调）
3. Agent 调度
4. 状态管理
5. 进度上下文注入

双模式设计：
- 单独模式（Standalone）：用户精细控制每个 Agent
- 协调模式（Coordinated）：自动编排完整流程

意图路由优先级：create_plan > ask_question > search_resource
"""

from typing import Optional, Dict, Any, List, Generator
from enum import Enum
import json
import re

from .base import BaseAgent
from .planner import PlannerAgent
from .tutor import TutorAgent
from src.core.file_manager import FileManager
from src.core.models import SessionState, SessionMode
from src.core.progress import ProgressTracker
from src.rag import RAGEngine
from src.core.search_keywords import is_search_intent
from src.specialists.resource_searcher import ResourceSearcher


class OrchestratorMode(str, Enum):
    """协调器模式"""
    STANDALONE = "standalone"  # 单独模式
    COORDINATED = "coordinated"  # 协调模式


class OrchestratorState(str, Enum):
    """协调器状态"""
    IDLE = "idle"              # 空闲
    PLANNING = "planning"      # 规划中
    LEARNING = "learning"      # 学习中
    VALIDATING = "validating"  # 验证中
    COMPLETED = "completed"    # 已完成


class Orchestrator:
    """
    协调器
    
    统一入口，管理整个学习流程
    
    面试话术：
    > "Orchestrator 实现了两种模式：单独模式适合想精细控制的用户，
    >  协调模式适合想一键完成全流程的用户。核心思想是把'谁来做'
    >  和'怎么做'分离，协调层只负责调度，不关心具体业务逻辑。"
    """
    
    def __init__(
        self,
        mode: OrchestratorMode = OrchestratorMode.STANDALONE,
        domain: Optional[str] = None,
        on_event: Optional[Any] = None,
    ):
        """
        初始化协调器
        
        Args:
            mode: 运行模式
            domain: 学习领域
            on_event: 事件回调 (event_type, name, detail)
        """
        self.mode = mode
        self.domain = domain
        self.state = OrchestratorState.IDLE
        self.on_event = on_event
        
        # 初始化 Agents 并注入回调
        self.planner = PlannerAgent(on_event=on_event)
        self.tutor = TutorAgent(on_event=on_event)

        # 注入资源搜索器
        try:
            self.tutor.set_resource_searcher(ResourceSearcher())
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"ResourceSearcher init failed: {e}")
        
        # 文件管理器（领域确定后初始化）
        self.file_manager: Optional[FileManager] = None
        
        # RAG 引擎
        self.rag_engine: Optional[RAGEngine] = None
        
        # 会话状态
        self.session_state: Optional[SessionState] = None
        
        # 进度追踪器
        self.progress_tracker: Optional[ProgressTracker] = None

        # 意图识别缓存：相同输入不重复调用 LLM
        self._intent_cache: Dict[str, str] = {}
        self._last_intent_meta: Dict[str, str] = {"source": "init", "intent": "ask_question"}
        
        # Clarification 状态跟踪：当 _handle_create_plan 走 clarification 分支时，
        # 保存原始输入，等用户回答后自动合并上下文重新生成计划
        self._pending_clarification: Optional[str] = None  # 原始用户输入（含 URL 等）
        self._last_plan = None  # 最近生成的 LearningPlan 对象（供 UI 读取资源卡片）
    
    def set_domain(self, domain: str):
        """设置学习领域"""
        import re
        
        # Sanitize domain for filesystem safety (remove invalid chars)
        safe_domain = re.sub(r'[<>:"/\\|?*]', '', domain).strip()
        if not safe_domain:
            safe_domain = "default_domain"
            
        self.domain = safe_domain
        self.file_manager = FileManager(self.domain)
        
        # 清理 collection 名称（只保留英文、数字、下划线、点、横线）
        safe_name = re.sub(r'[^a-zA-Z0-9._-]', '', domain.replace(' ', '_'))
        if not safe_name:
            safe_name = "default"
        # 确保不以下划线开头/结尾
        safe_name = safe_name.strip('_.-')
        if len(safe_name) < 3:
            safe_name = "kb" + safe_name
        
        self.rag_engine = RAGEngine(collection_name=f"knowledge_{safe_name}")
        self.tutor.set_rag_engine(self.rag_engine)
        
        # 初始化会话状态
        self.session_state = SessionState(domain=domain)
    
    def _emit_event(self, event_type: str, name: str, detail: str = ""):
        """发射追踪事件"""
        if self.on_event:
            self.on_event(event_type, name, detail)

    def process_file(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        """
        处理上传的文件（支持 PDF / Markdown / TXT / DOCX）
        
        面试话术：
        > "process_file 是统一的文件处理入口。不管用户上传 PDF、Word 还是 Markdown，
        >  都会自动识别类型、提取内容、存入 RAG。"
        """
        self._emit_event("tool_start", "FileProcessor", f"Analyzing {filename}...")
        lower = filename.lower()

        if lower.endswith(".pdf"):
            return self._process_pdf(file_content, filename)
        elif lower.endswith(".md") or lower.endswith(".txt"):
            return self._process_text(file_content, filename)
        elif lower.endswith(".docx"):
            return self._process_docx(file_content, filename)
        else:
            self._emit_event("tool_end", "FileProcessor", f"Unsupported file type: {filename}")
            return {
                "success": False,
                "message": f"⚠️ 暂不支持 {filename} 的文件类型",
                "chunks": 0
            }

    def _process_pdf(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        """处理 PDF 文件"""
        from src.specialists.pdf_analyzer import PDFAnalyzer

        analyzer = PDFAnalyzer()
        pdf_content = analyzer.analyze_from_bytes(file_content, filename)

        chunk_count = 0
        if self.rag_engine is None:
            print(f"[Orchestrator] Auto-setting domain to: {pdf_content.title}")
            self.set_domain(pdf_content.title or "default_domain")

        if self.rag_engine:
            try:
                ids = analyzer.import_to_rag(pdf_content, self.rag_engine)
                chunk_count = len(ids)
            except (RuntimeError, Exception) as e:
                self._emit_event("tool_end", "FileProcessor", f"RAG import failed: {e}")
                return {
                    "success": False,
                    "message": f"⚠️ PDF 解析成功但向量化失败: {e}",
                    "chunks": 0
                }

        self._emit_event("tool_end", "FileProcessor", f"Successfully indexed {pdf_content.title} ({chunk_count} chunks)")

        self.tutor.set_doc_meta({
            "filename": filename,
            "title": pdf_content.title,
            "pages": pdf_content.total_pages,
            "chunks": chunk_count,
        })

        return {
            "success": True,
            "message": f"✅ 已处理 PDF: {pdf_content.title}\n- 共 {pdf_content.total_pages} 页\n- 已生成 {chunk_count} 个知识切片",
            "title": pdf_content.title,
            "pages": pdf_content.total_pages,
            "chunks": chunk_count
        }

    def _process_text(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        """处理 Markdown / TXT 文件"""
        text = file_content.decode("utf-8", errors="replace")
        title = filename.rsplit(".", 1)[0]

        # 尝试从 Markdown 提取标题
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("# "):
                title = stripped[2:].strip()
                break

        return self._import_text_to_rag(text, title, filename)

    def _process_docx(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        """处理 Word .docx 文件"""
        try:
            import docx
            import io
            doc = docx.Document(io.BytesIO(file_content))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            text = "\n".join(paragraphs)
            title = filename.rsplit(".", 1)[0]
            # 用第一个非空段落作为标题
            if paragraphs:
                title = paragraphs[0][:80]
        except ImportError:
            self._emit_event("tool_end", "FileProcessor", "python-docx not installed")
            return {
                "success": False,
                "message": "⚠️ 需要安装 python-docx 才能解析 Word 文档。\n运行: pip install python-docx",
                "chunks": 0
            }
        except Exception as e:
            self._emit_event("tool_end", "FileProcessor", f"DOCX parse error: {e}")
            return {
                "success": False,
                "message": f"⚠️ Word 文档解析失败: {e}",
                "chunks": 0
            }

        return self._import_text_to_rag(text, title, filename)

    def _import_text_to_rag(self, text: str, title: str, filename: str) -> Dict[str, Any]:
        """通用文本导入 RAG"""
        if self.rag_engine is None:
            print(f"[Orchestrator] Auto-setting domain to: {title}")
            self.set_domain(title or "default_domain")

        chunk_count = 0
        if self.rag_engine:
            metadata = {"source": title, "type": "document", "filename": filename}
            try:
                ids = self.rag_engine.add_document(text, metadata)
                chunk_count = len(ids)
            except RuntimeError as e:
                self._emit_event("tool_end", "FileProcessor", f"RAG import failed: {e}")
                return {
                    "success": False,
                    "message": str(e),
                    "chunks": 0
                }

        line_count = len(text.split("\n"))
        char_count = len(text)
        ext = filename.rsplit(".", 1)[-1].upper()

        self._emit_event("tool_end", "FileProcessor", f"Successfully indexed {title} ({chunk_count} chunks)")

        self.tutor.set_doc_meta({
            "filename": filename,
            "title": title,
            "pages": 0,
            "chunks": chunk_count,
        })

        return {
            "success": True,
            "message": f"✅ 已处理 {ext} 文档: {title}\n- 共 {line_count} 行 / {char_count} 字符\n- 已生成 {chunk_count} 个知识切片",
            "title": title,
            "pages": 0,
            "chunks": chunk_count
        }

    def run(
        self,
        user_input: str,
        history: Optional[List[Dict[str, str]]] = None,
        pre_detected_intent: Optional[str] = None,
        platforms: Optional[List[str]] = None,
        **kwargs
    ) -> str:
        """
        处理用户输入
        
        Args:
            user_input: 用户输入
            history: 对话历史
            pre_detected_intent: 预检测的意图
            platforms: 用户选择的搜索平台列表
        """
        mode_cn = "自动协调" if self.mode == OrchestratorMode.COORDINATED else "独立"
        self._emit_event("progress", "Orchestrator", f"正在以 {mode_cn} 模式启动")
        if self.mode == OrchestratorMode.COORDINATED:
            return self._run_coordinated(
                user_input,
                history=history,
                pre_detected_intent=pre_detected_intent,
                platforms=platforms,
                **kwargs
            )
        else:
            return self._run_standalone(
                user_input,
                history=history,
                pre_detected_intent=pre_detected_intent,
                platforms=platforms,
                **kwargs
            )

    def stream(
        self,
        user_input: str,
        history: Optional[List[Dict[str, str]]] = None,
        platforms: Optional[List[str]] = None,
        **kwargs
    ) -> Generator[str, None, None]:
        """
        流式处理用户输入。

        仅在 Tutor Free 问答路径启用真正流式，其它意图退化为一次性输出。
        
        Args:
            user_input: 用户输入
            history: 对话历史
            platforms: 用户选择的搜索平台列表
        """
        # 自动设置 domain（首次输入时）
        if not self.domain and user_input.strip():
            self.set_domain(user_input[:50])

        intent = self._detect_intent(user_input)
        ask_like = intent in {"ask_question", "chitchat"}

        # Standalone + 问答：直接流式
        if self.mode == OrchestratorMode.STANDALONE and ask_like:
            yield from self.tutor.stream_response(user_input, history=history, use_rag=True)
            return

        # Coordinated + 问答：IDLE 时直接进入学习问答，不自动塞计划模板
        # 但如果有 pending clarification，需要走 _run_coordinated 检查是否该生成计划
        if self.mode == OrchestratorMode.COORDINATED and ask_like:
            if self._pending_clarification:
                # 走 _run_coordinated 让 clarification 回收逻辑判断
                yield self.run(user_input, history=history, pre_detected_intent=intent, platforms=platforms, **kwargs)
                return
            if self.state == OrchestratorState.IDLE:
                self.state = OrchestratorState.LEARNING
                self._emit_event("progress", "Orchestrator", "进入学习阶段（问答优先，不自动生成计划）")
            yield from self.tutor.stream_response(user_input, history=history, use_rag=True)
            return

        # 其它路径（plan/search_resource/report）保持一次性逻辑
        yield self.run(user_input, history=history, pre_detected_intent=intent, platforms=platforms, **kwargs)

    def _run_standalone(
        self,
        user_input: str,
        history: Optional[List[Dict[str, str]]] = None,
        pre_detected_intent: Optional[str] = None,
        platforms: Optional[List[str]] = None,
        **kwargs
    ) -> str:
        """
        单独模式：根据意图调用对应 Agent
        
        路由优先级：create_plan > ask_question > search_resource
        """
        intent = pre_detected_intent or self._detect_intent(user_input)
        source = self._last_intent_meta.get("source", "unknown")
        self._emit_event("progress", "IntentDetection", f"识别到的意图: {intent} (source={source})")
        
        # 注入 ProgressTracker 上下文
        self._inject_progress_context()
        
        if intent == "create_plan":
            return self._handle_create_plan(user_input, history=history)
        elif intent == "ask_question":
            return self._handle_ask_question(user_input, history=history)
        elif intent == "search_resource":
            # 传递用户选择的平台
            user_selected = platforms is not None and len(platforms) > 0
            return self._handle_search_resource(user_input, history=history, platforms=platforms if user_selected else None)
        elif intent == "get_report":
            return self._handle_get_report()
        else:
            # 默认当作问答处理
            return self._handle_ask_question(user_input, history=history)
    
    def _run_coordinated(
        self,
        user_input: str,
        history: Optional[List[Dict[str, str]]] = None,
        pre_detected_intent: Optional[str] = None,
        platforms: Optional[List[str]] = None,
        **kwargs
    ) -> str:
        """
        协调模式：自动执行完整流程，同时响应用户意图
        """
        intent = pre_detected_intent or self._detect_intent(user_input)
        source = self._last_intent_meta.get("source", "unknown")
        self._emit_event(
            "progress",
            "IntentDetection",
            f"协调模式意图识别: {intent} (source={source}, state={self.state})"
        )

        # 注入 ProgressTracker 上下文
        self._inject_progress_context()

        # 如果用户明确提到"重新开始"或者切换了话题（简单检测）
        if self.state != OrchestratorState.IDLE and self._is_context_reset_signal(user_input):
            self.state = OrchestratorState.IDLE
            self._pending_clarification = None
            self._emit_event("progress", "Orchestrator", "已重置流程状态")

        # === Clarification 回收：如果之前在等用户回答 clarification 问题 ===
        if self._pending_clarification and intent in {"ask_question", "chitchat", "create_plan"}:
            # 用户回答了 clarification 问题，或者直接要求生成计划
            plan_trigger_keywords = [
                "生成计划", "学习计划", "生成大纲", "做一个计划", "做个计划",
                "做一个规划", "做个规划", "帮我规划", "规划一下", "给我规划",
                "给我做一个", "给我做个", "开始规划", "plan", "roadmap",
                "生成", "规划", "大纲",
            ]
            user_wants_plan_now = (
                intent == "create_plan"
                or any(kw in user_input for kw in plan_trigger_keywords)
            )

            if user_wants_plan_now:
                # 合并原始输入 + 对话历史，生成计划
                self._emit_event("progress", "Orchestrator", "Clarification 完成，合并上下文生成计划")
                original_input = self._pending_clarification
                merged_input = original_input
                if history:
                    clarification_answers = []
                    for h in history:
                        if h.get("role") == "user" and h["content"] != original_input:
                            clarification_answers.append(h["content"])
                    if clarification_answers:
                        merged_input = (
                            f"{original_input}\n\n"
                            f"用户补充信息：\n" + "\n".join(f"- {a}" for a in clarification_answers)
                        )

                self.state = OrchestratorState.PLANNING
                plan_msg = self._handle_create_plan(merged_input, history=history)
                self.state = OrchestratorState.LEARNING
                return plan_msg
            else:
                # 用户还在回答问题，继续问答模式，但保持 clarification 状态
                return self._handle_ask_question(user_input, history=history)

        # 1. 初始状态下按意图分流
        if self.state == OrchestratorState.IDLE:
            if intent == "create_plan":
                self.state = OrchestratorState.PLANNING
                self._emit_event("progress", "Orchestrator", "进入规划阶段")
                plan_msg = self._handle_create_plan(user_input, history=history)
                self.state = OrchestratorState.LEARNING
                return plan_msg

            # ask_question / chitchat：直接学习问答，不自动生成计划
            if intent in {"ask_question", "chitchat"}:
                self.state = OrchestratorState.LEARNING
                self._emit_event("progress", "Orchestrator", "进入学习阶段（问答优先，不自动生成计划）")
                return self._handle_ask_question(user_input, history=history)

        # 2. 如果已经在学习中，根据意图路由
        if intent == "search_resource":
            # 传递用户选择的平台
            user_selected = platforms is not None and len(platforms) > 0
            return self._handle_search_resource(user_input, history=history, platforms=platforms if user_selected else None)
        elif intent == "get_report":
            return self._handle_get_report()
        elif intent == "create_plan" and self.state != OrchestratorState.PLANNING:
            return self._handle_create_plan(user_input, history=history)
        else:
            # 默认：在当前背景下进行辅导
            return self._handle_ask_question(user_input, history=history)

    
    def _detect_intent(self, user_input: str) -> str:
        """
        意图识别

        策略：
        1) 优先读缓存（相同输入不重复分类）
        2) 优先关键词（省 token，响应快）
        3) 关键词无法判断时，调用 LLM 分类
        4) LLM 失败时 fallback 为 ask_question

        面试话术：
        > "意图识别使用了分层策略：缓存 + 关键词 + LLM 分类。
        >  这样既保证低延迟和低成本，又能在模糊表达时提升准确率。"
        """
        cache_key = user_input.strip().lower()
        if cache_key in self._intent_cache:
            intent = self._intent_cache[cache_key]
            self._last_intent_meta = {"source": "cache", "intent": intent}
            return intent

        keyword_intent = self._detect_intent_by_keywords(user_input)
        if keyword_intent:
            self._intent_cache[cache_key] = keyword_intent
            self._last_intent_meta = {"source": "keyword", "intent": keyword_intent}
            return keyword_intent

        llm_intent = self._detect_intent_by_llm(user_input)
        if llm_intent:
            self._intent_cache[cache_key] = llm_intent
            self._last_intent_meta = {"source": "llm", "intent": llm_intent}
            return llm_intent

        # Fallback：保守地按问答处理
        self._intent_cache[cache_key] = "ask_question"
        self._last_intent_meta = {"source": "fallback", "intent": "ask_question"}
        return "ask_question"

    def _detect_intent_by_keywords(self, user_input: str) -> Optional[str]:
        """关键词规则匹配（高置信度、低成本）
        
        优先级：create_plan > ask_question > search_resource
        """
        input_lower = user_input.lower()

        # 优先级 1: create_plan
        if any(kw in input_lower for kw in [
            "生成计划", "学习计划", "plan for", "roadmap", "学习规划", "生成大纲",
            "做一个规划", "做个规划", "帮我规划", "规划一下", "给我规划",
            "做一个计划", "做个计划", "给我做一个", "给我做个",
        ]):
            return "create_plan"
        # GitHub URL 视为"生成计划"意图（用户粘贴仓库链接，期望分析并生成计划）
        if re.match(r'https?://github\.com/', input_lower):
            return "create_plan"

        # "分析" + 文档/pdf 相关词 → 视为问答（让 tutor 基于 RAG 分析内容）
        if "分析" in input_lower:
            return "ask_question"
        # 简短的延续性输入（"继续"、"好的"、"下一步"等）→ 直接问答
        if input_lower.strip() in {"继续", "好的", "下一步", "然后呢", "接着", "go on", "continue", "next"}:
            return "ask_question"

        # 优先级 2: search_resource
        if is_search_intent(input_lower):
            return "search_resource"

        if any(kw in input_lower for kw in ["报告", "进度", "report", "progress", "总结"]):
            return "get_report"

        return None

    def _detect_intent_by_llm(self, user_input: str) -> Optional[str]:
        """LLM 分类（关键词无法覆盖时启用）"""
        prompt = (
            "请判断用户意图，并仅返回 JSON，不要输出其它内容。\n"
            "可选 intent 只有：create_plan, ask_question, search_resource, get_report, chitchat\n"
            "JSON 格式：{\"intent\": \"...\"}\n\n"
            f"用户输入：{user_input}"
        )

        try:
            raw = self.tutor.llm.simple_chat(prompt, system_prompt=(
                "你是一个意图分类器。"
                "只能输出合法 JSON。"
                "如果不确定，返回 ask_question。"
            ))
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE).strip()

            match = re.search(r"\{[\s\S]*\}", cleaned)
            if match:
                cleaned = match.group(0)

            data = json.loads(cleaned)
            intent = data.get("intent", "").strip()
            if intent in {"create_plan", "ask_question", "search_resource", "get_report", "chitchat"}:
                lowered = user_input.lower()
                # 保护策略：报告必须显式触发
                if intent == "get_report" and not any(kw in lowered for kw in ["报告", "进度", "report", "progress", "总结"]):
                    return "ask_question"
                return intent
        except Exception:
            return None

        return None


    def _is_context_reset_signal(self, user_input: str) -> bool:
        """检测是否应重置流程状态（新话题/新项目）。"""
        lowered = user_input.lower()
        if any(kw in user_input for kw in ["重新开始", "换个话题", "新课程", "新项目", "从头开始", "复现"]):
            return True
        if "github.com/" in lowered:
            return True
        return False
    
    def _extract_context_from_history(self, history: Optional[List[Dict[str, str]]] = None) -> str:
        """从对话历史中提取用户提供的学习上下文信息（URL、目标、水平等）。
        
        用于在用户说"给我做个规划"时，把之前聊天中透露的信息汇总给 Planner。
        """
        if not history:
            return ""
        
        user_msgs = [h["content"] for h in history if h.get("role") == "user"]
        if not user_msgs:
            return ""
        
        # 提取 GitHub URL
        urls = []
        for msg in user_msgs:
            url_match = re.search(r'https?://github\.com/[\w\-]+/[\w\-]+', msg)
            if url_match:
                urls.append(url_match.group(0))
        
        # 收集所有用户消息作为上下文摘要
        context_parts = []
        if urls:
            context_parts.append(f"学习目标项目: {urls[-1]}")
        
        # 把用户的所有消息拼起来（去掉太短的如"好的""继续"）
        meaningful_msgs = [m for m in user_msgs if len(m.strip()) > 3]
        if meaningful_msgs:
            context_parts.append("用户在对话中提供的信息：\n" + "\n".join(f"- {m}" for m in meaningful_msgs))
        
        return "\n".join(context_parts)

    def _inject_progress_context(self) -> None:
        """在调用 Agent 前注入 ProgressTracker 上下文到 Tutor"""
        if self.progress_tracker:
            if hasattr(self.tutor, 'set_progress_tracker'):
                self.tutor.set_progress_tracker(self.progress_tracker)

    def _handle_create_plan(self, user_input: str, history: Optional[List[Dict[str, str]]] = None) -> str:
        """处理创建计划请求
        
        如果用户输入太笼统（没有具体主题），先让 Tutor 问清楚再生成。
        当 clarification 完成后（用户回答了问题），自动合并上下文生成计划。
        """
        # 判断用户是否给了足够的信息来生成计划
        vague_patterns = [
            "学习计划", "制定计划", "生成计划", "学习规划", "生成大纲",
            "plan", "roadmap", "帮我规划", "做一个计划", "做个计划",
            "做一个规划", "做个规划", "帮我规划一下", "规划一下",
            "给我规划", "给我做一个", "给我做个",
        ]
        input_stripped = user_input.strip()
        
        # GitHub URL 也需要先问清楚学习目标
        is_github_url = bool(re.match(r'https?://github\.com/', input_stripped))
        is_vague_text = (
            len(input_stripped) <= 30
            and any(kw in input_stripped for kw in vague_patterns)
        )
        
        needs_clarification = is_vague_text or is_github_url
        
        if needs_clarification:
            # 保存原始输入，等用户回答后自动合并
            self._pending_clarification = user_input
            
            has_doc = bool(self.rag_engine)
            if is_github_url:
                proj_match = re.search(r'github\.com/[\w-]+/([\w-]+)', input_stripped)
                proj_name = proj_match.group(1) if proj_match else "该项目"
                clarify_prompt = (
                    f"用户说：「{user_input}」\n\n"
                    f"用户想学习 GitHub 项目「{proj_name}」。"
                    "请友好地询问以下信息来定制学习计划：\n"
                    "1. 学习目的是什么（面试？项目实战？兴趣？想贡献代码？）\n"
                    "2. 当前对这个领域的了解程度如何？（零基础/有一定基础/比较熟悉）\n"
                    "3. 希望多长时间完成学习？\n"
                    "请用简洁友好的语气提问，不要一次问太多（2-3 个问题即可）。"
                )
            elif has_doc:
                doc_title = ""
                if hasattr(self.tutor, 'doc_meta') and self.tutor.doc_meta:
                    doc_title = self.tutor.doc_meta.get("title", "")
                clarify_prompt = (
                    f"用户说：「{user_input}」\n\n"
                    f"用户已上传了学习资料{f'「{doc_title}」' if doc_title else ''}，想制定学习计划。"
                    "请友好地询问以下信息来定制计划：\n"
                    "1. 学习目的是什么（面试？项目实战？兴趣？）\n"
                    "2. 当前对这个主题的了解程度如何？\n"
                    "3. 希望多长时间完成学习？\n"
                    "请用简洁友好的语气提问，不要一次问太多（2-3 个问题即可）。"
                )
            else:
                clarify_prompt = (
                    f"用户说：「{user_input}」\n\n"
                    "用户想制定学习计划但没有说明具体主题。请友好地询问：\n"
                    "1. 想学什么主题/技术？\n"
                    "2. 学习目的是什么（面试？项目实战？兴趣？）\n"
                    "3. 当前水平如何？\n"
                    "4. 希望多长时间完成？\n"
                    "请用简洁友好的语气提问，不要一次问太多。"
                )
            return self.tutor.run(clarify_prompt)

        if not self.domain:
            self.set_domain(user_input[:50])
        
        # 0. 从对话历史中提取上下文（URL、学习目标、用户水平等）
        history_context = self._extract_context_from_history(history)
        
        # 1. 尝试从 RAG 获取上下文
        rag_context = ""
        if self.rag_engine:
            summary_ctx = self.rag_engine.build_context("summary overview", k=5)
            if len(user_input) >= 20:
                specific_ctx = self.rag_engine.build_context(user_input, k=3)
                if specific_ctx and specific_ctx != summary_ctx:
                    rag_context = summary_ctx + "\n\n" + specific_ctx
                else:
                    rag_context = summary_ctx
            else:
                rag_context = summary_ctx
                
        # 2. 构造输入给 Planner — 合并用户输入 + 对话历史上下文 + RAG
        planner_input = user_input
        if history_context:
            planner_input = (
                f"用户请求: {user_input}\n\n"
                f"【对话上下文】以下是用户在之前对话中提供的信息，请务必参考：\n{history_context}"
            )
        if rag_context:
            planner_input += (
                f"\n\n【重要】以下是用户上传的学习资料内容，请务必基于这些内容生成计划，"
                f"计划中的阶段和知识点必须来自资料中的实际内容：\n{rag_context}"
            )

        plan = self.planner.run(planner_input)
        
        # 清除 clarification 状态
        self._pending_clarification = None
        
        # 保存结构化计划对象（供 UI 资源卡片读取）
        self._last_plan = plan
        
        # 初始化 ProgressTracker
        if self.progress_tracker:
            self.progress_tracker.init_from_plan(plan)
            self.progress_tracker.save()
        
        # 保存计划
        if self.file_manager:
            self.file_manager.save_plan(plan.to_markdown())
        
        # 导入 RAG
        if self.rag_engine:
            self.rag_engine.add_document(
                plan.to_markdown(),
                metadata={"source": "learning_plan", "type": "plan"}
            )
        
        return f"✅ 学习计划已生成！\n\n{plan.to_markdown()}"
    
    def _handle_ask_question(self, user_input: str, history: Optional[List[Dict[str, str]]] = None) -> str:
        """处理问答请求"""
        return self.tutor.run(user_input, mode=SessionMode.FREE, history=history)
    
    def _handle_search_resource(
        self, user_input: str,
        history: Optional[List[Dict[str, str]]] = None,
        platforms: Optional[List[str]] = None,
    ) -> str:
        """处理资源搜索请求 — 直接调用 ResourceSearcher，不再绕道 TutorAgent。"""
        try:
            # 获取搜索器实例（已在 __init__ 中注入到 tutor）
            searcher = self.tutor._resource_searcher
            if not searcher:
                import logging
                logging.getLogger(__name__).warning("[Orchestrator] ResourceSearcher not available, falling back to chat")
                return self._handle_ask_question(user_input, history=history)

            # 判断用户是否主动选择了平台
            user_selected = platforms is not None and len(platforms) > 0
            results = searcher.search(user_input, platforms=platforms, user_selected=user_selected)

            # 存入 session state 供 Resources 面板展示
            self._store_search_results(results, user_input)

            # 传给 TutorAgent 生成带资源推荐的回复
            return self.tutor.run_with_resources(user_input, results, history=history)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"搜索失败: {e}")
            return self._handle_ask_question(user_input, history=history)

    def _store_search_results(self, results, query: str):
        """将搜索结果存入日志（Streamlit 已移除，此方法仅做记录）。"""
        import logging
        log = logging.getLogger(__name__)
        count = len(results) if results else 0
        log.debug(f"[Orchestrator] Search returned {count} results for query={query!r}")


    
    def _handle_get_report(self) -> str:
        """处理获取报告请求"""
        # 基于 ProgressTracker 生成简单进度报告
        if self.progress_tracker:
            summary = self.progress_tracker.get_progress_summary()
            total = summary["total_days"]
            completed = summary["completed_days"]
            pct = summary["percentage"]
            current = summary["current_day"]
            lines = [
                f"📊 学习进度报告",
                f"- 总天数: {total}",
                f"- 已完成: {completed}",
                f"- 完成率: {pct:.0%}",
            ]
            if current is not None:
                lines.append(f"- 当前进度: Day {current}")
            return "\n".join(lines)
        return "暂无学习进度数据，请先生成学习计划。"
    
    def switch_mode(self, mode: OrchestratorMode):
        """切换模式"""
        self.mode = mode
        self.state = OrchestratorState.IDLE
    
    def reset(self):
        """重置状态"""
        self.state = OrchestratorState.IDLE
        self.session_state = None
        self.domain = None
        self.file_manager = None
        self.rag_engine = None
        self.progress_tracker = None
        self.tutor.set_rag_engine(None)
        self.tutor.set_doc_meta(None)
        self._intent_cache = {}
        self._pending_clarification = None
