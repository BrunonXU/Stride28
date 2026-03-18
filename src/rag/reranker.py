"""
Reranker 模块 — Cross-Encoder 重排序

两阶段检索的第二阶段：对 embedding 初始召回的 passages 用 Cross-Encoder 精排，
返回按相关性降序排列的 top_k 结果。

架构：
- BaseReranker ABC：抽象接口，支持未来替换为 API 服务（Cohere 等）
- LocalReranker：基于 BAAI/bge-reranker-v2-m3 的本地推理
- get_reranker()：懒加载全局单例工厂函数

降级策略：
- FlagEmbedding 未安装 → 返回 None，上层降级为 embedding-only
- 模型加载失败（OOM/下载失败）→ 返回 None，不重试
- RERANKER_ENABLED=false → 直接返回 None
"""

from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class RerankResult:
    """Reranker 重排序结果"""
    index: int      # 原始 passage 在输入列表中的位置
    score: float    # reranker 相关性分数（normalized）
    text: str       # passage 原文


class BaseReranker(ABC):
    """Reranker 抽象基类，支持未来替换为 API 服务（Cohere 等）"""

    @abstractmethod
    def rerank(self, query: str, passages: List[str], top_k: int) -> List[RerankResult]:
        """对 passages 按与 query 的相关性重排序，返回 top_k 个结果（按 score 降序）。"""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """检查 reranker 是否可用（模型已加载 / API 可达）。"""
        ...


class LocalReranker(BaseReranker):
    """基于 BAAI/bge-reranker-v2-m3 的本地 Cross-Encoder reranker。

    使用 FlagEmbedding 库加载模型，fp16 推理。
    单条 compute_score 返回 float，多条返回 list，内部统一处理。
    """

    def __init__(self, model_name_or_path: str = "BAAI/bge-reranker-v2-m3"):
        from FlagEmbedding import FlagReranker
        self._model = FlagReranker(model_name_or_path, use_fp16=True)
        logger.info("[Reranker] 模型加载完成: %s", model_name_or_path)

    def rerank(self, query: str, passages: List[str], top_k: int) -> List[RerankResult]:
        if not passages:
            return []

        t0 = time.perf_counter()

        # FlagReranker.compute_score 接受 [[query, passage], ...] 对
        pairs = [[query, p] for p in passages]
        scores = self._model.compute_score(pairs, normalize=True)

        # compute_score 单条时返回 float，多条返回 list
        if isinstance(scores, (int, float)):
            scores = [scores]

        # 按 score 降序排序，取 top_k
        indexed = [(i, s, passages[i]) for i, s in enumerate(scores)]
        indexed.sort(key=lambda x: x[1], reverse=True)

        results = [
            RerankResult(index=i, score=s, text=t)
            for i, s, t in indexed[:top_k]
        ]

        ms = round((time.perf_counter() - t0) * 1000, 1)
        logger.info("[Reranker] %d passages → top_%d in %sms", len(passages), top_k, ms)
        return results

    def is_available(self) -> bool:
        return self._model is not None


# ---------------------------------------------------------------------------
# 懒加载工厂函数（全局单例）
# ---------------------------------------------------------------------------

_reranker_instance: Optional[BaseReranker] = None
_reranker_initialized: bool = False  # 区分"未初始化"和"初始化失败返回 None"


def get_reranker() -> Optional[BaseReranker]:
    """获取全局 reranker 实例（懒加载单例）。

    - 首次调用时尝试加载模型
    - 加载失败返回 None（后续调用不重试，避免重复报错）
    - RERANKER_ENABLED=false 时直接返回 None
    - 用户可通过重启后端触发重新加载
    """
    global _reranker_instance, _reranker_initialized

    if _reranker_initialized:
        return _reranker_instance

    _reranker_initialized = True

    # 环境变量开关
    if os.getenv("RERANKER_ENABLED", "true").lower() == "false":
        logger.info("[Reranker] Disabled: RERANKER_ENABLED=false")
        return None

    # 尝试加载
    model_path = os.getenv("RERANKER_MODEL_PATH", "BAAI/bge-reranker-v2-m3")
    try:
        _reranker_instance = LocalReranker(model_name_or_path=model_path)
        logger.info("[Reranker] Enabled: %s", model_path)
    except ImportError:
        logger.warning("[Reranker] Disabled: FlagEmbedding 未安装 (pip install FlagEmbedding)")
    except Exception as e:
        logger.warning("[Reranker] Disabled: 模型加载失败 - %s", e)

    return _reranker_instance
