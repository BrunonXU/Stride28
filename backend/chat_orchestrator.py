"""
ChatOrchestrator — 基于 LangGraph StateGraph 的聊天编排器

核心职责：
1. 构建并编译 StateGraph（classify_intent → conditional → tutor_node | search_node → synthesis_node）
2. 提供 async def run(state, config) 入口
3. 内部 IntentClassifier（LLM 意图分类）
4. 暴露编译后的图对象用于可视化和测试

生命周期：
- 每次请求新建 ChatOrchestrator（轻量，<1ms）
- 底层 TutorAgent / SearchOrchestrator / LLMProvider 通过 session 缓存复用

设计决策参考：.kiro/specs/langgraph-chat-orchestrator/design.md
"""

import asyncio
import json
import logging
from typing import List, Optional, TYPE_CHECKING

from langgraph.graph import StateGraph, END
from langchain_core.runnables import RunnableConfig
from typing_extensions import TypedDict

if TYPE_CHECKING:
    from src.agents.tutor import TutorAgent
    from src.agents.episodic_memory import EpisodicMemory
    from src.providers.base import LLMProvider
    from src.specialists.search_orchestrator import SearchOrchestrator

logger = logging.getLogger(__name__)


# ============================================
# State 定义
# ============================================

class IntentResult(TypedDict):
    """意图分类结果"""
    label: str        # "normal_chat" | "search_needed"
    confidence: float  # 0.0 ~ 1.0
    platforms: Optional[List[str]]  # 用户指定的平台，None 表示全平台


class SearchResultItem(TypedDict):
    """搜索结果条目"""
    title: str
    url: str
    platform: str
    description: str
    score: float


class ChatState(TypedDict):
    """LangGraph 图状态，在节点间传递。

    注意：emit 回调不在 ChatState 中！
    通过 RunnableConfig.configurable["emit"] 传递，避免序列化问题（决策 10）。
    """
    # 输入（由 chat.py 填充）
    user_message: str
    history: List[dict]
    plan_id: str
    material_ids: Optional[List[str]]

    # 意图分类（classify_intent 填充）
    intent: Optional[IntentResult]

    # 用户指定的搜索平台（classify_intent 提取）
    target_platforms: Optional[List[str]]

    # 搜索分支（search_node 填充）
    search_query: Optional[str]
    search_results: Optional[List[SearchResultItem]]

    # 输出（tutor_node / synthesis_node 填充）
    response_chunks: List[str]
    sources: Optional[List[dict]]

    # 错误
    error: Optional[str]


# ============================================
# 辅助函数
# ============================================

def _get_emit(config: RunnableConfig):
    """从 RunnableConfig 中安全获取 emit 回调"""
    configurable = config.get("configurable", {})
    return configurable.get("emit")


def _route_by_intent(state: ChatState) -> str:
    """conditional edge 路由函数：根据意图标签决定下一个节点"""
    intent = state.get("intent")
    if intent and intent.get("label") == "search_needed":
        return "search_node"
    return "tutor_node"


# ============================================
# ChatOrchestrator
# ============================================

