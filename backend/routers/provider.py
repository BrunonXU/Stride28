"""
Provider 配置端点

GET  /api/provider/config  — 获取当前 provider 配置和可用列表
POST /api/provider/config  — 更新 provider 配置（热切换，不需要重启）

API Key 管理策略：
- .env 是唯一的 API Key 存储源（single source of truth）
- GET 返回 masked key（如 sk-****7673）
- POST 写入 .env 文件 + 设置当前进程 os.environ
- SQLite 只存 provider/model 选择，不存 API key
"""

import logging
import os
import re

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from backend import database
from src.providers.openai_compatible import PROVIDER_PRESETS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/provider", tags=["provider"])


# 所有可用 Provider 及其模型列表
AVAILABLE_PROVIDERS = {
    "tongyi": {
        "label": "通义千问 (Tongyi)",
        "models": ["qwen-turbo", "qwen-plus", "qwen-max"],
        "default_model": "qwen-turbo",
        "env_key": "DASHSCOPE_API_KEY",
    },
    **{
        name: {
            "label": {
                "openai": "OpenAI",
                "deepseek": "DeepSeek",
                "zhipu": "智谱 (Zhipu)",
            }.get(name, name),
            "models": preset["models"],
            "default_model": preset["default_model"],
            "env_key": preset["env_key"],
        }
        for name, preset in PROVIDER_PRESETS.items()
    },
}


def _mask_key(key: str) -> str:
    """将 API key 脱敏显示，如 sk-****7673"""
    if not key or len(key) < 8:
        return "****"
    return f"{key[:3]}****{key[-4:]}"


def _read_env_file() -> dict[str, str]:
    """读取 .env 文件，返回 {KEY: VALUE} 字典（保留原始值）"""
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
    result = {}
    if not os.path.exists(env_path):
        return result
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                result[k.strip()] = v.strip()
    return result


def _update_env_file(key: str, value: str) -> None:
    """更新 .env 文件中指定 key 的值，如果 key 不存在则追加"""
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
    if not os.path.exists(env_path):
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")
        return

    with open(env_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # 查找并替换已有的 key
    found = False
    pattern = re.compile(rf"^{re.escape(key)}\s*=")
    for i, line in enumerate(lines):
        if pattern.match(line.strip()):
            lines[i] = f"{key}={value}\n"
            found = True
            break

    if not found:
        # 追加到文件末尾
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(f"{key}={value}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


class ProviderConfigRequest(BaseModel):
    provider: str
    model: str
    apiKey: Optional[str] = None  # 可选，不传则保持 .env 现有值


@router.get("/config")
def get_provider_config():
    """返回当前 provider 配置和可用 provider 列表
    
    API Key 只从 .env / os.environ 读取，返回 masked 值。
    """
    current = database.get_setting("llm_provider") or os.getenv("DEFAULT_PROVIDER", "deepseek")
    current_model = database.get_setting("llm_model") or os.getenv("DEFAULT_MODEL", "deepseek-chat")

    providers_with_status = {}
    for name, info in AVAILABLE_PROVIDERS.items():
        env_key = info["env_key"]
        raw_key = os.getenv(env_key, "")
        has_key = bool(raw_key)
        providers_with_status[name] = {
            **info,
            "hasApiKey": has_key,
            "maskedKey": _mask_key(raw_key) if has_key else "",
        }

    return {
        "current": current,
        "currentModel": current_model,
        "providers": providers_with_status,
    }


@router.post("/config")
def update_provider_config(body: ProviderConfigRequest):
    """更新 provider 配置并热切换
    
    API Key 直接写入 .env 文件 + os.environ，不存 SQLite。
    """
    provider = body.provider.lower()

    if provider not in AVAILABLE_PROVIDERS:
        return {"error": f"Unknown provider: {provider}", "available": list(AVAILABLE_PROVIDERS.keys())}

    valid_models = AVAILABLE_PROVIDERS[provider]["models"]
    if body.model not in valid_models:
        return {"error": f"Invalid model: {body.model}", "validModels": valid_models}

    env_key = AVAILABLE_PROVIDERS[provider]["env_key"]

    # 如果提供了新 API key，先验证再写入
    if body.apiKey:
        # 临时设置环境变量用于验证
        old_env_value = os.environ.get(env_key)
        os.environ[env_key] = body.apiKey
        try:
            from src.providers.factory import ProviderFactory
            from src.providers.base import Message
            test_llm = ProviderFactory.create_llm(
                provider_name=provider, model=body.model, api_key=body.apiKey
            )
            test_llm.chat([Message(role="user", content="hi")])
        except Exception as e:
            # 验证失败，回滚环境变量
            if old_env_value is not None:
                os.environ[env_key] = old_env_value
            else:
                os.environ.pop(env_key, None)
            logger.warning(f"[provider] API Key 验证失败: {e}")
            return {"error": f"API Key 验证失败: {e}"}

        # 验证通过，写入 .env 文件
        _update_env_file(env_key, body.apiKey)
        logger.info(f"[provider] API Key 验证通过，已写入 .env")

    # 保存 provider 和 model 选择到 SQLite（这两个可以存 SQLite）
    database.upsert_setting("llm_provider", provider)
    database.upsert_setting("llm_model", body.model)

    # 热切换：清除所有 session，下次请求时会用新 provider 创建
    from backend.session_context import _sessions
    _sessions.clear()
    logger.info(f"[provider] 切换到 {provider}/{body.model}，已清除所有 session")

    return {"ok": True, "provider": provider, "model": body.model}
