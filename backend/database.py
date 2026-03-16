"""
SQLite 数据访问层。
封装所有数据库连接管理和 CRUD 操作，作为唯一数据源。
"""

import json
import logging
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DB_PATH = os.getenv("DATA_DIR", "data") + "/app.db"
_connection: Optional[sqlite3.Connection] = None


def _to_camel(row: dict) -> dict:
    """snake_case → camelCase"""
    def convert(key: str) -> str:
        parts = key.split("_")
        return parts[0] + "".join(p.capitalize() for p in parts[1:])
    return {convert(k): v for k, v in row.items()}


def _to_snake(data: dict) -> dict:
    """camelCase → snake_case"""
    def convert(key: str) -> str:
        return re.sub(r"([A-Z])", r"_\1", key).lower()
    return {convert(k): v for k, v in data.items()}


def get_connection() -> sqlite3.Connection:
    """获取 SQLite 连接（单用户，复用同一连接）"""
    global _connection
    if _connection is None:
        os.makedirs(os.path.dirname(_DB_PATH) or ".", exist_ok=True)
        _connection = sqlite3.connect(_DB_PATH, check_same_thread=False)
        _connection.row_factory = sqlite3.Row
    return _connection


def init_db() -> None:
    """初始化数据库：创建表、启用 WAL 和外键"""
    conn = get_connection()
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS plans (
                id          TEXT PRIMARY KEY,
                title       TEXT NOT NULL,
                description TEXT DEFAULT '',
                source_count    INTEGER DEFAULT 0,
                last_accessed_at TEXT,
                cover_color TEXT DEFAULT 'from-blue-400 to-indigo-600',
                total_days      INTEGER DEFAULT 0,
                completed_days  INTEGER DEFAULT 0,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id          TEXT PRIMARY KEY,
                plan_id     TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
                role        TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                content     TEXT NOT NULL,
                sources     TEXT DEFAULT '[]',
                created_at  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_plan_id ON messages(plan_id);

            CREATE TABLE IF NOT EXISTS materials (
                id          TEXT PRIMARY KEY,
                plan_id     TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
                type        TEXT NOT NULL,
                name        TEXT NOT NULL,
                url         TEXT,
                status      TEXT NOT NULL DEFAULT 'parsing',
                added_at    TEXT NOT NULL,
                extra_data  TEXT DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_materials_plan_id ON materials(plan_id);

            CREATE TABLE IF NOT EXISTS progress (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id     TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
                day_number  INTEGER NOT NULL,
                title       TEXT NOT NULL,
                completed   INTEGER DEFAULT 0,
                tasks       TEXT DEFAULT '[]',
                UNIQUE(plan_id, day_number)
            );
            CREATE INDEX IF NOT EXISTS idx_progress_plan_id ON progress(plan_id);

            CREATE TABLE IF NOT EXISTS notes (
                id          TEXT PRIMARY KEY,
                plan_id     TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
                title       TEXT NOT NULL,
                content     TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_notes_plan_id ON notes(plan_id);

            CREATE TABLE IF NOT EXISTS generated_contents (
                id          TEXT PRIMARY KEY,
                plan_id     TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
                type        TEXT NOT NULL,
                title       TEXT NOT NULL,
                content     TEXT NOT NULL,
                created_at  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_generated_contents_plan_id ON generated_contents(plan_id);

            CREATE TABLE IF NOT EXISTS learner_profiles (
                id          TEXT PRIMARY KEY,
                plan_id     TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
                goal        TEXT DEFAULT '',
                duration    TEXT DEFAULT '',
                level       TEXT DEFAULT '',
                background  TEXT DEFAULT '',
                daily_hours TEXT DEFAULT '',
                extra       TEXT DEFAULT '{}',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                UNIQUE(plan_id)
            );
            CREATE INDEX IF NOT EXISTS idx_learner_profiles_plan_id ON learner_profiles(plan_id);

            CREATE TABLE IF NOT EXISTS search_history (
                id          TEXT PRIMARY KEY,
                plan_id     TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
                query       TEXT NOT NULL,
                platforms   TEXT DEFAULT '[]',
                results     TEXT DEFAULT '[]',
                result_count INTEGER DEFAULT 0,
                searched_at TEXT NOT NULL,
                status      TEXT DEFAULT 'done'
            );
            CREATE INDEX IF NOT EXISTS idx_search_history_plan_id ON search_history(plan_id);
        """)
        # Settings 表（Provider 配置等全局设置）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # Migration: add status column to search_history if missing
        try:
            conn.execute("ALTER TABLE search_history ADD COLUMN status TEXT DEFAULT 'done'")
            logger.info("Added status column to search_history")
        except sqlite3.OperationalError:
            pass  # column already exists

        # Migration: add search_results column to messages if missing
        try:
            conn.execute("ALTER TABLE messages ADD COLUMN search_results TEXT DEFAULT '[]'")
            logger.info("Added search_results column to messages")
        except sqlite3.OperationalError:
            pass  # column already exists

        # Migration: add sort_order column to materials if missing
        try:
            conn.execute("ALTER TABLE materials ADD COLUMN sort_order INTEGER DEFAULT 0")
            logger.info("Added sort_order column to materials")
        except sqlite3.OperationalError:
            pass  # column already exists

        # Migration: add viewed_at column to materials if missing
        try:
            conn.execute("ALTER TABLE materials ADD COLUMN viewed_at TEXT")
            logger.info("Added viewed_at column to materials")
        except sqlite3.OperationalError:
            pass  # column already exists

        # Episodic Memory: conversation_summaries 表
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversation_summaries (
                id               TEXT PRIMARY KEY,
                plan_id          TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
                summary_text     TEXT NOT NULL,
                message_count    INTEGER NOT NULL,
                start_message_id TEXT NOT NULL,
                end_message_id   TEXT NOT NULL,
                created_at       TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_conversation_summaries_plan_id
                ON conversation_summaries(plan_id);
        """)

        # 首次启动：如果 plans 表为空，注入示例数据
        _seed_demo_data(conn)

        logger.info("Database initialized successfully at %s", _DB_PATH)
    except sqlite3.Error as e:
        logger.error("Database initialization failed: %s", e)
        raise


def _seed_demo_data(conn: sqlite3.Connection) -> None:
    """首次启动时注入示例学习规划，让新用户看到完整成品效果。"""
    count = conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0]
    if count > 0:
        return

    seed_path = os.path.join(os.path.dirname(__file__), "demo_seed.json")
    if not os.path.exists(seed_path):
        logger.info("No demo_seed.json found, skipping demo data seeding")
        return

    try:
        with open(seed_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        with conn:
            # plan
            p = data["plan"]
            conn.execute(
                """INSERT INTO plans (id, title, description, source_count,
                   last_accessed_at, cover_color, total_days, completed_days, created_at)
                   VALUES (:id, :title, :description, :source_count,
                   :last_accessed_at, :cover_color, :total_days, :completed_days, :created_at)""",
                p,
            )

            # learner_profile
            lp = data.get("learner_profile")
            if lp:
                conn.execute(
                    """INSERT INTO learner_profiles (id, plan_id, goal, duration, level, background, daily_hours, extra, created_at, updated_at)
                       VALUES (:id, :plan_id, :goal, :duration, :level, :background, :daily_hours, :extra, :created_at, :updated_at)""",
                    lp,
                )

            # progress
            for d in data.get("progress", []):
                conn.execute(
                    "INSERT INTO progress (plan_id, day_number, title, completed, tasks) VALUES (?, ?, ?, ?, ?)",
                    (d["plan_id"], d["day_number"], d["title"], d["completed"], d["tasks"]),
                )

            # generated_contents
            for gc in data.get("generated_contents", []):
                conn.execute(
                    """INSERT INTO generated_contents (id, plan_id, type, title, content, created_at)
                       VALUES (:id, :plan_id, :type, :title, :content, :created_at)""",
                    gc,
                )

            # materials
            for m in data.get("materials", []):
                conn.execute(
                    """INSERT INTO materials (id, plan_id, type, name, url, status, added_at, extra_data)
                       VALUES (:id, :plan_id, :type, :name, :url, :status, :added_at, :extra_data)""",
                    m,
                )

            # messages
            for msg in data.get("messages", []):
                msg.setdefault("search_results", "[]")
                conn.execute(
                    """INSERT INTO messages (id, plan_id, role, content, sources, search_results, created_at)
                       VALUES (:id, :plan_id, :role, :content, :sources, :search_results, :created_at)""",
                    msg,
                )

            # search_history
            for sh in data.get("search_history", []):
                sh.setdefault("status", "done")
                conn.execute(
                    """INSERT INTO search_history (id, plan_id, query, platforms, results, result_count, searched_at, status)
                       VALUES (:id, :plan_id, :query, :platforms, :results, :result_count, :searched_at, :status)""",
                    sh,
                )

        logger.info("Demo data seeded successfully: plan '%s'", data["plan"]["title"])
    except Exception as e:
        logger.warning("Failed to seed demo data: %s", e)


# ---------------------------------------------------------------------------
# Plans CRUD
# ---------------------------------------------------------------------------

def create_plan(plan: dict) -> dict:
    conn = get_connection()
    data = _to_snake(plan)
    try:
        with conn:
            conn.execute(
                """INSERT INTO plans (id, title, description, source_count,
                   last_accessed_at, cover_color, total_days, completed_days, created_at)
                   VALUES (:id, :title, :description, :source_count,
                   :last_accessed_at, :cover_color, :total_days, :completed_days, :created_at)""",
                data,
            )
        return _to_camel(data)
    except sqlite3.IntegrityError as e:
        logger.warning("Plan creation failed: %s", e)
        raise ValueError(f"Plan creation failed: {e}")
    except sqlite3.Error as e:
        logger.error("Database error: %s", e)
        raise RuntimeError(f"Database error: {e}")


def get_all_plans() -> List[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM plans ORDER BY created_at DESC").fetchall()
    return [_to_camel(dict(r)) for r in rows]


def get_plan(plan_id: str) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
    return _to_camel(dict(row)) if row else None


def update_plan(plan_id: str, updates: dict) -> Optional[dict]:
    conn = get_connection()
    data = _to_snake(updates)
    if not data:
        return get_plan(plan_id)
    set_clause = ", ".join(f"{k} = :{k}" for k in data)
    data["id"] = plan_id
    try:
        with conn:
            cur = conn.execute(
                f"UPDATE plans SET {set_clause} WHERE id = :id", data
            )
        if cur.rowcount == 0:
            return None
        return get_plan(plan_id)
    except sqlite3.Error as e:
        logger.error("Database error: %s", e)
        raise RuntimeError(f"Database error: {e}")


def delete_plan(plan_id: str) -> bool:
    conn = get_connection()
    # Ensure foreign keys are on for cascade
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        with conn:
            cur = conn.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
        return cur.rowcount > 0
    except sqlite3.Error as e:
        logger.error("Database error: %s", e)
        raise RuntimeError(f"Database error: {e}")


# ---------------------------------------------------------------------------
# Messages CRUD
# ---------------------------------------------------------------------------

def insert_message(msg: dict) -> dict:
    conn = get_connection()
    data = _to_snake(msg)
    # Serialize JSON fields
    if "sources" in data and not isinstance(data["sources"], str):
        data["sources"] = json.dumps(data["sources"], ensure_ascii=False)
    if "search_results" in data and not isinstance(data["search_results"], str):
        data["search_results"] = json.dumps(data["search_results"], ensure_ascii=False)
    # 确保 search_results 有默认值
    data.setdefault("search_results", "[]")
    try:
        with conn:
            conn.execute(
                """INSERT INTO messages (id, plan_id, role, content, sources, search_results, created_at)
                   VALUES (:id, :plan_id, :role, :content, :sources, :search_results, :created_at)""",
                data,
            )
        # Return with deserialized fields
        result = dict(data)
        result["sources"] = json.loads(result.get("sources", "[]"))
        result["search_results"] = json.loads(result.get("search_results", "[]"))
        return _to_camel(result)
    except sqlite3.IntegrityError as e:
        logger.warning("Message insertion failed: %s", e)
        raise ValueError(f"Message insertion failed: {e}")
    except sqlite3.Error as e:
        logger.error("Database error: %s", e)
        raise RuntimeError(f"Database error: {e}")


def get_messages(plan_id: str) -> List[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM messages WHERE plan_id = ? ORDER BY created_at ASC",
        (plan_id,),
    ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["sources"] = json.loads(d.get("sources") or "[]")
        d["search_results"] = json.loads(d.get("search_results") or "[]")
        results.append(_to_camel(d))
    return results

def delete_messages(plan_id: str) -> int:
    """删除指定 plan 的所有消息，返回删除行数"""
    conn = get_connection()
    try:
        with conn:
            cur = conn.execute(
                "DELETE FROM messages WHERE plan_id = ?", (plan_id,)
            )
        return cur.rowcount
    except sqlite3.Error as e:
        logger.error("Database error: %s", e)
        raise RuntimeError(f"Database error: {e}")



# ---------------------------------------------------------------------------
# Materials CRUD
# ---------------------------------------------------------------------------

def insert_material(mat: dict) -> dict:
    conn = get_connection()
    data = _to_snake(mat)
    if "extra_data" in data and not isinstance(data["extra_data"], str):
        data["extra_data"] = json.dumps(data["extra_data"], ensure_ascii=False)
    try:
        with conn:
            conn.execute(
                """INSERT INTO materials (id, plan_id, type, name, url, status, added_at, extra_data)
                   VALUES (:id, :plan_id, :type, :name, :url, :status, :added_at, :extra_data)""",
                data,
            )
        result = dict(data)
        result["extra_data"] = json.loads(result.get("extra_data") or "{}")
        return _to_camel(result)
    except sqlite3.IntegrityError as e:
        logger.warning("Material insertion failed: %s", e)
        raise ValueError(f"Material insertion failed: {e}")
    except sqlite3.Error as e:
        logger.error("Database error: %s", e)
        raise RuntimeError(f"Database error: {e}")


def get_materials(plan_id: str) -> List[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM materials WHERE plan_id = ? ORDER BY sort_order ASC, added_at ASC",
        (plan_id,),
    ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["extra_data"] = json.loads(d.get("extra_data") or "{}")
        results.append(_to_camel(d))
    return results


def update_material_status(material_id: str, status: str) -> bool:
    conn = get_connection()
    try:
        with conn:
            cur = conn.execute(
                "UPDATE materials SET status = ? WHERE id = ?",
                (status, material_id),
            )
        return cur.rowcount > 0
    except sqlite3.Error as e:
        logger.error("Database error: %s", e)
        raise RuntimeError(f"Database error: {e}")


def get_material_extra_data(material_id: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT extra_data FROM materials WHERE id = ?", (material_id,)
        ).fetchone()
        if row and row["extra_data"]:
            return json.loads(row["extra_data"])
        return None
    except (sqlite3.Error, json.JSONDecodeError) as e:
        logger.error("Database error: %s", e)
        return None


def update_material_extra_data(material_id: str, extra_data: dict) -> bool:
    conn = get_connection()
    try:
        with conn:
            cur = conn.execute(
                "UPDATE materials SET extra_data = ? WHERE id = ?",
                (json.dumps(extra_data, ensure_ascii=False), material_id),
            )
        return cur.rowcount > 0
    except sqlite3.Error as e:
        logger.error("Database error: %s", e)
        raise RuntimeError(f"Database error: {e}")


def delete_material(material_id: str) -> bool:
    conn = get_connection()
    try:
        with conn:
            # Get plan_id before deleting
            row = conn.execute(
                "SELECT plan_id FROM materials WHERE id = ?", (material_id,)
            ).fetchone()
            if not row:
                return False
            plan_id = row["plan_id"]
            conn.execute("DELETE FROM materials WHERE id = ?", (material_id,))
            # Decrement plan's source_count
            conn.execute(
                "UPDATE plans SET source_count = MAX(source_count - 1, 0) WHERE id = ?",
                (plan_id,),
            )
        return True
    except sqlite3.Error as e:
        logger.error("Database error: %s", e)
        raise RuntimeError(f"Database error: {e}")


def update_material_order(plan_id: str, ordered_ids: List[str]) -> bool:
    """按前端传入的 id 顺序批量更新 sort_order。"""
    conn = get_connection()
    try:
        with conn:
            for idx, mid in enumerate(ordered_ids):
                conn.execute(
                    "UPDATE materials SET sort_order = ? WHERE id = ? AND plan_id = ?",
                    (idx, mid, plan_id),
                )
        return True
    except sqlite3.Error as e:
        logger.error("Database error: %s", e)
        raise RuntimeError(f"Database error: {e}")


# ---------------------------------------------------------------------------
# Progress CRUD
# ---------------------------------------------------------------------------

def upsert_progress(plan_id: str, days: list[dict]) -> None:
    conn = get_connection()
    try:
        with conn:
            for day in days:
                d = _to_snake(day)
                tasks = d.get("tasks", [])
                if not isinstance(tasks, str):
                    tasks = json.dumps(tasks, ensure_ascii=False)
                conn.execute(
                    """INSERT OR REPLACE INTO progress (plan_id, day_number, title, completed, tasks)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        plan_id,
                        d["day_number"],
                        d["title"],
                        1 if d.get("completed") else 0,
                        tasks,
                    ),
                )
            # Update plan's total_days
            conn.execute(
                "UPDATE plans SET total_days = ? WHERE id = ?",
                (len(days), plan_id),
            )
    except sqlite3.IntegrityError as e:
        logger.warning("Progress upsert failed: %s", e)
        raise ValueError(f"Progress upsert failed: {e}")
    except sqlite3.Error as e:
        logger.error("Database error: %s", e)
        raise RuntimeError(f"Database error: {e}")


def get_progress(plan_id: str) -> List[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM progress WHERE plan_id = ? ORDER BY day_number ASC",
        (plan_id,),
    ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["tasks"] = json.loads(d.get("tasks") or "[]")
        d["completed"] = bool(d["completed"])
        results.append(_to_camel(d))
    return results


def update_progress_completed(plan_id: str, day_number: int, completed: bool) -> bool:
    conn = get_connection()
    try:
        with conn:
            cur = conn.execute(
                "UPDATE progress SET completed = ? WHERE plan_id = ? AND day_number = ?",
                (1 if completed else 0, plan_id, day_number),
            )
            if cur.rowcount == 0:
                return False
            # Sync plan's completed_days
            count = conn.execute(
                "SELECT COUNT(*) FROM progress WHERE plan_id = ? AND completed = 1",
                (plan_id,),
            ).fetchone()[0]
            conn.execute(
                "UPDATE plans SET completed_days = ? WHERE id = ?",
                (count, plan_id),
            )
        return True
    except sqlite3.Error as e:
        logger.error("Database error: %s", e)
        raise RuntimeError(f"Database error: {e}")


def update_progress_tasks(plan_id: str, day_number: int, tasks: list[dict]) -> bool:
    conn = get_connection()
    try:
        with conn:
            cur = conn.execute(
                "UPDATE progress SET tasks = ? WHERE plan_id = ? AND day_number = ?",
                (json.dumps(tasks, ensure_ascii=False), plan_id, day_number),
            )
        return cur.rowcount > 0
    except sqlite3.Error as e:
        logger.error("Database error: %s", e)
        raise RuntimeError(f"Database error: {e}")


# ---------------------------------------------------------------------------
# Notes CRUD
# ---------------------------------------------------------------------------

def create_note(note: dict) -> dict:
    conn = get_connection()
    data = _to_snake(note)
    try:
        with conn:
            conn.execute(
                """INSERT INTO notes (id, plan_id, title, content, created_at, updated_at)
                   VALUES (:id, :plan_id, :title, :content, :created_at, :updated_at)""",
                data,
            )
        return _to_camel(data)
    except sqlite3.IntegrityError as e:
        logger.warning("Note creation failed: %s", e)
        raise ValueError(f"Note creation failed: {e}")
    except sqlite3.Error as e:
        logger.error("Database error: %s", e)
        raise RuntimeError(f"Database error: {e}")


def get_notes(plan_id: str) -> List[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM notes WHERE plan_id = ? ORDER BY updated_at DESC",
        (plan_id,),
    ).fetchall()
    return [_to_camel(dict(r)) for r in rows]


def update_note(note_id: str, updates: dict) -> Optional[dict]:
    conn = get_connection()
    data = _to_snake(updates)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    set_clause = ", ".join(f"{k} = :{k}" for k in data)
    data["id"] = note_id
    try:
        with conn:
            cur = conn.execute(
                f"UPDATE notes SET {set_clause} WHERE id = :id", data
            )
        if cur.rowcount == 0:
            return None
        row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        return _to_camel(dict(row)) if row else None
    except sqlite3.Error as e:
        logger.error("Database error: %s", e)
        raise RuntimeError(f"Database error: {e}")


def delete_note(note_id: str) -> bool:
    conn = get_connection()
    try:
        with conn:
            cur = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        return cur.rowcount > 0
    except sqlite3.Error as e:
        logger.error("Database error: %s", e)
        raise RuntimeError(f"Database error: {e}")


# ---------------------------------------------------------------------------
# Generated Contents CRUD
# ---------------------------------------------------------------------------

def insert_generated_content(content: dict) -> dict:
    conn = get_connection()
    data = _to_snake(content)
    try:
        with conn:
            conn.execute(
                """INSERT INTO generated_contents (id, plan_id, type, title, content, created_at)
                   VALUES (:id, :plan_id, :type, :title, :content, :created_at)""",
                data,
            )
        return _to_camel(data)
    except sqlite3.IntegrityError as e:
        logger.warning("Generated content insertion failed: %s", e)
        raise ValueError(f"Generated content insertion failed: {e}")
    except sqlite3.Error as e:
        logger.error("Database error: %s", e)
        raise RuntimeError(f"Database error: {e}")


def get_generated_contents(plan_id: str) -> List[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM generated_contents WHERE plan_id = ? ORDER BY created_at DESC",
        (plan_id,),
    ).fetchall()
    return [_to_camel(dict(r)) for r in rows]


def delete_generated_content(content_id: str) -> bool:
    conn = get_connection()
    try:
        with conn:
            cur = conn.execute("DELETE FROM generated_contents WHERE id = ?", (content_id,))
        return cur.rowcount > 0
    except sqlite3.Error as e:
        logger.error("Database error: %s", e)
        raise RuntimeError(f"Database error: {e}")


# ---------------------------------------------------------------------------
# Search History CRUD
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Learner Profiles CRUD
# ---------------------------------------------------------------------------

def upsert_learner_profile(profile: dict) -> dict:
    conn = get_connection()
    data = _to_snake(profile)
    # 自动生成 id（create_plan 同步调用时可能未提供）
    if not data.get("id"):
        data["id"] = str(uuid.uuid4())
    if "extra" in data and not isinstance(data["extra"], str):
        data["extra"] = json.dumps(data["extra"], ensure_ascii=False)
    now = datetime.now(timezone.utc).isoformat()
    data.setdefault("created_at", now)
    data.setdefault("extra", "{}")
    # 可选字段默认空字符串，避免 SQL 参数缺失
    data.setdefault("goal", "")
    data.setdefault("duration", "")
    data.setdefault("level", "")
    data.setdefault("background", "")
    data.setdefault("daily_hours", "")
    data["updated_at"] = now
    try:
        with conn:
            conn.execute(
                """INSERT INTO learner_profiles (id, plan_id, goal, duration, level, background, daily_hours, extra, created_at, updated_at)
                   VALUES (:id, :plan_id, :goal, :duration, :level, :background, :daily_hours, :extra, :created_at, :updated_at)
                   ON CONFLICT(plan_id) DO UPDATE SET
                     goal=excluded.goal, duration=excluded.duration, level=excluded.level,
                     background=excluded.background, daily_hours=excluded.daily_hours,
                     extra=excluded.extra, updated_at=excluded.updated_at""",
                data,
            )
        result = dict(data)
        result["extra"] = json.loads(result.get("extra") or "{}")
        return _to_camel(result)
    except sqlite3.Error as e:
        logger.error("Database error: %s", e)
        raise RuntimeError(f"Database error: {e}")


def get_learner_profile(plan_id: str) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM learner_profiles WHERE plan_id = ?", (plan_id,)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["extra"] = json.loads(d.get("extra") or "{}")
    return _to_camel(d)


def insert_search_history(entry: dict) -> dict:
    conn = get_connection()
    data = _to_snake(entry)
    if "platforms" in data and not isinstance(data["platforms"], str):
        data["platforms"] = json.dumps(data["platforms"], ensure_ascii=False)
    if "results" in data and not isinstance(data["results"], str):
        data["results"] = json.dumps(data["results"], ensure_ascii=False)
    if "status" not in data:
        data["status"] = "done"
    try:
        with conn:
            conn.execute(
                """INSERT INTO search_history (id, plan_id, query, platforms, results, result_count, searched_at, status)
                   VALUES (:id, :plan_id, :query, :platforms, :results, :result_count, :searched_at, :status)""",
                data,
            )
        result = dict(data)
        result["platforms"] = json.loads(result.get("platforms") or "[]")
        result["results"] = json.loads(result.get("results") or "[]")
        return _to_camel(result)
    except sqlite3.IntegrityError as e:
        logger.warning("Search history insertion failed: %s", e)
        raise ValueError(f"Search history insertion failed: {e}")
    except sqlite3.Error as e:
        logger.error("Database error: %s", e)
        raise RuntimeError(f"Database error: {e}")


def get_search_history(plan_id: str, limit: int = 20) -> List[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM search_history WHERE plan_id = ? ORDER BY searched_at DESC LIMIT ?",
        (plan_id, limit),
    ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["platforms"] = json.loads(d.get("platforms") or "[]")
        d["results"] = json.loads(d.get("results") or "[]")
        results.append(_to_camel(d))
    return results


def update_search_history(entry_id: str, patch: dict) -> Optional[dict]:
    """Update an existing search history entry (e.g. after search completes)."""
    conn = get_connection()
    data = _to_snake(patch)
    if "results" in data and not isinstance(data["results"], str):
        data["results"] = json.dumps(data["results"], ensure_ascii=False)
    if "platforms" in data and not isinstance(data["platforms"], str):
        data["platforms"] = json.dumps(data["platforms"], ensure_ascii=False)

    allowed = {"results", "result_count", "status"}
    sets = []
    params: dict = {}
    for k, v in data.items():
        if k in allowed:
            sets.append(f"{k} = :{k}")
            params[k] = v
    if not sets:
        return None
    params["id"] = entry_id
    try:
        with conn:
            cur = conn.execute(
                f"UPDATE search_history SET {', '.join(sets)} WHERE id = :id",
                params,
            )
        if cur.rowcount == 0:
            return None
        row = conn.execute("SELECT * FROM search_history WHERE id = ?", (entry_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["platforms"] = json.loads(d.get("platforms") or "[]")
        d["results"] = json.loads(d.get("results") or "[]")
        return _to_camel(d)
    except sqlite3.Error as e:
        logger.error("Database error: %s", e)
        raise RuntimeError(f"Database error: {e}")


def delete_single_search_history(entry_id: str) -> bool:
    """删除单条搜索历史。"""
    conn = get_connection()
    try:
        with conn:
            cur = conn.execute(
                "DELETE FROM search_history WHERE id = ?", (entry_id,)
            )
        return cur.rowcount > 0
    except sqlite3.Error as e:
        logger.error("Database error: %s", e)
        raise RuntimeError(f"Database error: {e}")


def delete_search_history(plan_id: str) -> bool:
    conn = get_connection()
    try:
        with conn:
            cur = conn.execute(
                "DELETE FROM search_history WHERE plan_id = ?", (plan_id,)
            )
        return cur.rowcount > 0
    except sqlite3.Error as e:
        logger.error("Database error: %s", e)
        raise RuntimeError(f"Database error: {e}")




# ---------------------------------------------------------------------------
# Settings KV store
# ---------------------------------------------------------------------------

def get_setting(key: str) -> Optional[str]:
    """获取全局设置值"""
    conn = get_connection()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def upsert_setting(key: str, value: str) -> None:
    """插入或更新全局设置"""
    conn = get_connection()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
        (key, value, value),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Conversation Summaries (Episodic Memory)
# ---------------------------------------------------------------------------

def insert_conversation_summary(summary: dict) -> dict:
    """插入对话摘要记录"""
    row = _to_snake(summary)
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                """INSERT INTO conversation_summaries
                   (id, plan_id, summary_text, message_count, start_message_id, end_message_id, created_at)
                   VALUES (:id, :plan_id, :summary_text, :message_count, :start_message_id, :end_message_id, :created_at)""",
                row,
            )
        return _to_camel(row)
    except sqlite3.Error as e:
        logger.error("Database error: %s", e)
        raise RuntimeError(f"Database error: {e}")


def get_conversation_summaries(plan_id: str) -> List[dict]:
    """获取该 plan 的所有摘要，按 created_at ASC（最早在前）"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM conversation_summaries WHERE plan_id = ? ORDER BY created_at ASC",
        (plan_id,),
    ).fetchall()
    return [_to_camel(dict(r)) for r in rows]


def get_latest_conversation_summary(plan_id: str) -> Optional[dict]:
    """获取该 plan 的最新一条摘要"""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM conversation_summaries WHERE plan_id = ? ORDER BY created_at DESC LIMIT 1",
        (plan_id,),
    ).fetchone()
    return _to_camel(dict(row)) if row else None


def delete_conversation_summary(summary_id: str) -> bool:
    """删除指定摘要（合并时用）"""
    conn = get_connection()
    try:
        with conn:
            cur = conn.execute(
                "DELETE FROM conversation_summaries WHERE id = ?", (summary_id,)
            )
        return cur.rowcount > 0
    except sqlite3.Error as e:
        logger.error("Database error: %s", e)
        raise RuntimeError(f"Database error: {e}")


def update_conversation_summary_text(
    summary_id: str,
    merged_text: str,
    new_start_message_id: str = "",
    new_message_count: int = 0,
) -> bool:
    """更新摘要文本（合并摘要链时用）"""
    conn = get_connection()
    try:
        with conn:
            cur = conn.execute(
                """UPDATE conversation_summaries
                   SET summary_text = ?, start_message_id = ?, message_count = ?
                   WHERE id = ?""",
                (merged_text, new_start_message_id, new_message_count, summary_id),
            )
        return cur.rowcount > 0
    except sqlite3.Error as e:
        logger.error("Database error: %s", e)
        raise RuntimeError(f"Database error: {e}")


def count_messages_after(plan_id: str, after_message_id: Optional[str] = None) -> int:
    """统计 plan 中在 after_message_id 之后的消息数。
    after_message_id 为 None 时返回该 plan 的总消息数。
    用 rowid 排序（插入顺序）。
    如果 after_message_id 对应的消息已被删除，回退到统计全部消息。
    """
    conn = get_connection()
    if after_message_id is None:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM messages WHERE plan_id = ?", (plan_id,)
        ).fetchone()
    else:
        # 先检查 after_message_id 是否还存在
        exists = conn.execute(
            "SELECT 1 FROM messages WHERE id = ?", (after_message_id,)
        ).fetchone()
        if not exists:
            # 消息已被删除（清空对话后的边界情况），回退到统计全部
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM messages WHERE plan_id = ?", (plan_id,)
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT COUNT(*) as cnt FROM messages
                   WHERE plan_id = ?
                     AND rowid > (SELECT rowid FROM messages WHERE id = ?)""",
                (plan_id, after_message_id),
            ).fetchone()
    return row["cnt"] if row else 0


def get_messages_range(
    plan_id: str,
    after_message_id: Optional[str] = None,
    exclude_last_n: int = 12,
) -> List[dict]:
    """获取 after_message_id 之后、排除最后 exclude_last_n 条的消息列表。
    这些就是待压缩的消息。用 rowid 排序。
    如果 after_message_id 对应的消息已被删除，回退到取全部消息。
    """
    conn = get_connection()

    # 检查 after_message_id 是否还存在，不存在则回退
    effective_after_id = after_message_id
    if effective_after_id is not None:
        exists = conn.execute(
            "SELECT 1 FROM messages WHERE id = ?", (effective_after_id,)
        ).fetchone()
        if not exists:
            effective_after_id = None

    if effective_after_id is None:
        # 取该 plan 全部消息，排除最后 N 条
        rows = conn.execute(
            """SELECT * FROM messages
               WHERE plan_id = ?
               ORDER BY rowid ASC""",
            (plan_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM messages
               WHERE plan_id = ?
                 AND rowid > (SELECT rowid FROM messages WHERE id = ?)
               ORDER BY rowid ASC""",
            (plan_id, effective_after_id),
        ).fetchall()

    # 排除最后 exclude_last_n 条（Working Memory 窗口）
    if exclude_last_n > 0 and len(rows) > exclude_last_n:
        rows = rows[:-exclude_last_n]
    elif exclude_last_n > 0:
        return []  # 消息数不够，没有可压缩的

    return [_to_camel(dict(r)) for r in rows]
