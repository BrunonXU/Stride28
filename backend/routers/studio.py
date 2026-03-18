"""
Studio 内容生成端点

POST /api/studio/{type}           — 生成 AI 内容（learning-plan / study-guide / flashcards / quiz / progress-report / mind-map / day-summary）
PUT  /api/plan/day/{day_id}/complete — 标记 Day 完成（幂等）
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Union

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import database
from backend.prompt_builder import PromptBuilder
from backend.session_context import get_session

logger = logging.getLogger(__name__)
router = APIRouter(tags=["studio"])

VALID_TYPES = {"learning-plan", "study-guide", "flashcards", "quiz", "progress-report", "mind-map", "day-summary"}

# 各类型对应的生成提示词
_PROMPTS = {
    "learning-plan": (
        "请根据已上传的学习材料，生成一份结构化的学习计划。"
        "包含：总体目标、每日学习主题（3-7天）、每天的具体任务（视频/阅读/练习）。"
        "用 Markdown 格式输出，包含清晰的标题层级。"
    ),
    "study-guide": (
        "请根据已上传的学习材料，生成一份全面的学习指南。"
        "包含：核心概念总结、重要知识点、学习路径建议、常见问题解答。"
        "用 Markdown 格式输出。"
    ),
    "flashcards": (
        "请根据已上传的学习材料，生成 10-15 张闪卡（问答对）。"
        "格式：每张卡片用 '**Q:** 问题\\n**A:** 答案' 格式，用 '---' 分隔。"
        "覆盖核心概念、定义、原理等关键知识点。"
    ),
    "quiz": (
        "请根据已上传的学习材料，生成一份包含 5-8 道题的测验。"
        "包含：单选题、判断题、简答题各若干道。"
        "每题附上正确答案和解析。用 Markdown 格式输出。"
    ),
    "progress-report": (
        "请根据当前学习进度，生成一份学习进度报告。"
        "包含：已完成内容、掌握程度评估、薄弱环节分析、下一步建议。"
        "用 Markdown 格式输出。"
    ),
    "mind-map": (
        "请根据已上传的学习材料，生成一份思维导图结构。"
        "使用 Markdown 标题层级格式（#/##/###），适合渲染为思维导图。"
        "按学习天数组织知识结构。"
    ),
    "day-summary": (
        "请根据今日学习内容，生成一份知识总结。"
        "包含：知识回顾、与之前知识的关联分析、复习建议、明日预告。"
        "用 Markdown 格式输出。"
    ),
}

_TITLES = {
    "learning-plan": "学习计划",
    "study-guide": "学习指南",
    "flashcards": "闪卡",
    "quiz": "测验",
    "progress-report": "进度报告",
    "mind-map": "思维导图",
    "day-summary": "今日总结",
}


class LearnerProfileRequest(BaseModel):
    """学习者画像"""
    goal: str = ""
    duration: Union[str, int] = ""
    level: str = ""
    background: str = ""
    dailyHours: str = ""


class StudioRequest(BaseModel):
    """HTTP request body for Studio content generation.
    Also serves as the LearningContext for PromptBuilder."""
    planId: str = ""
    allDays: List[Dict] = []
    currentDayNumber: Optional[int] = None
    learnerProfile: Optional[LearnerProfileRequest] = None


# Alias for clarity when used as internal context by PromptBuilder
LearningContext = StudioRequest


class StudioResponse(BaseModel):
    type: str
    title: str
    content: str
    createdAt: str


class DayCompleteResponse(BaseModel):
    success: bool
    dayNumber: int


@router.post("/studio/{content_type}", response_model=StudioResponse)
async def generate_studio_content(content_type: str, body: StudioRequest):
    if content_type not in VALID_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown type: {content_type}")

    title = _TITLES[content_type]
    t_start = time.perf_counter()
    status = "ok"

    try:
        ctx = get_session(body.planId)
        # Load learner profile: prefer request body, fallback to DB
        learner_profile = body.learnerProfile
        if not learner_profile and body.planId:
            profile_data = database.get_learner_profile(body.planId)
            if profile_data:
                learner_profile = LearnerProfileRequest(
                    goal=profile_data.get("goal", ""),
                    duration=profile_data.get("duration", ""),
                    level=profile_data.get("level", ""),
                    background=profile_data.get("background", ""),
                    dailyHours=profile_data.get("dailyHours", ""),
                )
        learning_context = LearningContext(
            planId=body.planId,
            allDays=body.allDays,
            currentDayNumber=body.currentDayNumber,
            learnerProfile=learner_profile,
        )
        builder = PromptBuilder(rag_engine=ctx.tutor.rag_engine)
        user_prompt, system_prompt = builder.build(content_type, learning_context)
        # 不设 max_tokens，让模型自行决定输出长度（避免长 JSON 被截断）
        content = await asyncio.to_thread(ctx.tutor.generate, user_prompt, system_prompt=system_prompt)
    except Exception as e:
        logger.warning(f"[studio] Generation failed for {content_type}: {e}")
        content = _fallback_content(content_type)
        user_prompt = ""
        status = "error"

    duration_ms = round((time.perf_counter() - t_start) * 1000, 1)
    now = datetime.now(timezone.utc).isoformat()

    # Record trace for DEV panel
    try:
        from backend.routers.dev import record_trace
        record_trace({
            "id": str(uuid.uuid4()),
            "type": "tool",
            "name": f"Studio.{content_type}",
            "startTime": now,
            "duration": duration_ms,
            "status": status,
            "input": (user_prompt[:200] if user_prompt else ""),
            "output": content[:200],
            "tokens": {"prompt": 0, "completion": 0, "total": 0},
            "metadata": {"planId": body.planId, "contentType": content_type},
        })
    except Exception:
        pass

    # Persist generated content to database
    # 输出质量校验：LLM 返回 → 校验/修复 → 存入 DB
    if status == "ok":
        if content_type == "learning-plan":
            content = _apply_learning_plan_validation(content, body.learnerProfile)
        elif content_type == "flashcards":
            content = _validate_flashcards(content)
        elif content_type == "quiz":
            content = _validate_quiz(content)
        elif content_type == "mind-map":
            content = _validate_mind_map(content)

    if body.planId:
        content_id = str(uuid.uuid4())
        try:
            database.insert_generated_content({
                "id": content_id,
                "planId": body.planId,
                "type": content_type,
                "title": title,
                "content": content,
                "createdAt": now,
            })
        except Exception as e:
            logger.warning(f"[studio] Failed to persist generated content: {e}")

    return StudioResponse(type=content_type, title=title, content=content, createdAt=now)


@router.put("/plan/day/{day_id}/complete", response_model=DayCompleteResponse)
async def complete_day(day_id: int, plan_id: str = ""):
    """标记 Day 完成（幂等）
    
    进度状态由前端 studioStore + SQLite progress 表管理，
    此端点仅做幂等确认，不再依赖旧的 ProgressTracker。
    """
    return DayCompleteResponse(success=True, dayNumber=day_id)


async def generate_studio_content_internal(content_type: str, plan_id: str) -> dict:
    """Internal function for chat-triggered Studio content generation.

    Reuses PromptBuilder logic without HTTP request/response overhead.
    Called from chat.py when IntentDetector detects a Studio trigger.

    Returns:
        dict with type, title, content, createdAt (empty dict if invalid type)
    """
    if content_type not in VALID_TYPES:
        return {}

    ctx = get_session(plan_id)
    # Load learner profile from DB for internal calls
    profile_data = database.get_learner_profile(plan_id)
    learner_profile = None
    if profile_data:
        learner_profile = LearnerProfileRequest(
            goal=profile_data.get("goal", ""),
            duration=profile_data.get("duration", ""),
            level=profile_data.get("level", ""),
            background=profile_data.get("background", ""),
            dailyHours=profile_data.get("dailyHours", ""),
        )
    learning_context = LearningContext(planId=plan_id, learnerProfile=learner_profile)
    builder = PromptBuilder(rag_engine=ctx.tutor.rag_engine)
    title = _TITLES.get(content_type, content_type)

    try:
        user_prompt, system_prompt = builder.build(content_type, learning_context)
        content = await asyncio.to_thread(ctx.tutor.generate, user_prompt, system_prompt=system_prompt)
    except Exception as e:
        logger.warning(f"[studio] Internal generation failed for {content_type}: {e}")
        content = _fallback_content(content_type)

    now = datetime.now(timezone.utc).isoformat()

    # 输出质量校验
    if content_type == "learning-plan":
        content = _apply_learning_plan_validation(content, learner_profile)
    elif content_type == "flashcards":
        content = _validate_flashcards(content)
    elif content_type == "quiz":
        content = _validate_quiz(content)
    elif content_type == "mind-map":
        content = _validate_mind_map(content)

    # Persist
    if plan_id:
        try:
            database.insert_generated_content({
                "id": str(uuid.uuid4()),
                "planId": plan_id,
                "type": content_type,
                "title": title,
                "content": content,
                "createdAt": now,
            })
        except Exception:
            pass

    return {"type": content_type, "title": title, "content": content, "createdAt": now}


# ---------------------------------------------------------------------------
# Learner Profile endpoints
# ---------------------------------------------------------------------------

class LearnerProfileResponse(BaseModel):
    planId: str
    goal: str = ""
    duration: Union[str, int] = ""
    level: str = ""
    background: str = ""
    dailyHours: str = ""


@router.get("/learner-profile/{plan_id}", response_model=LearnerProfileResponse)
async def get_learner_profile(plan_id: str):
    """获取学习者画像"""
    profile = database.get_learner_profile(plan_id)
    if not profile:
        return LearnerProfileResponse(planId=plan_id)
    return LearnerProfileResponse(
        planId=plan_id,
        goal=profile.get("goal", ""),
        duration=profile.get("duration", ""),
        level=profile.get("level", ""),
        background=profile.get("background", ""),
        dailyHours=profile.get("dailyHours", ""),
    )


@router.put("/learner-profile/{plan_id}", response_model=LearnerProfileResponse)
async def save_learner_profile(plan_id: str, body: LearnerProfileRequest):
    """保存/更新学习者画像"""
    profile_id = str(uuid.uuid4())
    database.upsert_learner_profile({
        "id": profile_id,
        "planId": plan_id,
        "goal": body.goal,
        "duration": str(body.duration),
        "level": body.level,
        "background": body.background,
        "dailyHours": body.dailyHours,
    })
    return LearnerProfileResponse(
        planId=plan_id,
        goal=body.goal,
        duration=body.duration,
        level=body.level,
        background=body.background,
        dailyHours=body.dailyHours,
    )


def _enforce_day_count(days: list[dict], target_duration: int) -> list[dict]:
    """硬校验：确保 days 数组长度 === target_duration。

    - 多余：截断到 target_duration
    - 不足：补齐占位 day（title="Day N", tasks=[]）
    - dayNumber 重新编号确保连续
    """
    # 截断
    result = days[:target_duration]
    # 补齐
    existing_count = len(result)
    for i in range(existing_count, target_duration):
        result.append({
            "dayNumber": i + 1,
            "title": f"Day {i + 1}",
            "completed": False,
            "tasks": [],
        })
    # 重新编号
    for i, d in enumerate(result):
        d["dayNumber"] = i + 1
    if len(days) != target_duration:
        logger.warning(
            "[studio] _enforce_day_count: LLM returned %d days, target %d → adjusted",
            len(days), target_duration,
        )
    return result


def _apply_learning_plan_validation(content: str, learner_profile) -> str:
    """对 learning-plan 的 LLM 输出做天数硬校验，返回修正后的 content 字符串。"""
    import json as _json
    import re

    from backend.prompt_builder import safe_parse_duration

    # 提取 duration
    raw_duration = None
    if learner_profile:
        raw_duration = getattr(learner_profile, "duration", None)
        if raw_duration is None:
            raw_duration = learner_profile.duration if hasattr(learner_profile, "duration") else None
    if raw_duration is None or raw_duration == "":
        return content  # 没有 duration 约束，跳过校验

    target = safe_parse_duration(raw_duration)

    # 尝试解析 JSON（先 strip code fence）
    clean = content.strip()
    if clean.startswith("```"):
        # 去掉首行 ```json 和末尾 ```
        lines = clean.split("\n")
        if lines[-1].strip().startswith("```"):
            lines = lines[1:-1]
        else:
            lines = lines[1:]  # 末尾没有 ```（可能被截断）
        clean = "\n".join(lines)

    try:
        parsed = _json.loads(clean)
    except _json.JSONDecodeError:
        return content  # 无法解析，原样返回

    if not isinstance(parsed, dict) or "days" not in parsed:
        return content

    parsed["days"] = _enforce_day_count(parsed["days"], target)
    return _json.dumps(parsed, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 输出质量校验（Task 9）
# ---------------------------------------------------------------------------

def _validate_flashcards(content: str) -> str:
    """校验闪卡结构：移除不完整卡片，截断超量，不足仅警告。"""
    import json as _json

    try:
        parsed = _json.loads(content)
    except _json.JSONDecodeError:
        return content  # 非 JSON 格式，原样返回

    if not isinstance(parsed, dict) or "cards" not in parsed:
        return content

    cards = parsed.get("cards", [])
    # 移除缺失 front/back 的卡片
    valid_cards = [c for c in cards if c.get("front") and c.get("back")]
    if len(valid_cards) < len(cards):
        logger.warning("[studio] Removed %d invalid flashcards", len(cards) - len(valid_cards))
    # 截断超过 20 张
    if len(valid_cards) > 20:
        logger.warning("[studio] Truncating flashcards from %d to 20", len(valid_cards))
        valid_cards = valid_cards[:20]
    # 不足 5 张仅警告
    if len(valid_cards) < 5:
        logger.warning("[studio] Only %d valid flashcards (expected 5-20)", len(valid_cards))

    parsed["cards"] = valid_cards
    return _json.dumps(parsed, ensure_ascii=False)


def _validate_quiz(content: str) -> str:
    """校验测验结构：移除不完整题目，检查题型多样性。"""
    import json as _json

    try:
        parsed = _json.loads(content)
    except _json.JSONDecodeError:
        return content

    if not isinstance(parsed, dict) or "questions" not in parsed:
        return content

    questions = parsed.get("questions", [])
    valid_qs = [
        q for q in questions
        if q.get("question") and (q.get("options") or q.get("answer"))
    ]
    if len(valid_qs) < len(questions):
        logger.warning("[studio] Removed %d invalid quiz questions", len(questions) - len(valid_qs))
    # 题型多样性检查（仅警告）
    types = set(q.get("type", "unknown") for q in valid_qs)
    if len(types) <= 1 and len(valid_qs) > 1:
        logger.warning("[studio] All quiz questions are same type: %s", types)

    parsed["questions"] = valid_qs
    return _json.dumps(parsed, ensure_ascii=False)


def _validate_mind_map(content: str) -> str:
    """校验思维导图 Markdown 结构（仅警告，不修改）。"""
    h1_count = content.count("\n# ") + (1 if content.startswith("# ") else 0)
    h2_count = content.count("\n## ")
    if h1_count < 2:
        logger.warning("[studio] Mind-map has only %d H1 headings (expected >= 2)", h1_count)
    if h2_count < 4:
        logger.warning("[studio] Mind-map has only %d H2 headings (expected >= 4)", h2_count)
    return content  # 不修改，仅日志


def _fallback_content(content_type: str) -> str:
    """TutorAgent 不可用时的降级内容"""
    fallbacks = {
        "learning-plan": "# 学习计划\n\n请先上传学习材料，AI 将根据材料内容生成个性化学习计划。",
        "study-guide": "# 学习指南\n\n请先上传学习材料，AI 将根据材料内容生成学习指南。",
        "flashcards": "**Q:** 请先上传学习材料\n**A:** AI 将根据材料内容生成闪卡",
        "quiz": "# 测验\n\n请先上传学习材料，AI 将根据材料内容生成测验题目。",
        "progress-report": "# 进度报告\n\n暂无学习数据，开始学习后将自动生成进度报告。",
        "mind-map": "# 思维导图\n\n请先上传学习材料，AI 将根据材料内容生成思维导图。",
        "day-summary": "# 今日总结\n\n暂无今日学习数据，完成学习任务后将自动生成总结。",
    }
    return fallbacks.get(content_type, "内容生成失败，请稍后重试。")


# ─── Regenerate Plan (Preserve_Mode) ───

class RegeneratePlanRequest(BaseModel):
    """周期变更重新生成请求"""
    planId: str
    newCycleDays: int  # 3-28
    completedDays: List[Dict] = []


class RegeneratePlanResponse(BaseModel):
    days: List[Dict]
    totalDays: int


@router.post("/studio/regenerate-plan", response_model=RegeneratePlanResponse)
async def regenerate_plan(body: RegeneratePlanRequest):
    """周期变更重新生成学习计划（Preserve_Mode）

    逻辑：
    1. 保留已完成天数
    2. 重新生成未完成天数（从 completed_count+1 到 newCycleDays）
    3. 截断边界：newCycleDays <= completed_count 时直接截断
    """
    if not 3 <= body.newCycleDays <= 28:
        raise HTTPException(status_code=400, detail="cycleDays must be between 3 and 28")

    completed = body.completedDays
    completed_count = len(completed)

    # 边界：新周期 <= 已完成天数 → 截断
    if body.newCycleDays <= completed_count:
        truncated = completed[:body.newCycleDays]
        database.upsert_progress(body.planId, truncated)
        _update_profile_duration(body.planId, body.newCycleDays)
        return RegeneratePlanResponse(days=truncated, totalDays=body.newCycleDays)

    # 正常：保留已完成 + 重新生成未完成
    try:
        ctx = get_session(body.planId)
        profile_data = database.get_learner_profile(body.planId)
        learner_profile = None
        if profile_data:
            learner_profile = LearnerProfileRequest(
                goal=profile_data.get("goal", ""),
                duration=str(body.newCycleDays),
                level=profile_data.get("level", ""),
                background=profile_data.get("background", ""),
                dailyHours=profile_data.get("dailyHours", ""),
            )

        learning_context = LearningContext(
            planId=body.planId,
            allDays=completed,
            currentDayNumber=completed_count + 1,
            learnerProfile=learner_profile,
        )
        builder = PromptBuilder(rag_engine=ctx.tutor.rag_engine)
        user_prompt, system_prompt = builder.build("learning-plan", learning_context)

        # Preserve_Mode 指令：只生成未完成部分
        user_prompt += (
            f"\n\n【重要】这是周期变更重新生成。"
            f"已完成 Day 1-{completed_count}，请只生成 Day {completed_count + 1} 到 Day {body.newCycleDays} 的计划。"
            f"返回的 JSON days 数组只包含新生成的天数（dayNumber 从 {completed_count + 1} 开始）。"
            f"总天数为 {body.newCycleDays}。"
        )

        content = await asyncio.to_thread(ctx.tutor.generate, user_prompt, system_prompt=system_prompt, max_tokens=8192)
        new_days = _parse_generated_days(content, completed_count, body.newCycleDays)

    except Exception as e:
        logger.warning(f"[studio] regenerate-plan generation failed: {e}")
        # 降级：生成空白占位天数
        new_days = _generate_placeholder_days(completed_count + 1, body.newCycleDays)

    merged = completed + new_days
    database.upsert_progress(body.planId, merged)
    _update_profile_duration(body.planId, body.newCycleDays)

    return RegeneratePlanResponse(days=merged, totalDays=body.newCycleDays)


def _update_profile_duration(plan_id: str, new_duration: int) -> None:
    """更新 learner_profile 的 duration 字段"""
    try:
        profile = database.get_learner_profile(plan_id)
        if profile:
            profile["duration"] = new_duration
            profile["planId"] = plan_id
            database.upsert_learner_profile(profile)
    except Exception as e:
        logger.warning(f"[studio] Failed to update profile duration: {e}")


def _parse_generated_days(content: str, completed_count: int, total_days: int) -> List[dict]:
    """从 LLM 生成内容中解析 days JSON，带容错"""
    import json as _json
    import re

    try:
        parsed = _json.loads(content)
    except _json.JSONDecodeError:
        # 尝试从 markdown code block 中提取
        match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', content)
        if match:
            try:
                parsed = _json.loads(match.group(1))
            except _json.JSONDecodeError:
                return _generate_placeholder_days(completed_count + 1, total_days)
        else:
            return _generate_placeholder_days(completed_count + 1, total_days)

    days_raw = parsed.get("days", []) if isinstance(parsed, dict) else parsed
    if not isinstance(days_raw, list):
        return _generate_placeholder_days(completed_count + 1, total_days)

    result = []
    for i, d in enumerate(days_raw):
        day_num = completed_count + 1 + i
        if day_num > total_days:
            break
        tasks = []
        for j, t in enumerate(d.get("tasks", [])):
            tasks.append({
                "id": t.get("id", f"task-{day_num}-{j}"),
                "type": t.get("type", "reading"),
                "title": t.get("title", f"任务 {j + 1}"),
                "completed": False,
            })
        result.append({
            "dayNumber": day_num,
            "title": d.get("title", f"Day {day_num}"),
            "completed": False,
            "tasks": tasks,
        })

    # 补齐缺失的天数
    existing_nums = {d["dayNumber"] for d in result}
    for day_num in range(completed_count + 1, total_days + 1):
        if day_num not in existing_nums:
            result.append({
                "dayNumber": day_num,
                "title": f"Day {day_num}",
                "completed": False,
                "tasks": [],
            })

    result.sort(key=lambda d: d["dayNumber"])
    return result


def _generate_placeholder_days(start: int, end: int) -> List[dict]:
    """降级：生成空白占位天数"""
    return [
        {
            "dayNumber": i,
            "title": f"Day {i}",
            "completed": False,
            "tasks": [],
        }
        for i in range(start, end + 1)
    ]

