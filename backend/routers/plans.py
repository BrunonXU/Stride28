"""规划 CRUD 端点及子资源端点"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import database
from backend.session_context import clear_session, get_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["plans"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class PlanCreate(BaseModel):
    title: str
    description: Optional[str] = None
    cycleDays: Optional[int] = None              # 3-28，写入 plans.total_days
    learnerProfile: Optional[dict] = None         # 可选画像数据

class PlanUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None


class PlanResponse(BaseModel):
    id: str
    title: str
    description: Optional[str]
    sourceCount: int
    lastAccessedAt: str
    coverColor: str
    totalDays: int
    completedDays: int
    createdAt: str


class ProgressCompleted(BaseModel):
    completed: bool


class ProgressTasks(BaseModel):
    tasks: list


# ---------------------------------------------------------------------------
# Plans CRUD
# ---------------------------------------------------------------------------

@router.get("/plans", response_model=List[PlanResponse])
async def list_plans():
    return database.get_all_plans()


@router.post("/plans", response_model=PlanResponse, status_code=201)
async def create_plan(body: PlanCreate):
    plan_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    plan = {
        "id": plan_id,
        "title": body.title,
        "description": body.description or "",
        "sourceCount": 0,
        "lastAccessedAt": now,
        "coverColor": "from-blue-400 to-indigo-600",
        "totalDays": body.cycleDays or 0,
        "completedDays": 0,
        "createdAt": now,
    }
    result = database.create_plan(plan)

    # 可选：同步写入学习者画像
    if body.learnerProfile:
        try:
            profile = dict(body.learnerProfile)
            profile["planId"] = plan_id
            profile["id"] = str(uuid.uuid4())
            # 同步 duration 为天数字符串（learner_profiles.duration 是 TEXT 类型）
            profile["duration"] = str(body.cycleDays or 14)
            database.upsert_learner_profile(profile)
        except Exception as e:
            # 画像写入失败不影响计划创建
            logger.warning("[create_plan] 写入学习者画像失败: %s", e)

    return result


@router.put("/plans/{plan_id}", response_model=PlanResponse)
async def update_plan(plan_id: str, body: PlanUpdate):
    updates = {}
    if body.title is not None:
        updates["title"] = body.title
    if body.description is not None:
        updates["description"] = body.description
    updates["lastAccessedAt"] = datetime.now(timezone.utc).isoformat()
    result = database.update_plan(plan_id, updates)
    if result is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return result


@router.delete("/plans/{plan_id}", status_code=204)
async def delete_plan(plan_id: str):
    deleted = database.delete_plan(plan_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Plan not found")
    clear_session(plan_id)


# ---------------------------------------------------------------------------
# Messages sub-resource
# ---------------------------------------------------------------------------

@router.get("/plans/{plan_id}/messages")
async def get_plan_messages(plan_id: str):
    return database.get_messages(plan_id)


@router.delete("/plans/{plan_id}/messages", status_code=204)
async def clear_plan_messages(plan_id: str):
    """清空对话消息。先强制摘要再删消息，都在后台执行，不阻塞响应。

    前端乐观更新（立即清屏），后端异步处理：摘要 → 删消息。
    """

    async def _bg_summarize_then_delete():
        try:
            ctx = get_session(plan_id)
            from src.agents.episodic_memory import EpisodicMemory
            em = EpisodicMemory(llm_provider=ctx.tutor.llm)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, em.force_summarize_all, plan_id)
        except Exception as e:
            logger.warning(f"[plans] 清空对话前强制摘要失败: {e}")
        # 无论摘要成功与否，都删消息
        database.delete_messages(plan_id)

    asyncio.create_task(_bg_summarize_then_delete())


# ---------------------------------------------------------------------------
# Materials sub-resource
# ---------------------------------------------------------------------------

@router.get("/plans/{plan_id}/materials")
async def get_plan_materials(plan_id: str):
    return database.get_materials(plan_id)


# ---------------------------------------------------------------------------
# Progress sub-resource
# ---------------------------------------------------------------------------

@router.post("/plans/{plan_id}/progress")
async def save_progress(plan_id: str, body: List[dict]):
    database.upsert_progress(plan_id, body)
    return {"ok": True}


@router.get("/plans/{plan_id}/progress")
async def get_plan_progress(plan_id: str):
    return database.get_progress(plan_id)


@router.put("/plans/{plan_id}/progress/{day_number}")
async def update_day_completed(plan_id: str, day_number: int, body: ProgressCompleted):
    ok = database.update_progress_completed(plan_id, day_number, body.completed)
    if not ok:
        raise HTTPException(status_code=404, detail="Progress not found")
    return {"ok": True}


@router.put("/plans/{plan_id}/progress/{day_number}/tasks")
async def update_day_tasks(plan_id: str, day_number: int, body: ProgressTasks):
    ok = database.update_progress_tasks(plan_id, day_number, body.tasks)
    if not ok:
        raise HTTPException(status_code=404, detail="Progress not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Notes sub-resource
# ---------------------------------------------------------------------------

@router.get("/plans/{plan_id}/notes")
async def get_plan_notes(plan_id: str):
    return database.get_notes(plan_id)


# ---------------------------------------------------------------------------
# Generated Contents sub-resource
# ---------------------------------------------------------------------------

@router.get("/plans/{plan_id}/generated-contents")
async def get_plan_generated_contents(plan_id: str):
    return database.get_generated_contents(plan_id)


@router.post("/plans/{plan_id}/generated-contents")
async def save_generated_content(plan_id: str, body: dict):
    body["planId"] = plan_id
    return database.insert_generated_content(body)


@router.delete("/generated-contents/{content_id}", status_code=204)
async def delete_generated_content(content_id: str):
    deleted = database.delete_generated_content(content_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Generated content not found")


# ---------------------------------------------------------------------------
# Search History sub-resource
# ---------------------------------------------------------------------------

@router.get("/plans/{plan_id}/search-history")
async def get_plan_search_history(plan_id: str):
    return database.get_search_history(plan_id)


@router.post("/plans/{plan_id}/search-history")
async def save_search_history(plan_id: str, body: dict):
    body["planId"] = plan_id
    return database.insert_search_history(body)


@router.put("/plans/{plan_id}/search-history/{entry_id}")
async def update_search_history(plan_id: str, entry_id: str, body: dict):
    result = database.update_search_history(entry_id, body)
    if result is None:
        raise HTTPException(status_code=404, detail="Search history entry not found")
    return result


@router.delete("/plans/{plan_id}/search-history/{entry_id}", status_code=204)
async def delete_single_search_history(plan_id: str, entry_id: str):
    deleted = database.delete_single_search_history(entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Search history entry not found")


@router.delete("/plans/{plan_id}/search-history", status_code=204)
async def clear_search_history(plan_id: str):
    database.delete_search_history(plan_id)
