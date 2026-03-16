"""
AI 对话端点

POST /api/chat      — SSE 流式输出（chunk / sources / questions / done / error）
POST /api/chat/sync — 普通 HTTP 降级端点（SSE 失败时使用）
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend import database

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])

MAX_HISTORY = 12  # 最多保留 12 条（6 轮）


class ChatRequest(BaseModel):
    planId: str
    message: str
    history: Optional[List[dict]] = None
    materialIds: Optional[List[str]] = None


def _truncate_history(history: List[dict]) -> List[dict]:
    """保留最近 MAX_HISTORY 条消息（6 轮）"""
    return history[-MAX_HISTORY:] if history else []


def _build_material_context(plan_id: str, material_ids: List[str], user_message: str = "") -> str:
    """从数据库获取指定材料的内容，组装为可注入 prompt 的上下文文本。

    搜索来源材料（bilibili/xiaohongshu/other 等）：从 extra_data 提取内容。
    上传文件材料（pdf/markdown/text）：通过 RAGEngine 按 material_id 过滤检索。
    总上下文限制 8000 字符，按材料顺序截断。
    """
    MAX_MATERIALS = 5
    MAX_CONTENT_TEXT = 2000
    MAX_TOTAL_CHARS = 8000

    if not material_ids:
        return ""

    # 获取所有材料基本信息
    all_materials = database.get_materials(plan_id) if plan_id else []
    mat_map = {m["id"]: m for m in all_materials}

    # 区分搜索来源 vs 上传文件
    UPLOAD_TYPES = {"pdf", "markdown", "text"}
    search_ids = []
    upload_ids = []
    for mid in material_ids[:MAX_MATERIALS]:
        mat = mat_map.get(mid, {})
        mat_type = mat.get("type", "")
        if mat_type in UPLOAD_TYPES:
            upload_ids.append(mid)
        else:
            search_ids.append(mid)

    parts = []

    # 1) 搜索来源材料：从 extra_data 提取
    for mid in search_ids:
        mat = mat_map.get(mid, {})
        title = mat.get("name") or mid[:8]
        extra = mat.get("extraData") or {}

        if not extra:
            extra = database.get_material_extra_data(mid) or {}

        sections = [f"【材料：{title}】"]

        content_text = extra.get("contentText") or ""
        if content_text:
            if len(content_text) > MAX_CONTENT_TEXT:
                content_text = content_text[:MAX_CONTENT_TEXT] + "…（已截断）"
            sections.append(f"正文：{content_text}")

        summary = extra.get("contentSummary") or ""
        if summary:
            sections.append(f"摘要：{summary}")

        key_points = extra.get("keyPoints") or []
        if key_points:
            sections.append("核心观点：\n" + "\n".join(f"- {p}" for p in key_points))

        key_facts = extra.get("keyFacts") or []
        if key_facts:
            sections.append("关键事实：" + "；".join(key_facts))

        comment_summary = extra.get("commentSummary") or ""
        if comment_summary:
            sections.append(f"评论总结：{comment_summary}")

        desc = extra.get("description") or ""
        if desc and not content_text and not summary:
            sections.append(f"描述：{desc}")

        if len(sections) > 1:
            parts.append("\n".join(sections))

    # 2) 上传文件材料：通过 RAG 按需检索
    if upload_ids and user_message:
        try:
            from src.rag import RAGEngine
            rag = RAGEngine(collection_name=f"plan_{plan_id}")
            k = min(3 * len(upload_ids), 10)
            results = rag.retrieve(
                query=user_message,
                k=k,
                filter={"material_id": {"$in": upload_ids}},
            )
            logger.info(f"[chat] RAG retrieve for upload materials: ids={upload_ids}, results={len(results)}")
            # 按 material_id 分组
            grouped: dict = {}
            for r in results:
                r_mid = r.metadata.get("material_id", "")
                grouped.setdefault(r_mid, []).append(r)

            for mid in upload_ids:
                mat = mat_map.get(mid, {})
                title = mat.get("name") or mid[:8]
                chunks = grouped.get(mid, [])
                if not chunks:
                    # Fallback：RAG 无结果时注入元信息，让 LLM 至少知道有这个文件
                    parts.append(f"【材料：{title}】\n（该文件内容暂未索引到相关片段，请用户提供更具体的问题）")
                    continue
                sections = [f"【材料：{title}】"]
                for i, chunk in enumerate(chunks[:3], 1):
                    sections.append(f"[相关片段 {i}]\n{chunk.content}")
                parts.append("\n\n".join(sections))
        except Exception as e:
            logger.warning(f"[chat] RAG retrieve failed for upload materials: {e}")
            # Fallback：RAG 异常时也注入元信息
            for mid in upload_ids:
                mat = mat_map.get(mid, {})
                title = mat.get("name") or mid[:8]
                parts.append(f"【材料：{title}】\n（文件内容检索失败，请稍后重试）")

    if not parts:
        return ""

    # 3) 总长度控制：按顺序截断，优先保留前面材料
    header = "[用户附加的参考材料]\n\n"
    separator = "\n\n---\n\n"
    remaining = MAX_TOTAL_CHARS - len(header)
    kept = []
    for i, part in enumerate(parts):
        cost = len(part) + (len(separator) if kept else 0)
        if cost <= remaining:
            kept.append(part)
            remaining -= cost
        else:
            break

    if not kept:
        return ""

    return header + separator.join(kept)


async def _generate_sse_legacy(plan_id: str, message: str, history: List[dict], material_ids: Optional[List[str]] = None):
    """SSE 生成器：逐 chunk 推送 TutorAgent 流式输出"""
    from backend.session_context import get_session

    logger.info(f"[chat] ▶ plan={plan_id!r} message={message[:80]!r} history_len={len(history)} materials={material_ids}")

    # Persist user message BEFORE starting the stream
    user_msg = {
        "id": str(uuid.uuid4()),
        "planId": plan_id,
        "role": "user",
        "content": message,
        "sources": [],
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    try:
        database.insert_message(user_msg)
    except Exception as e:
        logger.warning(f"[chat] Failed to persist user message: {e}")

    ctx = get_session(plan_id)
    truncated = _truncate_history(history)

    # 获取附加材料的内容，注入到对话上下文
    material_context = ""
    if material_ids:
        material_context = _build_material_context(plan_id, material_ids, user_message=message)
        logger.info(f"[chat] material_context built: ids={material_ids}, len={len(material_context)}, empty={not material_context}")

    chunk_count = 0
    full_response = ""
    src_payload = []
    t_start = time.perf_counter()

    # Episodic Memory：检查是否需要触发后台摘要，获取当前可用摘要
    episodic_summary = None
    try:
        from src.agents.episodic_memory import EpisodicMemory
        em = EpisodicMemory(llm_provider=ctx.tutor.llm)
        if em.should_trigger(plan_id):
            asyncio.create_task(em.trigger_background_summary(plan_id))
        episodic_summary = em.get_injectable_summary(plan_id)
    except Exception as e:
        logger.warning(f"[chat] Episodic Memory 初始化失败: {e}")

    try:
        for chunk in ctx.tutor.stream_response(
            user_input=message,
            history=truncated,
            use_rag=False,
            material_context=material_context if material_context else None,
            episodic_summary=episodic_summary,
        ):
            if chunk:
                chunk_count += 1
                full_response += chunk
                data = json.dumps({"type": "chunk", "content": chunk}, ensure_ascii=False)
                yield f"data: {data}\n\n"
                await asyncio.sleep(0)  # 让出事件循环，保证 SSE 实时推送

        # 推送来源（TutorAgent 在 _current_sources 里记录）
        sources = ctx.tutor._current_sources
        if sources:
            src_payload = [
                {
                    "materialId": s.get("filename", s.get("source", "unknown")),
                    "materialName": s.get("filename", s.get("source", "来源")),
                    "snippet": s.get("section", s.get("query", "")),
                }
                for s in sources
            ]
            src_data = json.dumps({"type": "sources", "sources": src_payload}, ensure_ascii=False)
            yield f"data: {src_data}\n\n"

        # 异步生成建议问题（简单实现：基于最后一条 AI 回复）
        questions = _generate_suggested_questions(message)
        if questions:
            q_data = json.dumps({"type": "questions", "questions": questions}, ensure_ascii=False)
            yield f"data: {q_data}\n\n"

    except Exception as e:
        logger.error(f"[chat] ✗ plan={plan_id!r} error={e!r}")
        err_data = json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)
        yield f"data: {err_data}\n\n"

    finally:
        t_end = time.perf_counter()
        duration_ms = round((t_end - t_start) * 1000, 1)

        # Persist assistant message after stream completes
        if full_response:
            assistant_msg = {
                "id": str(uuid.uuid4()),
                "planId": plan_id,
                "role": "assistant",
                "content": full_response,
                "sources": src_payload,
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
            try:
                database.insert_message(assistant_msg)
            except Exception as e:
                logger.warning(f"[chat] Failed to persist assistant message: {e}")

        # Record trace for DEV panel
        try:
            from backend.routers.dev import record_trace
            record_trace({
                "id": str(uuid.uuid4()),
                "type": "chain",
                "name": "TutorAgent.stream_response",
                "startTime": datetime.now(timezone.utc).isoformat(),
                "duration": duration_ms,
                "status": "ok" if full_response else "error",
                "input": message[:200],
                "output": full_response[:200] if full_response else "",
                "tokens": {"prompt": 0, "completion": 0, "total": 0},
                "metadata": {
                    "planId": plan_id,
                    "chunks": chunk_count,
                    "historyLen": len(history),
                    "hasSources": bool(src_payload),
                },
            })
        except Exception:
            pass

        logger.info(f"[chat] ✓ plan={plan_id!r} chunks={chunk_count} duration={duration_ms}ms")
        done_data = json.dumps({"type": "done", "chunkCount": chunk_count}, ensure_ascii=False)
        yield f"data: {done_data}\n\n"


async def _generate_sse_v2(plan_id: str, message: str, history: List[dict],
                          material_ids: Optional[List[str]] = None):
    """基于 ChatOrchestrator 的 SSE 生成器。

    核心变化：
    1. 用 asyncio.Queue 作为节点→SSE 的通信通道
    2. 图执行和 SSE yield 并发运行
    3. emit 通过 RunnableConfig 传递给图节点
    4. 无手动 record_trace（LangSmith 自动采集）
    """
    from backend.chat_orchestrator import ChatState, _get_orchestrator

    logger.info(f"[chat] ▶ plan={plan_id!r} message={message[:80]!r} history_len={len(history)} materials={material_ids}")

    # 持久化用户消息（图执行前）
    user_msg = {
        "id": str(uuid.uuid4()),
        "planId": plan_id,
        "role": "user",
        "content": message,
        "sources": [],
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    try:
        database.insert_message(user_msg)
    except Exception as e:
        logger.warning(f"[chat] 持久化用户消息失败: {e}")

    # SSE 事件队列
    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()  # 结束标记

    async def emit(event: dict):
        await queue.put(event)

    # 构建初始状态（emit 不在 state 里，通过 RunnableConfig 传递）
    state: ChatState = {
        "user_message": message,
        "history": _truncate_history(history),
        "plan_id": plan_id,
        "material_ids": material_ids,
        "intent": None,
        "target_platforms": None,
        "search_query": None,
        "search_results": None,
        "response_chunks": [],
        "sources": None,
        "error": None,
    }

    config = {"configurable": {"emit": emit}}

    async def _run_graph():
        """在后台执行图，完成后放入 sentinel"""
        try:
            orchestrator = _get_orchestrator(plan_id)
            result = await orchestrator.run(state, config=config)

            # 推送建议问题
            questions = _generate_suggested_questions(message)
            if questions:
                await queue.put({"type": "questions", "questions": questions})

            # 持久化助手回复（图执行后）
            full_response = "".join(result.get("response_chunks", []))
            if full_response:
                # 搜索结果快照：持久化到 DB，刷新后引用不丢失
                search_results_snapshot = result.get("search_results") or []
                assistant_msg = {
                    "id": str(uuid.uuid4()),
                    "planId": plan_id,
                    "role": "assistant",
                    "content": full_response,
                    "sources": result.get("sources") or [],
                    "searchResults": search_results_snapshot,
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                }
                try:
                    database.insert_message(assistant_msg)
                except Exception as e:
                    logger.warning(f"[chat] 持久化助手消息失败: {e}")

        except Exception as e:
            logger.error(f"[chat] 图执行失败，降级到 TutorAgent: {e}")
            await _fallback_tutor(plan_id, message, history, material_ids, queue)
        finally:
            await queue.put(sentinel)

    # 并发：图执行 + SSE 消费
    task = asyncio.create_task(_run_graph())

    try:
        while True:
            event = await queue.get()
            if event is sentinel:
                break
            data = json.dumps(event, ensure_ascii=False)
            yield f"data: {data}\n\n"
    finally:
        if not task.done():
            task.cancel()

    yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"


async def _fallback_tutor(plan_id: str, message: str, history: List[dict],
                          material_ids: Optional[List[str]], queue: asyncio.Queue):
    """图执行完全失败时的降级路径：直接调用 TutorAgent.stream_response()。

    使用 run_coroutine_threadsafe 实现逐 chunk 实时推送（与 tutor_node 一致）。
    """
    from backend.session_context import get_session

    ctx = get_session(plan_id)
    truncated = _truncate_history(history)

    material_context = ""
    if material_ids:
        material_context = _build_material_context(plan_id, material_ids, message)

    loop = asyncio.get_running_loop()
    chunks = []

    def _stream():
        for chunk in ctx.tutor.stream_response(
            user_input=message,
            history=truncated,
            use_rag=False,
            material_context=material_context if material_context else None,
        ):
            if chunk:
                chunks.append(chunk)
                future = asyncio.run_coroutine_threadsafe(
                    queue.put({"type": "chunk", "content": chunk}), loop
                )
                future.result(timeout=5)

    try:
        await asyncio.to_thread(_stream)

        # 持久化降级回复
        full_response = "".join(chunks)
        if full_response:
            assistant_msg = {
                "id": str(uuid.uuid4()),
                "planId": plan_id,
                "role": "assistant",
                "content": full_response,
                "sources": [],
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
            try:
                database.insert_message(assistant_msg)
            except Exception as e:
                logger.warning(f"[chat] 降级路径持久化失败: {e}")
    except Exception as e:
        logger.error(f"[chat] 降级路径也失败: {e}")
        await queue.put({"type": "error", "message": str(e)})


def _generate_suggested_questions(user_message: str) -> List[str]:
    """
    简单的建议问题生成（Task 7.6 可接入 LLM 异步生成）。
    目前基于关键词启发式生成 3 个问题。
    """
    templates = [
        f"{user_message}的核心原理是什么？",
        f"能举一个{user_message}的实际应用例子吗？",
        f"{user_message}和相关概念有什么区别？",
    ]
    return templates[:3]


@router.post("/chat")
async def chat(body: ChatRequest):
    return StreamingResponse(
        _generate_sse_v2(body.planId, body.message, body.history or [], body.materialIds),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/chat/sync")
async def chat_sync(body: ChatRequest):
    """降级端点：普通 HTTP，返回完整回复"""
    from backend.session_context import get_session

    ctx = get_session(body.planId)
    truncated = _truncate_history(body.history or [])

    try:
        response = ctx.tutor.run(
            user_input=body.message,
            history=truncated,
        )
        return {"content": response, "type": "sync"}
    except Exception as e:
        logger.error(f"[chat sync] error: {e}")
        return {"content": "AI 暂时不可用，请稍后重试", "type": "error"}
