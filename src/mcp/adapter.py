"""MCP 小红书搜索适配器 —— 纯浏览器方案

不使用 httpx 调 API，所有操作都在 Playwright 浏览器内完成：
- 登录：persistent context + 扫码
- 搜索：导航到搜索页 + 提取 __INITIAL_STATE__
- 登录检测：检查 web_session cookie

参考：https://github.com/xpzouying/xiaohongshu-mcp
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
from pathlib import Path
from typing import List, Optional

from playwright.async_api import async_playwright, BrowserContext, Page

from src.mcp.models import SearchResultItem, SearchData

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_BROWSER_DATA = _PROJECT_ROOT / "browser_data" / "xhs"
_STEALTH_JS = _PROJECT_ROOT / "stealth.min.js"
_XHS_INDEX = "https://www.xiaohongshu.com/explore"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)


class LoginRequiredError(Exception):
    def __init__(self, platform: str = "xiaohongshu"):
        super().__init__(f"{platform} 未登录")
        self.platform = platform


class BrowserCrashError(Exception):
    def __init__(self, detail: str = ""):
        super().__init__(f"浏览器异常: {detail}")


# ============================================================
# XhsBrowserSearcher：纯浏览器搜索器
# ============================================================

class XhsBrowserSearcher:
    """纯浏览器小红书搜索器

    所有操作都在 Playwright persistent context 内完成，
    不使用 httpx，不调 API，不需要签名。
    """

    def __init__(self):
        self._pw_cm = None
        self._playwright = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._initialized = False

    async def init_browser(self, headless: bool = True):
        """启动 Playwright persistent context"""
        if self._initialized:
            return

        logger.info("MCP: 初始化小红书浏览器 (headless=%s)...", headless)
        self._pw_cm = async_playwright()
        self._playwright = await self._pw_cm.start()

        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(_BROWSER_DATA),
            headless=headless,
            viewport={"width": 1920, "height": 1080},
            user_agent=_UA,
        )
        if _STEALTH_JS.exists():
            await self._context.add_init_script(path=str(_STEALTH_JS))

        self._page = await self._context.new_page()
        self._initialized = True
        logger.info("MCP: 小红书浏览器就绪")

    async def check_auth(self) -> bool:
        """检查登录态：persistent context 目录存在 + web_session cookie"""
        if not _BROWSER_DATA.exists():
            return False
        try:
            await self.init_browser(headless=True)
            # 导航到首页触发 cookie 加载
            await self._page.goto(_XHS_INDEX, wait_until="domcontentloaded", timeout=30000)
            await self._page.wait_for_timeout(2000)
            cookies = await self._context.cookies()
            cookie_dict = {c["name"]: c["value"] for c in cookies}
            has_session = bool(cookie_dict.get("web_session"))
            logger.info("MCP: check_auth web_session=%s", "存在" if has_session else "不存在")
            return has_session
        except Exception as e:
            logger.warning("MCP: check_auth 异常: %s", e)
            return False

    async def search(self, query: str, limit: int = 10) -> SearchData:
        """在浏览器内执行搜索，从 __INITIAL_STATE__ 提取结果"""
        if not self._initialized:
            await self.init_browser(headless=True)

        search_url = self._make_search_url(query)
        logger.info("MCP: 导航到搜索页: %s", search_url)

        await self._page.goto(search_url, wait_until="domcontentloaded", timeout=30000)

        # 等待页面网络空闲 + __INITIAL_STATE__.search.feeds 有数据
        try:
            await self._page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass  # networkidle 超时不致命

        try:
            await self._page.wait_for_function(
                """() => {
                    if (!window.__INITIAL_STATE__ || !window.__INITIAL_STATE__.search) return false;
                    const feeds = window.__INITIAL_STATE__.search.feeds;
                    if (!feeds) return false;
                    const data = feeds.value !== undefined ? feeds.value : feeds._value;
                    return data && data.length > 0;
                }""",
                timeout=15000,
            )
        except Exception:
            logger.warning("MCP: __INITIAL_STATE__.search.feeds 未加载或为空，再等 3 秒...")
            await self._page.wait_for_timeout(3000)

        # 从 __INITIAL_STATE__ 提取搜索结果
        raw_json = await self._page.evaluate("""() => {
            if (window.__INITIAL_STATE__ &&
                window.__INITIAL_STATE__.search &&
                window.__INITIAL_STATE__.search.feeds) {
                const feeds = window.__INITIAL_STATE__.search.feeds;
                const feedsData = feeds.value !== undefined ? feeds.value : feeds._value;
                if (feedsData) {
                    return JSON.stringify(feedsData);
                }
            }
            return "";
        }""")

        if not raw_json:
            logger.warning("MCP: 搜索结果为空 (query='%s')", query)
            return SearchData(total_requested=limit, total_returned=0)

        # 解析 feeds JSON
        try:
            feeds = json.loads(raw_json)
        except json.JSONDecodeError as e:
            logger.error("MCP: feeds JSON 解析失败: %s", e)
            return SearchData(total_requested=limit, total_returned=0)

        items = self._parse_feeds(feeds, limit)
        logger.info("MCP: 搜索完成，返回 %d 条结果 (query='%s')", len(items), query)

        return SearchData(
            results=items,
            total_requested=limit,
            total_returned=len(items),
        )

    async def login(self, timeout: float = 300):
        """弹出可见浏览器让用户扫码登录"""
        # 关闭现有 headless 浏览器
        await self.close()

        logger.info("=" * 50)
        logger.info("MCP: 需要登录小红书，即将弹出浏览器窗口")
        logger.info("请手动登录，登录成功后自动检测（最多等 5 分钟）")
        logger.info("=" * 50)

        self._pw_cm = async_playwright()
        self._playwright = await self._pw_cm.start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(_BROWSER_DATA),
            headless=False,
            viewport={"width": 1920, "height": 1080},
            user_agent=_UA,
        )
        if _STEALTH_JS.exists():
            await self._context.add_init_script(path=str(_STEALTH_JS))

        self._page = await self._context.new_page()
        await self._page.goto(_XHS_INDEX, wait_until="domcontentloaded", timeout=30000)

        # 轮询等待 web_session cookie
        logged_in = False
        max_polls = int(timeout / 5)
        for i in range(max_polls):
            await self._page.wait_for_timeout(5000)
            cookies = await self._context.cookies()
            cookie_dict = {c["name"]: c["value"] for c in cookies}
            if cookie_dict.get("web_session"):
                logger.info("MCP: web_session 已检测到，登录成功！")
                logged_in = True
                break
            if i % 6 == 0:
                logger.info("等待登录中... (%ds / %ds)", (i + 1) * 5, int(timeout))

        if not logged_in:
            await self.close()
            raise RuntimeError(f"登录超时（{int(timeout)}秒）")

        # 登录成功，关闭可见浏览器，下次搜索时重新 headless 启动
        await self.close()

    async def close(self):
        """关闭浏览器"""
        self._initialized = False
        self._page = None
        try:
            if self._context:
                await self._context.close()
                self._context = None
            if self._pw_cm:
                await self._pw_cm.__aexit__(None, None, None)
                self._playwright = None
                self._pw_cm = None
        except Exception:
            pass

    # ---- 内部方法 ----

    @staticmethod
    def _make_search_url(keyword: str) -> str:
        params = urllib.parse.urlencode({
            "keyword": keyword,
            "source": "web_explore_feed",
        })
        return f"https://www.xiaohongshu.com/search_result?{params}"

    @staticmethod
    def _parse_feeds(feeds: list, limit: int) -> List[SearchResultItem]:
        """从 __INITIAL_STATE__ 的 feeds 数组解析搜索结果"""
        items = []
        for feed in feeds[:limit]:
            try:
                note_card = feed.get("note_card") or feed.get("noteCard") or {}
                # feed 可能直接包含 id，也可能在 note_card 里
                note_id = feed.get("id") or note_card.get("noteId") or ""
                xsec_token = feed.get("xsec_token") or feed.get("xsecToken") or ""

                display_title = (
                    note_card.get("display_title")
                    or note_card.get("displayTitle")
                    or ""
                )
                # 互动数据
                interact_info = note_card.get("interact_info") or note_card.get("interactInfo") or {}
                liked_count = interact_info.get("liked_count") or interact_info.get("likedCount") or "0"

                # 用户信息
                user = note_card.get("user") or {}
                nickname = user.get("nickname") or user.get("nick_name") or ""

                # 封面
                cover = note_card.get("cover") or {}
                cover_url = cover.get("url_default") or cover.get("urlDefault") or ""

                # 笔记类型
                note_type = note_card.get("type") or "normal"

                url = f"https://www.xiaohongshu.com/explore/{note_id}" if note_id else ""

                items.append(SearchResultItem(
                    id=str(note_id),
                    title=display_title,
                    url=url,
                    snippet=display_title,  # __INITIAL_STATE__ 没有摘要，用标题代替
                    cover_url=cover_url,
                    author=nickname,
                    likes=int(str(liked_count).replace("+", "").replace("万", "0000")) if liked_count else 0,
                    xsec_token=xsec_token,
                    note_type=note_type,
                ))
            except Exception as e:
                logger.warning("MCP: 解析 feed 失败: %s", e)
                continue
        return items
