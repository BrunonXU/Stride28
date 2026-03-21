"""
Tavily 通用网页搜索器

两段式策略：
1. /search 获取结果列表 + snippet（1 credit basic）
2. /extract 提取 top N 正文（5 URL/credit basic）

降级策略：
- API Key 未配置 → is_available() 返回 False
- /search 失败 → WARNING + 返回空列表
- /extract 失败 → 降级使用 /search 的 snippet 作为 content_snippet

Credit 消耗估算（basic 模式）：
- 单次搜索：1 credit（/search）+ 1 credit（/extract 5 URL）= 2 credits
- 免费额度 1000 credits/月 ≈ 500 次搜索
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urlparse

from src.specialists.browser_models import RawSearchResult

logger = logging.getLogger(__name__)


class TavilySearcher:
    """Tavily 通用网页搜索器（两段式：/search + /extract）"""

    DEFAULT_LIMIT = 10
    EXTRACT_TOP_N = 5  # 对 top 5 结果做 /extract，平衡质量和 credit 消耗

    def __init__(self, api_key: Optional[str] = None, api_cache=None):
        """初始化，api_key 从参数或 TAVILY_API_KEY 环境变量获取。"""
        self._api_key = api_key or os.environ.get("TAVILY_API_KEY")
        self._client = None  # 延迟初始化
        self._api_cache = api_cache

    def is_available(self) -> bool:
        """检查 API Key 是否已配置。"""
        return bool(self._api_key)

    def _ensure_client(self):
        """延迟初始化 AsyncTavilyClient。"""
        if self._client is None:
            if not self._api_key:
                raise RuntimeError("Tavily API Key 未配置")
            from tavily import AsyncTavilyClient
            self._client = AsyncTavilyClient(api_key=self._api_key)

    async def search(self, query: str, limit: int = 10) -> List[RawSearchResult]:
        """两段式搜索：/search + /extract。

        失败时返回空列表（静默降级）。
        """
        if not self.is_available():
            logger.warning("Tavily 搜索跳过: API Key 未配置")
            return []

        try:
            self._ensure_client()
        except Exception as e:
            logger.warning(f"Tavily client 初始化失败: {e}")
            return []

        # 第一段：/search（带缓存）
        try:
            if self._api_cache:
                cached = self._api_cache.get("tavily_search", query=query, limit=limit)
                if cached is not None:
                    search_results = cached
                    logger.debug(f"Tavily /search 缓存命中: query={query[:30]}")
                else:
                    search_results = await self._do_search(query, limit)
                    if search_results:
                        self._api_cache.set("tavily_search", search_results, query=query, limit=limit)
            else:
                search_results = await self._do_search(query, limit)
        except Exception as e:
            logger.warning(f"Tavily /search 失败: {e}")
            return []

        if not search_results:
            return []

        # 第二段：/extract（top N）
        urls_to_extract = [
            r["url"] for r in search_results[:self.EXTRACT_TOP_N]
            if r.get("url")
        ]
        extracted: Dict[str, str] = {}
        if urls_to_extract:
            # /extract 缓存：key 包含排序后的 URL 列表
            urls_key = ",".join(sorted(urls_to_extract))
            if self._api_cache:
                cached_ext = self._api_cache.get("tavily_extract", urls=urls_key)
                if cached_ext is not None:
                    extracted = cached_ext
                    logger.debug(f"Tavily /extract 缓存命中: {len(urls_to_extract)} URLs")
                else:
                    try:
                        extracted = await self._do_extract(urls_to_extract)
                        if extracted:
                            self._api_cache.set("tavily_extract", extracted, urls=urls_key)
                    except Exception as e:
                        logger.warning(f"Tavily /extract 失败，降级使用 snippet: {e}")
            else:
                try:
                    extracted = await self._do_extract(urls_to_extract)
                except Exception as e:
                    logger.warning(f"Tavily /extract 失败，降级使用 snippet: {e}")

        # 组装结果
        results = []
        for item in search_results:
            url = item.get("url", "")
            ext_content = extracted.get(url)
            parsed = self._parse_result(item, extracted=ext_content)
            if parsed:
                results.append(parsed)

        if results:
            logger.info(
                f"Tavily 搜索成功: {len(results)} 条结果"
                f"（{len(extracted)} 条已提取正文）"
            )
        return results

    async def _do_search(self, query: str, limit: int) -> List[dict]:
        """调用 Tavily /search API。"""
        response = await self._client.search(
            query=query,
            search_depth="basic",
            topic="general",
            max_results=min(limit, 20),
            include_answer=False,
        )
        return response.get("results", [])

    async def _do_extract(self, urls: List[str]) -> Dict[str, str]:
        """调用 Tavily /extract API 提取正文。

        返回 {url: extracted_content} 映射。
        失败的 URL 静默跳过。
        """
        response = await self._client.extract(urls=urls)
        result_map: Dict[str, str] = {}
        for item in response.get("results", []):
            url = item.get("url", "")
            content = item.get("raw_content", "") or item.get("text", "")
            if url and content:
                # 截取前 5000 字符，够 LLM 评估用
                result_map[url] = content[:5000]
        return result_map

    def _parse_result(
        self, item: dict, extracted: Optional[str] = None
    ) -> Optional[RawSearchResult]:
        """将 Tavily 结果转换为 RawSearchResult。"""
        title = item.get("title", "")
        url = item.get("url", "")
        if not title or not url:
            return None

        snippet = item.get("content", "")
        content = extracted or snippet
        now_utc = datetime.now(timezone.utc).isoformat()

        # 提取域名
        try:
            domain = urlparse(url).netloc
        except Exception:
            domain = ""

        return RawSearchResult(
            title=title.strip(),
            url=url,
            platform="tavily",
            resource_type="article",
            description=snippet[:300] if snippet else "",
            content_snippet=content,
            engagement_metrics={},
            source_tier="broad_web",
            author="",
            publish_time=item.get("published_date", ""),
            fetched_at=now_utc,
            extraction_mode="tavily_extract" if extracted else "tavily_search",
            source_metadata={
                "tavily_score": item.get("score", 0.0),
                "domain": domain,
            },
        )

    async def close(self):
        """清理资源。AsyncTavilyClient 无需显式关闭。"""
        self._client = None
