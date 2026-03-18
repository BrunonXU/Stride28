"""
BiliBiliSearcher — B站视频搜索器

使用 httpx 调用 B站搜索 API 获取视频结果，不依赖 Playwright 浏览器。
API 失败时回退到构造 B站搜索链接作为降级结果。

调用方：SearchOrchestrator._search_single_platform()
"""

import logging
from typing import List, Optional
from urllib.parse import quote

import httpx

from src.specialists.browser_models import RawSearchResult

logger = logging.getLogger(__name__)


class BiliBiliSearcher:
    """B站视频搜索（httpx API 直连）"""

    API_URL = "https://api.bilibili.com/x/web-interface/search/type"
    TIMEOUT = 8  # 秒
    
    # 请求头，模拟浏览器访问
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    async def search(self, query: str, limit: int = 10) -> List[RawSearchResult]:
        """搜索 B站视频，返回 RawSearchResult 列表。
        
        Args:
            query: 搜索关键词
            limit: 返回结果数量限制
            
        Returns:
            RawSearchResult 列表，失败时返回降级搜索链接
        """
        try:
            results = await self._search_api(query, limit)
            if results:
                logger.info(f"B站 API 搜索成功: {len(results)} 条结果")
                return results
        except Exception as e:
            logger.warning(f"B站 API 搜索失败: {e}")
        
        # 降级：返回搜索链接
        return self._fallback_result(query)

    async def _search_api(self, query: str, limit: int) -> List[RawSearchResult]:
        """调用 B站搜索 API 获取视频结果。"""
        params = {
            "search_type": "video",
            "keyword": query,
            "page": 1,
            "page_size": min(limit, 50),  # B站 API 单页最多 50 条
        }
        
        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            response = await client.get(
                self.API_URL,
                params=params,
                headers=self.HEADERS,
            )
            response.raise_for_status()
            data = response.json()
        
        if data.get("code") != 0:
            raise ValueError(f"B站 API 返回错误: {data.get('message', 'unknown')}")
        
        result_list = data.get("data", {}).get("result", [])
        if not result_list:
            return []
        
        results = []
        for item in result_list[:limit]:
            result = self._parse_video_item(item)
            if result:
                results.append(result)
        
        return results

    def _parse_video_item(self, item: dict) -> Optional[RawSearchResult]:
        """解析单个视频搜索结果。"""
        try:
            bvid = item.get("bvid", "")
            aid = item.get("aid", "")
            title = self._clean_title(item.get("title", ""))
            
            if not title or (not bvid and not aid):
                return None
            
            # 构造视频 URL
            if bvid:
                url = f"https://www.bilibili.com/video/{bvid}"
            else:
                url = f"https://www.bilibili.com/video/av{aid}"
            
            # 提取互动指标
            play_count = self._safe_int(item.get("play", 0))
            danmaku_count = self._safe_int(item.get("danmaku", 0))
            favorites = self._safe_int(item.get("favorites", 0))
            likes = self._safe_int(item.get("like", 0))
            
            # 提取描述
            description = item.get("description", "") or item.get("desc", "")
            
            return RawSearchResult(
                title=title,
                url=url,
                platform="bilibili",
                resource_type="video",
                description=description[:500] if description else "",
                engagement_metrics={
                    "views": play_count,
                    "danmaku": danmaku_count,
                    "collected": favorites,
                    "likes": likes,
                    "play": play_count,  # 兼容字段
                },
            )
        except Exception as e:
            logger.debug(f"解析 B站视频项失败: {e}")
            return None

    def _clean_title(self, title: str) -> str:
        """清理标题中的 HTML 高亮标签。"""
        if not title:
            return ""
        # B站搜索结果标题可能包含 <em class="keyword"> 高亮标签
        import re
        return re.sub(r"<[^>]+>", "", title).strip()

    @staticmethod
    def _safe_int(value) -> int:
        """安全转换为整数。"""
        if value is None:
            return 0
        try:
            return int(value)
        except (ValueError, TypeError):
            return 0

    def _fallback_result(self, query: str) -> List[RawSearchResult]:
        """降级结果：返回 B站搜索链接。"""
        search_url = f"https://search.bilibili.com/all?keyword={quote(query)}"
        return [
            RawSearchResult(
                title=f"在 B站 搜索「{query}」",
                url=search_url,
                platform="bilibili",
                resource_type="video",
                description="点击链接在 B站 查看更多搜索结果",
                engagement_metrics={},
            )
        ]
