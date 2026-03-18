"""
SessionContext — 懒加载会话上下文

每个 plan_id 对应一个独立的 SessionContext，按需初始化 TutorAgent 等重型对象。
"""

import logging
from typing import Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.agents.tutor import TutorAgent

logger = logging.getLogger(__name__)

_sessions: Dict[str, "SessionContext"] = {}


class SessionContext:
    """单个学习规划的会话上下文（懒加载）"""

    def __init__(self, plan_id: str):
        self.plan_id = plan_id
        self._tutor: Optional[TutorAgent] = None

    @property
    def tutor(self) -> "TutorAgent":
        if self._tutor is None:
            logger.info(f"[SessionContext] Initializing TutorAgent for plan {self.plan_id}")
            from src.agents.tutor import TutorAgent
            from src.providers.factory import ProviderFactory
            from backend import database
            import os

            # 从 settings 表读取用户选择的 provider/model
            provider_name = database.get_setting("llm_provider") or os.getenv("DEFAULT_PROVIDER", "deepseek")
            model = database.get_setting("llm_model") or os.getenv("DEFAULT_MODEL", "deepseek-chat")

            # API Key 只从 .env / os.environ 读取，不从 SQLite 读

            try:
                llm = ProviderFactory.create_llm(provider_name=provider_name, model=model)
            except Exception as e:
                logger.warning(f"[SessionContext] Failed to create {provider_name}/{model}: {e}, falling back to deepseek")
                llm = ProviderFactory.create_llm(provider_name="deepseek")

            self._tutor = TutorAgent(llm_provider=llm)
        return self._tutor



def get_session(plan_id: str) -> SessionContext:
    """获取或创建 plan_id 对应的 SessionContext"""
    if plan_id not in _sessions:
        _sessions[plan_id] = SessionContext(plan_id)
    return _sessions[plan_id]


def clear_session(plan_id: str) -> None:
    """清除 plan_id 对应的 SessionContext（删除规划时调用）"""
    _sessions.pop(plan_id, None)
