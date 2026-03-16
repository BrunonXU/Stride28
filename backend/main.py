"""
FastAPI 后端入口

提供 REST + SSE API，供 React 前端调用。
集成现有 TutorAgent、ProgressTracker、Orchestrator。
"""

import sys
import os
import asyncio
import logging
import platform

from dotenv import load_dotenv
load_dotenv()

# Windows 上确保事件循环支持子进程（Playwright 需要）
# 必须在任何事件循环创建之前设置
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers import plans, chat, upload, search, studio, notes, resource, dev, provider
from backend import database

app = FastAPI(title="Stride28 API", version="0.1.0")


@app.on_event("startup")
async def _startup():
    """启动时初始化数据库并检查事件循环类型。"""
    logger = logging.getLogger("backend.main")

    # 初始化 SQLite 数据库
    try:
        database.init_db()
        logger.info("SQLite 数据库初始化完成")
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")
        raise

    # 检查事件循环类型
    loop = asyncio.get_running_loop()
    loop_type = type(loop).__name__
    logger.info(f"事件循环类型: {loop_type}")
    if platform.system() == "Windows" and "Proactor" not in loop_type:
        logger.warning(
            f"当前事件循环 {loop_type} 不支持子进程！"
            "Playwright 搜索功能可能无法使用。"
            "请使用 'uvicorn backend.main:app --port 8000' 启动（不要加 --reload）。"
        )

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost",       # Docker nginx
        "http://localhost:80",    # Docker nginx (explicit)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(plans.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(upload.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(studio.router, prefix="/api")
app.include_router(notes.router, prefix="/api")
app.include_router(resource.router, prefix="/api")
app.include_router(dev.router, prefix="/api")
app.include_router(provider.router, prefix="/api")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/migrate-local-data")
async def migrate_local_data(payload: dict):
    """一次性迁移端点：将前端 localStorage 旧数据导入 SQLite。"""
    logger = logging.getLogger("backend.main")
    imported = {"plans": 0, "messages": 0, "materials": 0, "progress": 0, "notes": 0, "generatedContents": 0, "searchHistory": 0}

    try:
        # 导入 plans
        for plan in payload.get("plans", []):
            if not plan.get("id"):
                continue
            existing = database.get_plan(plan["id"])
            if existing:
                continue
            plan.setdefault("createdAt", plan.get("lastAccessedAt", ""))
            plan.setdefault("description", "")
            plan.setdefault("sourceCount", 0)
            plan.setdefault("coverColor", "from-blue-400 to-indigo-600")
            plan.setdefault("totalDays", 0)
            plan.setdefault("completedDays", 0)
            try:
                database.create_plan(plan)
                imported["plans"] += 1
            except Exception as e:
                logger.warning("迁移 plan %s 失败: %s", plan.get("id"), e)

        # 导入 messages（按 planId 分组）
        for msg in payload.get("messages", []):
            if not msg.get("id") or not msg.get("planId"):
                continue
            try:
                database.insert_message(msg)
                imported["messages"] += 1
            except Exception as e:
                logger.warning("迁移 message %s 失败: %s", msg.get("id"), e)

        # 导入 materials
        for mat in payload.get("materials", []):
            if not mat.get("id") or not mat.get("planId"):
                continue
            try:
                database.insert_material(mat)
                imported["materials"] += 1
            except Exception as e:
                logger.warning("迁移 material %s 失败: %s", mat.get("id"), e)

        # 导入 studio 数据（progress, notes, generatedContents）
        for planId, studioData in payload.get("studio", {}).items():
            # progress
            days = studioData.get("allDays", [])
            if days:
                try:
                    database.upsert_progress(planId, days)
                    imported["progress"] += len(days)
                except Exception as e:
                    logger.warning("迁移 progress for plan %s 失败: %s", planId, e)

            # notes
            for note in studioData.get("notes", []):
                if not note.get("id"):
                    continue
                note["planId"] = planId
                try:
                    database.create_note(note)
                    imported["notes"] += 1
                except Exception as e:
                    logger.warning("迁移 note %s 失败: %s", note.get("id"), e)

            # generatedContents
            for gc in studioData.get("generatedContents", []):
                if not gc.get("id"):
                    continue
                gc["planId"] = planId
                try:
                    database.insert_generated_content(gc)
                    imported["generatedContents"] += 1
                except Exception as e:
                    logger.warning("迁移 generated content %s 失败: %s", gc.get("id"), e)

        # 导入 search history
        for entry in payload.get("searchHistory", []):
            if not entry.get("id"):
                continue
            try:
                database.insert_search_history(entry)
                imported["searchHistory"] += 1
            except Exception as e:
                logger.warning("迁移 search history %s 失败: %s", entry.get("id"), e)

    except Exception as e:
        logger.error("数据迁移失败: %s", e)
        return {"ok": False, "error": str(e), "imported": imported}

    logger.info("localStorage 数据迁移完成: %s", imported)
    return {"ok": True, "imported": imported}
