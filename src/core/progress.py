"""
每日线性进度追踪器

维护以 DayProgress 为最小单位的学习进度，
数据持久化到 data/sessions/{session_id}.json 的 progress 键。
"""

import json
import logging
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel

from .models import LearningPlan

logger = logging.getLogger(__name__)

# Session 文件目录
SESSIONS_DIR = Path(__file__).parent.parent.parent / "data" / "sessions"


class DayProgress(BaseModel):
    """单天的学习进度"""
    day_number: int       # 天数编号，从 1 开始
    title: str            # 当天学习主题
    completed: bool = False  # 是否已完成


class ProgressTracker:
    """每日线性进度追踪器"""

    def __init__(self, session_id: str):
        self._session_id = session_id
        self._days: List[DayProgress] = []

    @property
    def days(self) -> List[DayProgress]:
        return list(self._days)

    def _session_path(self) -> Path:
        """返回当前 session 的 JSON 文件路径"""
        return SESSIONS_DIR / f"{self._session_id}.json"

    def init_from_plan(self, plan: LearningPlan) -> None:
        """从学习计划初始化每日进度列表"""
        self._days = [
            DayProgress(day_number=day.day_number, title=day.title)
            for day in plan.days
        ]

    def mark_day_completed(self, day_number: int) -> bool:
        """标记某天为已完成，返回是否成功"""
        for day in self._days:
            if day.day_number == day_number:
                day.completed = True
                self.save()
                return True
        return False

    def get_progress_summary(self) -> dict:
        """返回进度摘要"""
        completed = sum(1 for d in self._days if d.completed)
        total = len(self._days)
        current = next(
            (d.day_number for d in self._days if not d.completed), None
        )
        return {
            "total_days": total,
            "completed_days": completed,
            "percentage": completed / total if total > 0 else 0.0,
            "current_day": current,
            "days": list(self._days),
        }

    def save(self) -> None:
        """持久化到 session storage"""
        path = self._session_path()
        try:
            SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
            # 读取现有 session 数据
            session_data: dict = {}
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    session_data = json.load(f)

            # 写入 progress 键
            session_data["progress"] = {
                "days": [d.model_dump() for d in self._days]
            }

            with open(path, "w", encoding="utf-8") as f:
                json.dump(session_data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.error("Failed to save progress for session %s: %s", self._session_id, exc)

    def load(self) -> None:
        """从 session storage 加载"""
        path = self._session_path()
        try:
            if not path.exists():
                self._days = []
                return

            with open(path, "r", encoding="utf-8") as f:
                session_data = json.load(f)

            progress = session_data.get("progress")
            if progress and "days" in progress:
                self._days = [
                    DayProgress(**d) for d in progress["days"]
                ]
            else:
                self._days = []
        except Exception as exc:
            logger.error("Failed to load progress for session %s: %s, resetting", self._session_id, exc)
            self._days = []

    def reset(self) -> None:
        """重置为空白状态"""
        self._days = []
        self.save()
