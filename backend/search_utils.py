"""
搜索相关公共工具函数

抽取 learner_context 构建逻辑，供侧边栏搜索和聊天搜索共用。
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def build_learner_context(plan_id: str, query: str) -> Optional["LearnerContext"]:
    """从数据库构建学习者上下文，用于个性化搜索评估和 query rewrite。

    Args:
        plan_id: 学习计划 ID
        query: 搜索关键词（填入 LearnerContext.query）

    Returns:
        LearnerContext 实例，构建失败返回 None
    """
    if not plan_id:
        return None

    try:
        from src.specialists.quality_assessor import LearnerContext
        from backend import database

        # 查询学习者画像
        profile = database.get_learner_profile(plan_id)
        # 查询学习进度，构建轻量摘要
        progress = database.get_progress(plan_id)
        plan_summary = ""
        if progress:
            total_days = len(progress)
            completed_days = sum(1 for d in progress if d.get("completed"))
            lines = []
            for d in progress:
                day_num = d.get("dayNumber", 0)
                title = d.get("title", "")
                done = d.get("completed", False)
                prefix = (
                    "\u2705" if done
                    else "\U0001f535" if day_num == completed_days + 1
                    else "  "
                )
                suffix = "\uff08\u5f53\u524d\uff09" if (not done and day_num == completed_days + 1) else ""
                lines.append(f"{prefix} Day {day_num}: {title}{suffix}")
            plan_summary = f"\u8fdb\u5ea6\uff1a\u7b2c{completed_days}\u5929/\u5171{total_days}\u5929\n" + "\n".join(lines)

        return LearnerContext(
            query=query,
            goal=profile.get("goal", "") if profile else "",
            level=profile.get("level", "") if profile else "",
            background=profile.get("background", "") if profile else "",
            daily_hours=profile.get("dailyHours", "") if profile else "",
            plan_summary=plan_summary,
        )
    except Exception as e:
        logger.warning(f"构建学习者上下文失败（降级为通用评估）: {e}")
        return None
