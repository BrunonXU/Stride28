"""
api_cache — Searcher 级 API 响应缓存

进程内内存字典实现，重启失效，不做跨进程共享或持久化。
与 SearchCache（最终结果缓存）独立运行，互不干扰。

职责边界：
- 只缓存 searcher 级原始 API 响应和 /extract 结果
- 不缓存 LLM 评估结果（QualityAssessor 输出）
- 不缓存最终聚合排序结果（SearchCache 职责）
"""

import hashlib
import logging
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# 模块级单例：进程内共享，跨 SearchOrchestrator 实例复用
_global_instance: Optional["APICache"] = None


class APICache:
    """Searcher 级 API 响应缓存。

    key = SHA-256(searcher_name | normalized_params)
    """

    DEFAULT_TTL = 3600  # 默认 1 小时

    # 各 searcher 可配置不同 TTL（秒）
    TTL_CONFIG: Dict[str, int] = {
        "tavily_search": 3600,      # Tavily /search 1 小时
        "tavily_extract": 7200,     # Tavily /extract 2 小时（正文不常变）
        "arxiv_search": 3600,       # arXiv 1 小时
        "github_search": 1800,      # GitHub 30 分钟（stars 变化快）
        "github_readme": 7200,      # GitHub README 2 小时
    }

    @classmethod
    def get_instance(cls) -> "APICache":
        """返回模块级单例，进程内共享，跨 SearchOrchestrator 实例复用。"""
        global _global_instance
        if _global_instance is None:
            _global_instance = cls()
            logger.info("APICache 单例已创建")
        return _global_instance

    def __init__(self) -> None:
        self._store: Dict[str, Tuple[float, Any]] = {}
        self._hits = 0
        self._misses = 0

    def get(self, searcher: str, **params: Any) -> Optional[Any]:
        """查询缓存。命中返回缓存值，未命中或过期返回 None。"""
        key = self._make_key(searcher, params)
        entry = self._store.get(key)
        if entry is None:
            self._misses += 1
            return None
        timestamp, value = entry
        ttl = self.TTL_CONFIG.get(searcher, self.DEFAULT_TTL)
        if time.time() - timestamp > ttl:
            del self._store[key]
            self._misses += 1
            return None
        self._hits += 1
        logger.info(f"APICache 命中: {searcher} (hits={self._hits}, misses={self._misses})")
        return value

    def set(self, searcher: str, value: Any, **params: Any) -> None:
        """写入缓存。"""
        key = self._make_key(searcher, params)
        self._store[key] = (time.time(), value)

    @staticmethod
    def _make_key(searcher: str, params: dict) -> str:
        """生成缓存 key：searcher + 规范化参数的 SHA-256。

        规范化规则：
        - key 按字母排序
        - 字符串 value 转小写并 strip
        - list value 排序后 join
        """
        normalized = []
        for k in sorted(params.keys()):
            v = params[k]
            if isinstance(v, str):
                v = v.lower().strip()
            elif isinstance(v, list):
                v = ",".join(sorted(str(x).lower() for x in v))
            normalized.append(f"{k}={v}")
        raw = f"{searcher}|{'|'.join(normalized)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @property
    def stats(self) -> Dict[str, int]:
        """返回缓存统计信息。"""
        return {
            "size": len(self._store),
            "hits": self._hits,
            "misses": self._misses,
        }

    def clear(self) -> None:
        """清空缓存。"""
        self._store.clear()
        self._hits = 0
        self._misses = 0