class ChatOrchestrator:
    """基于 LangGraph StateGraph 的聊天编排器。

    图结构：
        __start__ → classify_intent → conditional → tutor_node | search_node → synthesis_node → __end__

    所有外部依赖通过构造函数注入，支持 mock 测试。
    """

    def __init__(
        self,
        tutor_agent: "TutorAgent",
        search_orchestrator: "SearchOrchestrator",
        llm_provider: "LLMProvider",
        episodic_memory: Optional["EpisodicMemory"] = None,
    ):
        self._tutor = tutor_agent
        self._search = search_orchestrator
        self._llm = llm_provider
        self._episodic = episodic_memory
        self._graph = self._build_graph()

    def _build_graph(self):
        """构建并编译 StateGraph"""
        graph = StateGraph(ChatState)

        # 注册节点（绑定 self，让节点方法能访问依赖）
        graph.add_node("classify_intent", self._classify_intent_node)
        graph.add_node("tutor_node", self._tutor_node)
        graph.add_node("search_node", self._search_node)
        graph.add_node("synthesis_node", self._synthesis_node)

        # 边
        graph.set_entry_point("classify_intent")
        graph.add_conditional_edges(
            "classify_intent",
            _route_by_intent,
            {"tutor_node": "tutor_node", "search_node": "search_node"},
        )
        graph.add_edge("tutor_node", END)
        graph.add_edge("search_node", "synthesis_node")
        graph.add_edge("synthesis_node", END)

        return graph.compile()

    # ------------------------------------------
    # 节点方法（Task 3~6 实现，当前为 pass 骨架）
    # ------------------------------------------

    async def _classify_intent_node(self, state: ChatState, config: RunnableConfig) -> dict:
        """LLM 意图分类节点。

        - 使用 LLMProvider.simple_chat()（sync）通过 asyncio.to_thread 调用
        - 输入：user_message + history（最多 12 条）
        - 输出：IntentResult {label, confidence}
        - 降级：LLM 调用失败 → 默认 normal_chat + confidence=0.0
        """
        emit = _get_emit(config)
        if emit:
            await emit({"type": "status", "node": "classify", "message": "正在分析意图..."})

        user_msg = state["user_message"]
        history = state.get("history") or []

        # 构建意图分类 prompt
        history_text = ""
        if history:
            recent = history[-6:]  # 最近 3 轮
            history_text = "\n".join(
                f"{'用户' if h.get('role') == 'user' else 'AI'}: {h.get('content', '')[:100]}"
                for h in recent
            )
            history_text = f"\n最近对话：\n{history_text}\n"

        # 可用平台列表（用于 prompt 中告知 LLM）
        try:
            from src.specialists.platform_configs import PLATFORM_CONFIGS
            available_platforms = list(PLATFORM_CONFIGS.keys())
        except Exception:
            available_platforms = ["bilibili", "zhihu", "xiaohongshu", "youtube", "github", "google", "wechat"]

        platform_list_str = "、".join(available_platforms)

        prompt = (
            f"{history_text}"
            f"当前用户消息：{user_msg}\n\n"
            f"判断用户意图：\n"
            f"1. 如果用户想搜索资源、查找教程、寻找学习材料，输出 search_needed\n"
            f"2. 如果是普通聊天、提问、讨论，输出 normal_chat\n"
            f'3. 如果用户指定了搜索平台（如"搜小红书""在B站找"），在 platforms 中列出\n'
            f"可用平台：{platform_list_str}\n"
            f"平台别名映射：小红书=xiaohongshu, B站/哔哩哔哩=bilibili, 知乎=zhihu, 谷歌=google, 微信=wechat"
        )

        try:
            raw = await asyncio.to_thread(
                self._llm.simple_chat,
                prompt,
                system_prompt=(
                    '你是意图分类器。只输出 JSON，不要其他内容。\n'
                    '格式：{"intent": "normal_chat"|"search_needed", "confidence": 0.0~1.0, '
                    '"platforms": ["平台名"] 或 null}\n'
                    '如果用户没有指定平台，platforms 为 null。\n'
                    '如果用户指定了平台，platforms 只包含用户指定的平台（用英文 key）。'
                ),
            )
            # 尝试解析 JSON（兼容 LLM 可能输出的 markdown code block）
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            result = json.loads(cleaned)
            label = result.get("intent", "normal_chat")
            if label not in ("normal_chat", "search_needed"):
                label = "normal_chat"
            confidence = max(0.0, min(1.0, float(result.get("confidence", 0.5))))

            # 提取用户指定的平台
            raw_platforms = result.get("platforms")
            target_platforms = None
            if raw_platforms and isinstance(raw_platforms, list):
                valid = [p for p in raw_platforms if p in available_platforms]
                if valid:
                    target_platforms = valid

            return {
                "intent": {"label": label, "confidence": confidence, "platforms": target_platforms},
                "target_platforms": target_platforms,
            }
        except Exception as e:
            logger.warning(f"意图分类失败，降级为 normal_chat: {e}")
            return {
                "intent": {"label": "normal_chat", "confidence": 0.0, "platforms": None},
                "target_platforms": None,
            }

    async def _tutor_node(self, state: ChatState, config: RunnableConfig) -> dict:
        """普通对话节点：封装 TutorAgent.stream_response()。

        关键设计：真实逐 chunk 流式推送
        - sync generator 在子线程中运行
        - 每产生一个 chunk，通过 asyncio.run_coroutine_threadsafe 实时推送到 async 侧
        - 用户看到的是逐字流式输出，不是等全部生成后批量推送
        """
        emit = _get_emit(config)
        if emit:
            await emit({"type": "status", "node": "tutor", "message": "正在思考..."})

        plan_id = state["plan_id"]
        material_ids = state.get("material_ids") or []

        # 材料上下文构建（复用 chat.py 的 _build_material_context）
        material_context = ""
        if material_ids:
            from backend.routers.chat import _build_material_context
            material_context = await asyncio.to_thread(
                _build_material_context, plan_id, material_ids, state["user_message"]
            )

        # Episodic Memory 检查 + 注入（保持与现有 chat.py 一致）
        episodic_summary = None
        if self._episodic:
            try:
                should = await asyncio.to_thread(self._episodic.should_trigger, plan_id)
                if should:
                    asyncio.create_task(self._episodic.trigger_background_summary(plan_id))
                episodic_summary = await asyncio.to_thread(
                    self._episodic.get_injectable_summary, plan_id
                )
            except Exception as e:
                logger.warning(f"Episodic Memory 失败: {e}")

        # 在子线程中消费 sync generator，逐 chunk 实时推送
        chunks: List[str] = []
        loop = asyncio.get_running_loop()

        def _stream_with_realtime_emit():
            """在子线程中运行，逐 chunk 通过 run_coroutine_threadsafe 推送到 async 侧"""
            for chunk in self._tutor.stream_response(
                user_input=state["user_message"],
                history=state["history"],
                use_rag=False,
                material_context=material_context if material_context else None,
                episodic_summary=episodic_summary,
            ):
                if chunk:
                    chunks.append(chunk)
                    if emit:
                        future = asyncio.run_coroutine_threadsafe(
                            emit({"type": "chunk", "content": chunk}), loop
                        )
                        future.result(timeout=5)  # 背压控制

        await asyncio.to_thread(_stream_with_realtime_emit)

        # 推送 sources 事件（保持与现有 chat.py 一致）
        sources = []
        try:
            raw_sources = self._tutor._current_sources
            if raw_sources:
                sources = [
                    {
                        "materialId": s.get("filename", s.get("source", "unknown")),
                        "materialName": s.get("filename", s.get("source", "来源")),
                        "snippet": s.get("section", s.get("query", "")),
                    }
                    for s in raw_sources
                ]
                if emit:
                    await emit({"type": "sources", "sources": sources})
        except Exception:
            pass

        return {"response_chunks": chunks, "sources": sources}

    async def _search_node(self, state: ChatState, config: RunnableConfig) -> dict:
        """搜索节点：LLM 提取关键词 + SearchOrchestrator.search_all_platforms_stream 搜索。

        使用与正常搜索面板完全相同的 stream 路径（SlotAllocator + EngagementRanker + PipelineExecutor），
        消费 async generator 事件，实时推送搜索进度到前端。
        """
        emit = _get_emit(config)
        if emit:
            await emit({"type": "status", "node": "search", "message": "正在搜索相关资源..."})

        # 1. LLM 提取搜索关键词（排除平台名）
        try:
            keyword_prompt = (
                f"从以下用户消息中提取搜索关键词（只输出关键词，不要其他内容）：\n"
                f"用户消息：{state['user_message']}\n\n"
                f"注意：去掉平台名称（如小红书、B站、知乎、YouTube、Google、微信、GitHub），只保留实际搜索内容。"
            )
            search_query = await asyncio.to_thread(
                self._llm.simple_chat,
                keyword_prompt,
                system_prompt="你是关键词提取器。只输出搜索关键词，不超过 10 个字。不要包含平台名称。",
            )
            search_query = search_query.strip()
            logger.info(f"LLM 提取关键词: '{search_query}'（原始消息: '{state['user_message'][:50]}'）")
        except Exception as e:
            logger.warning(f"关键词提取失败，使用原始消息: {e}")
            search_query = state["user_message"][:50]

        # 2. 确定搜索平台：优先使用用户指定的平台，否则全平台
        target_platforms = state.get("target_platforms")
        try:
            from src.specialists.platform_configs import PLATFORM_CONFIGS
            all_platforms = list(PLATFORM_CONFIGS.keys())
        except Exception:
            all_platforms = ["bilibili", "zhihu", "xiaohongshu", "youtube", "github", "google", "wechat"]

        if target_platforms and len(target_platforms) > 0:
            platforms = [p for p in target_platforms if p in all_platforms]
            if not platforms:
                platforms = all_platforms
            logger.info(f"使用用户指定平台: {platforms}")
        else:
            platforms = all_platforms

        # 3. 使用 search_all_platforms_stream（与正常搜索面板同一路径）
        search_items = []
        try:
            async for event in self._search.search_all_platforms_stream(
                query=search_query,
                platforms=platforms,
                top_k=10,
            ):
                stage = event.get("stage", "")

                if stage == "searching" and emit:
                    await emit({"type": "status", "node": "search", "stage": "searching", "message": event.get("message", "搜索中...")})

                elif stage == "filtering" and emit:
                    await emit({"type": "status", "node": "search", "stage": "filtering", "message": event.get("message", "初筛中...")})

                elif stage == "extracting" and emit:
                    await emit({"type": "status", "node": "search", "stage": "extracting", "message": event.get("message", "提取详情...")})

                elif stage == "evaluating" and emit:
                    await emit({"type": "status", "node": "search", "stage": "evaluating", "message": event.get("message", "AI 评估中...")})

                elif stage == "done":
                    raw_results = event.get("results", [])
                    search_items = [
                        {
                            "title": r.get("title", ""),
                            "url": r.get("url", ""),
                            "platform": r.get("platform", ""),
                            "description": r.get("description", ""),
                            "score": r.get("quality_score", 0.0),
                            "contentSummary": r.get("content_summary", ""),
                            "contentText": r.get("content_text", ""),
                            "commentSummary": r.get("comment_summary", ""),
                            "commentsPreview": r.get("comments_preview", []),
                            "imageUrls": r.get("image_urls", []),
                            "engagementMetrics": r.get("engagement_metrics", {}),
                            "recommendationReason": r.get("recommendation_reason", ""),
                            "keyPoints": r.get("key_points", []),
                        }
                        for r in raw_results
                    ]
                    logger.info(f"搜索完成: {len(search_items)} 条结果")

                elif stage == "error":
                    error_msg = event.get("message", "搜索失败")
                    logger.warning(f"搜索流式事件 error: {error_msg}")
                    return {
                        "search_query": search_query,
                        "search_results": [],
                        "error": error_msg,
                    }

        except Exception as e:
            logger.error(f"搜索执行失败: {e}")
            return {
                "search_query": search_query,
                "search_results": [],
                "error": f"搜索失败: {e}",
            }

        # 4. 推送搜索结果到前端
        if emit and search_items:
            await emit({"type": "search_results", "results": search_items})

        return {"search_query": search_query, "search_results": search_items}

    async def _synthesis_node(self, state: ChatState, config: RunnableConfig) -> dict:
        """搜索结果合成节点：使用 LLMProvider.stream() 实现真实流式输出。

        降级路径：
        1. 搜索失败（有 error） → simple_chat 普通回复
        2. 搜索无结果 → 固定提示
        3. stream() 失败 → 降级为 simple_chat 非流式
        """
        emit = _get_emit(config)
        if emit:
            await emit({"type": "status", "node": "synthesis", "message": "正在整合搜索结果..."})

        search_results = state.get("search_results") or []
        error = state.get("error")

        # 降级路径 1：搜索失败，退化为普通回复
        if error and not search_results:
            try:
                fallback = await asyncio.to_thread(
                    self._llm.simple_chat, state["user_message"]
                )
                chunks = [fallback] if fallback else ["抱歉，搜索失败了，请稍后重试。"]
            except Exception:
                chunks = ["抱歉，搜索失败了，请稍后重试。"]
            if emit:
                for c in chunks:
                    await emit({"type": "chunk", "content": c})
            return {"response_chunks": chunks, "sources": []}

        # 降级路径 2：搜索无结果
        if not search_results:
            msg = "没有找到相关资源。你可以尝试换个关键词，或者更具体地描述你想学习的内容。"
            if emit:
                await emit({"type": "chunk", "content": msg})
            return {"response_chunks": [msg], "sources": []}

        # 正常路径：构建带搜索结果的 prompt，流式输出
        context_parts = []
        for i, r in enumerate(search_results, 1):
            context_parts.append(
                f"[{i}] {r['title']} ({r['platform']})\n"
                f"    URL: {r['url']}\n"
                f"    {r.get('description', '')}"
            )
        search_context = "\n\n".join(context_parts)

        synthesis_prompt = (
            f"用户问题：{state['user_message']}\n\n"
            f"以下是搜索到的相关资源：\n{search_context}\n\n"
            f"请基于以上搜索结果，为用户提供综合回答。"
            f"在回答中用 [1] [2] 等标注引用了哪些来源。"
            f"如果搜索结果与问题不太相关，诚实告知用户。"
        )

        from src.providers.base import Message
        messages = [
            Message(role="system", content="你是一个学习助手，基于搜索结果为用户提供准确、有引用的综合回答。"),
            Message(role="user", content=synthesis_prompt),
        ]

        chunks: List[str] = []
        loop = asyncio.get_running_loop()

        def _stream_synthesis():
            """在子线程中运行 LLM stream，逐 chunk 实时推送"""
            try:
                for chunk in self._llm.stream(messages):
                    if chunk:
                        chunks.append(chunk)
                        if emit:
                            future = asyncio.run_coroutine_threadsafe(
                                emit({"type": "chunk", "content": chunk}), loop
                            )
                            future.result(timeout=5)
            except Exception as e:
                logger.error(f"合成流式输出失败，降级为非流式: {e}")
                # 降级路径 3：流式失败 → simple_chat 非流式
                try:
                    fallback = self._llm.simple_chat(
                        synthesis_prompt,
                        system_prompt="你是一个学习助手，基于搜索结果为用户提供准确、有引用的综合回答。",
                    )
                    if fallback:
                        chunks.append(fallback)
                        if emit:
                            future = asyncio.run_coroutine_threadsafe(
                                emit({"type": "chunk", "content": fallback}), loop
                            )
                            future.result(timeout=5)
                except Exception:
                    error_msg = "整合结果时出错，请重试。"
                    chunks.append(error_msg)
                    if emit:
                        future = asyncio.run_coroutine_threadsafe(
                            emit({"type": "chunk", "content": error_msg}), loop
                        )
                        future.result(timeout=5)

        await asyncio.to_thread(_stream_synthesis)

        return {"response_chunks": chunks, "sources": []}

    # ------------------------------------------
    # 公开接口
    # ------------------------------------------

    async def run(self, state: ChatState, config: RunnableConfig = None) -> ChatState:
        """执行图，返回最终状态"""
        return await self._graph.ainvoke(state, config=config)

    @property
    def graph(self):
        """暴露编译后的图对象"""
        return self._graph

    @classmethod
    def build_for_visualization(cls):
        """无依赖构建图结构，仅用于可视化（不注入真实依赖）。

        创建一个 dummy 实例，只为获取编译后的图拓扑。
        """
        # 用 None 占位，节点不会被执行
        class _DummyOrchestrator:
            _tutor = None
            _search = None
            _llm = None
            _episodic = None

            async def _classify_intent_node(self, state, config):
                return {"intent": {"label": "normal_chat", "confidence": 0.0}}

            async def _tutor_node(self, state, config):
                return {}

            async def _search_node(self, state, config):
                return {}

            async def _synthesis_node(self, state, config):
                return {}

        dummy = _DummyOrchestrator()
        graph = StateGraph(ChatState)
        graph.add_node("classify_intent", dummy._classify_intent_node)
        graph.add_node("tutor_node", dummy._tutor_node)
        graph.add_node("search_node", dummy._search_node)
        graph.add_node("synthesis_node", dummy._synthesis_node)
        graph.set_entry_point("classify_intent")
        graph.add_conditional_edges(
            "classify_intent",
            _route_by_intent,
            {"tutor_node": "tutor_node", "search_node": "search_node"},
        )
        graph.add_edge("tutor_node", END)
        graph.add_edge("search_node", "synthesis_node")
        graph.add_edge("synthesis_node", END)
        return graph.compile()


# ============================================
# 工厂函数
# ============================================

def _get_orchestrator(plan_id: str) -> ChatOrchestrator:
    """从 session 获取依赖，构建 ChatOrchestrator。

    - TutorAgent / LLMProvider 通过 get_session(plan_id) 复用
    - SearchOrchestrator 每次新建（内部有浏览器生命周期管理）
    - EpisodicMemory 使用 session 的 LLMProvider 构建
    """
    from backend.session_context import get_session
    from src.specialists.search_orchestrator import SearchOrchestrator
    from src.agents.episodic_memory import EpisodicMemory

    ctx = get_session(plan_id)
    llm = ctx.tutor.llm
    return ChatOrchestrator(
        tutor_agent=ctx.tutor,
        search_orchestrator=SearchOrchestrator(llm_provider=llm),
        llm_provider=llm,
        episodic_memory=EpisodicMemory(llm_provider=llm),
    )
