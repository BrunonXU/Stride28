"""
search_cache — 搜索结果内存缓存

基于 query + sorted platforms 生成 SHA-256 哈希键，支持 TTL 过期（默认 1 小时）。
避免短时间内重复搜索相同关键词浪费浏览器资源和 LLM 调用。

调用方：SearchOrchestrator
"""

import hashlib
import time
from typing import Dict, List, Optional, Tuple

from src.core.models import SearchResult


class SearchCache:
    """搜索结果本地缓存"""

    def __init__(self, ttl: int = 3600):
        self._ttl = ttl  # 缓存有效期（秒）
        self._store: Dict[str, Tuple[float, List[SearchResult]]] = {}

    def get(self, query: str, platforms: List[str]) -> Optional[List[SearchResult]]:
        """获取缓存结果，过期返回 None"""
        key = self._make_key(query, platforms)
        entry = self._store.get(key)
        if entry is None:
            return None
        timestamp, results = entry
        if time.time() - timestamp > self._ttl:
            del self._store[key]
            return None
        return results

    def set(self, query: str, platforms: List[str], results: List[SearchResult]) -> None:
        """设置缓存"""
        key = self._make_key(query, platforms)
        self._store[key] = (time.time(), results)

    @staticmethod
    def _make_key(query: str, platforms: List[str]) -> str:
        """生成缓存键：query + sorted platforms 的哈希"""
        raw = f"{query}|{'|'.join(sorted(platforms))}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
