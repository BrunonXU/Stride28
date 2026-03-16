"""
BrowserAgent - 基于 Playwright 的浏览器代理

管理 Playwright 浏览器实例，执行页面操作，支持 API 响应拦截。
基于 POC (scripts/poc_xhs_parallel.py) 的验证结果实现。

核心功能：
- 启动带反检测配置的 Chromium 浏览器
- 混合模式搜索（浏览器 + API 响应拦截）
- 并行详情页获取（asyncio.Semaphore 控制并发）
- Cookie 持久化与登录状态管理
- 三级回退正文提取（API JSON → __INITIAL_STATE__ → DOM）
"""

import asyncio
import json
import logging
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from src.specialists.browser_models import RawSearchResult, ResourceDetail
from src.specialists.platform_configs import PlatformConfig
from src.specialists.resource_collector import ResourceCollector

logger = logging.getLogger(__name__)

# User-Agent 池
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/17.2",
]


def _random_delay() -> float:
    """生成 [1.0, 3.0] 秒的随机延迟值。"""
    return random.uniform(BrowserAgent.MIN_DELAY, BrowserAgent.MAX_DELAY)


class BrowserAgent:
    """基于 Playwright 的浏览器代理，支持混合模式（浏览器 + API 拦截）。

    混合模式用 Playwright 浏览器执行搜索（浏览器自带签名），
    通过 page.on("response") 拦截 API 响应获取结构化 JSON 数据。
    """

    PAGE_TIMEOUT = 15_000  # 页面加载超时（毫秒）
    MIN_DELAY = 1.0  # 最小操作间隔（秒）
    MAX_DELAY = 3.0  # 最大操作间隔（秒）
    MIN_PLATFORM_INTERVAL = 2.0  # 同平台最小请求间隔（秒）
    DETAIL_MAX_RETRIES = 2  # 详情页最大重试次数
    DETAIL_CONCURRENCY = 3  # 详情页并行获取的最大 tab 数
    SEARCH_FULL_COUNT = 60  # 搜索全量获取数（滚动加载）
    DETAIL_TOP_K = 20  # 获取详情的 top K 条结果
    SCROLL_COUNT = 2  # 搜索页滚动次数（减少等待时间）
    SCROLL_PX = 800  # 每次滚动像素
    DETAIL_SCROLL_COUNT = 3  # 详情页滚动次数（触发评论加载）
    DETAIL_SCROLL_PX = 500  # 详情页每次滚动像素

    def __init__(self) -> None:
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        # 拦截到的搜索 API 响应
        self._intercepted_search: List[dict] = []
        # note_id → 评论列表
        self._intercepted_comments: Dict[str, List[dict]] = {}
        # note_id → 详情数据
        self._intercepted_details: Dict[str, dict] = {}
        # 捕获的签名 headers
        self._captured_headers: Dict[str, str] = {}
        # 同平台上次请求时间戳
        self._last_platform_request: Dict[str, float] = {}
        # 评论锁（懒加载，避免在无事件循环的线程中初始化失败）
        self._comment_lock: Optional[asyncio.Lock] = None
        # 浏览器启动锁，防止并发 launch
        self._launch_lock: Optional[asyncio.Lock] = None

    def _get_launch_lock(self) -> asyncio.Lock:
        """懒加载启动锁，确保在有事件循环的上下文中创建。"""
        if self._launch_lock is None:
            self._launch_lock = asyncio.Lock()
        return self._launch_lock

    def _get_comment_lock(self) -> asyncio.Lock:
        """懒加载评论锁，确保在有事件循环的上下文中创建。"""
        if self._comment_lock is None:
            self._comment_lock = asyncio.Lock()
        return self._comment_lock

    # ------------------------------------------------------------------
    # launch / close
    # ------------------------------------------------------------------

    async def launch(self, config: PlatformConfig, allow_interactive_login: bool = True) -> None:
        """启动浏览器实例（带反检测配置），如需登录则加载 Cookie。

        - 有 Cookie 且有效时窗口隐藏运行（offscreen），用户看不到
        - 不需要登录的平台也隐藏运行
        - 没有 Cookie 或 Cookie 失效时：
          - allow_interactive_login=True: 弹出可见浏览器让用户手动登录（最多等 3 分钟）
          - allow_interactive_login=False: 直接跳过，不弹窗（搜索流程中使用）
        
        使用 headless="new"（Chromium 新版无头模式）隐藏运行，反爬检测能力接近有头模式。
        仅在需要用户手动登录时才用 headless=False 弹出可见窗口。
        """
        try:
            from playwright.async_api import async_playwright

            # 判断是否有 cookie 文件
            has_cookie_file = False
            if config.requires_login and config.cookie_file:
                cookie_path = Path(config.cookie_file)
                has_cookie_file = cookie_path.exists()

            # 是否需要用户可见（仅首次登录时）
            needs_visible = (config.requires_login and config.cookie_file and not has_cookie_file)
            hidden_mode = not needs_visible  # 有 cookie 或不需要登录 → 隐藏
            launch_args = ["--disable-blink-features=AutomationControlled"]

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=hidden_mode,  # True=无头模式（新版Playwright默认用新引擎），False=弹窗登录
                args=launch_args,
            )

            user_agent = random.choice(_USER_AGENTS)
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=user_agent,
                locale="zh-CN",
            )

            # 反检测：覆盖 webdriver 属性
            await self._context.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )

            # 加载 Cookie 并验证
            if config.requires_login and config.cookie_file:
                cookie_path = Path(config.cookie_file)
                need_login = True

                if cookie_path.exists():
                    cookies = json.loads(cookie_path.read_text(encoding="utf-8"))
                    await self._context.add_cookies(cookies)
                    logger.info(f"已加载 {len(cookies)} 条 Cookie ({config.name})")

                    # 验证 cookie 是否有效
                    is_valid = await self._verify_cookie_valid(config)
                    if is_valid:
                        need_login = False
                    else:
                        logger.warning(f"Cookie 已失效 ({config.name})，需要重新登录")
                        cookie_path.unlink(missing_ok=True)
                        # 清除浏览器中的旧 cookie
                        await self._context.clear_cookies()

                if need_login:
                    if not allow_interactive_login:
                        logger.warning(f"Cookie 失效且不允许交互登录 ({config.name})，跳过该平台")
                        # 清理已启动的浏览器资源
                        try:
                            await self._browser.close()
                            await self._playwright.stop()
                        except Exception:
                            pass
                        self._browser = None
                        self._context = None
                        self._playwright = None
                        return

                    # 如果当前是隐藏模式，需要关闭重新以可见模式启动
                    if hidden_mode:
                        await self._browser.close()
                        self._browser = await self._playwright.chromium.launch(
                            headless=False,
                            args=["--disable-blink-features=AutomationControlled"],
                        )
                        self._context = await self._browser.new_context(
                            viewport={"width": 1280, "height": 900},
                            user_agent=user_agent,
                            locale="zh-CN",
                        )
                        await self._context.add_init_script(
                            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
                        )

                    logger.info(f"将弹出浏览器供用户登录 ({config.name})")
                    await self._interactive_login(config, cookie_path)

            logger.info(f"浏览器已启动 (UA: {user_agent[:50]}...)")
        except Exception as e:
            logger.error(f"浏览器启动失败: {e}", exc_info=True)
            # 确保清理资源
            try:
                if self._browser:
                    await self._browser.close()
                if self._playwright:
                    await self._playwright.stop()
            except Exception:
                pass
            self._browser = None
            self._context = None
            self._playwright = None

    async def _verify_cookie_valid(self, config: PlatformConfig) -> bool:
        """验证 cookie 是否有效：访问小红书搜索页，检查是否能正常搜索。

        检测策略：直接访问搜索页面，检查是否弹出登录弹窗或二维码。
        比检查首页更可靠，因为搜索页面的登录检查更严格。
        """
        if config.name != "xiaohongshu":
            return True
        page = await self._context.new_page()
        try:
            # 直接访问搜索页面（比首页更能反映真实登录状态）
            await page.goto(
                "https://www.xiaohongshu.com/search_result?keyword=test&source=web_search_result_note",
                wait_until="domcontentloaded",
                timeout=15_000,
            )
            await asyncio.sleep(3)

            # 检查是否有二维码登录弹窗（最可靠的失效信号）
            validation = await page.evaluate("""() => {
                // 检查二维码登录弹窗
                const qrLogin = document.querySelector('[class*="qrcode"], [class*="login-container"], [class*="login-modal"]');
                if (qrLogin) {
                    const rect = qrLogin.getBoundingClientRect();
                    if (rect.width > 50 && rect.height > 50) {
                        return {valid: false, reason: 'qrcode_login_popup'};
                    }
                }
                // 检查是否有搜索结果或搜索相关的 DOM 元素
                const noteItems = document.querySelectorAll('section.note-item, [data-note-id], .note-item');
                if (noteItems.length > 0) {
                    return {valid: true, reason: 'search_results_visible'};
                }
                // 检查 cookie 中是否有 web_session
                if (document.cookie.includes('web_session')) {
                    return {valid: true, reason: 'web_session_present'};
                }
                // 没有明确信号
                return {valid: false, reason: 'no_results_no_session'};
            }""")

            is_valid = validation.get("valid", False)
            reason = validation.get("reason", "unknown")
            if is_valid:
                logger.info(f"Cookie 验证通过（{reason}）")
            else:
                logger.info(f"Cookie 验证失败（{reason}）")
            return is_valid
        except Exception as e:
            logger.warning(f"Cookie 验证异常: {e}")
            # 验证异常时倾向于尝试使用，让 search_platform 自己处理
            return True
        finally:
            await page.close()

    async def _interactive_login(self, config: PlatformConfig, cookie_path: Path) -> None:
        """弹出浏览器让用户手动登录小红书，等待最多 3 分钟。

        检测方式：每 3 秒轮询一次，检查"登录"按钮是否消失。
        比 wait_for_selector 更可靠，不会误匹配其他元素。
        """
        page = await self._context.new_page()
        logger.info(
            f"请在弹出的浏览器中登录 {config.name}，"
            f"登录成功后会自动保存 Cookie（最多等待 3 分钟）"
        )
        try:
            await page.goto("https://www.xiaohongshu.com", wait_until="domcontentloaded")
            await asyncio.sleep(3)

            # 轮询检测登录状态（最多 3 分钟）
            max_wait = 180  # 秒
            poll_interval = 3  # 秒
            elapsed = 0
            logged_in = False

            while elapsed < max_wait:
                try:
                    has_login_btn = await page.evaluate("""() => {
                        const btns = document.querySelectorAll('button, a, span, div');
                        for (const el of btns) {
                            const t = (el.textContent || '').trim();
                            if (t === '登录' || t === '立即登录' || t === '登录/注册') {
                                const rect = el.getBoundingClientRect();
                                if (rect.width > 0 && rect.height > 0) {
                                    return true;
                                }
                            }
                        }
                        return false;
                    }""")
                    if not has_login_btn:
                        # 登录按钮消失了，再等 2 秒确认 cookie 稳定
                        await asyncio.sleep(2)
                        logged_in = True
                        break
                except Exception:
                    pass
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

            if logged_in:
                cookies = await self._context.cookies()
                if cookies:
                    cookie_path.parent.mkdir(parents=True, exist_ok=True)
                    cookie_path.write_text(
                        json.dumps(cookies, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    logger.info(
                        f"登录成功，已保存 {len(cookies)} 条 Cookie 到 {config.cookie_file}"
                    )
            else:
                logger.warning("等待登录超时（3分钟），请重试")
        except Exception as e:
            logger.warning(f"登录流程异常: {e}")
        finally:
            await page.close()

    async def close(self) -> None:
        """关闭浏览器实例，保存 Cookie，释放资源。"""
        try:
            if self._context:
                try:
                    cookies = await self._context.cookies()
                    if cookies:
                        cookie_path = Path("scripts/.xhs_cookies.json")
                        cookie_path.parent.mkdir(parents=True, exist_ok=True)
                        cookie_path.write_text(
                            json.dumps(cookies, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                        logger.info(f"已保存 {len(cookies)} 条 Cookie")
                except Exception as e:
                    logger.debug(f"保存 Cookie 失败: {e}")

            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.error(f"关闭浏览器失败: {e}")
        finally:
            self._browser = None
            self._context = None
            self._playwright = None

    # ------------------------------------------------------------------
    # API interception callbacks
    # ------------------------------------------------------------------

    async def _intercept_response(self, response: Any) -> None:
        """API 响应拦截回调，提取搜索结果、详情和评论的 JSON 数据。"""
        url = response.url
        try:
            if "/api/sns/web/v1/search/notes" in url and response.status == 200:
                data = await response.json()
                if data.get("success") or data.get("code") == 0:
                    items = data.get("data", {}).get("items", [])
                    self._intercepted_search.extend(items)
                    logger.debug(
                        f"[拦截] 搜索: +{len(items)} 条 (累计 {len(self._intercepted_search)})"
                    )

            elif "/api/sns/web/v2/comment/page" in url and response.status == 200:
                data = await response.json()
                if data.get("success") or data.get("code") == 0:
                    comments = data.get("data", {}).get("comments", [])
                    m = re.search(r"note_id=([a-f0-9]+)", url)
                    if m:
                        nid = m.group(1)
                        async with self._get_comment_lock():
                            self._intercepted_comments[nid] = comments
                        logger.debug(f"[拦截] 评论 {nid}: {len(comments)} 条")

            elif "/api/sns/web/v1/feed" in url and response.status == 200:
                data = await response.json()
                if data.get("success") or data.get("code") == 0:
                    feed_items = data.get("data", {}).get("items", [])
                    for fi in feed_items:
                        nid = fi.get("id", "")
                        if nid:
                            self._intercepted_details[nid] = fi
                            logger.debug(f"[拦截] 详情 {nid}")
        except Exception:
            pass

    async def _intercept_request(self, route: Any, request: Any) -> None:
        """请求拦截回调，捕获签名 headers（x-s, x-t, x-s-common）。"""
        try:
            headers = request.headers
            for key in ("x-s", "x-t", "x-s-common"):
                if key in headers:
                    self._captured_headers[key] = headers[key]
        except Exception:
            pass
        await route.continue_()

    # ------------------------------------------------------------------
    # Platform interval enforcement
    # ------------------------------------------------------------------

    async def _enforce_platform_interval(self, platform: str) -> None:
        """确保同平台连续请求间隔不少于 MIN_PLATFORM_INTERVAL 秒。"""
        now = time.time()
        last = self._last_platform_request.get(platform, 0.0)
        wait = self.MIN_PLATFORM_INTERVAL - (now - last)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_platform_request[platform] = time.time()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search_platform(
        self, query: str, config: PlatformConfig
    ) -> List[RawSearchResult]:
        """在指定平台执行搜索，返回原始结果。

        对于 use_hybrid_mode=True 的平台，注册 API 响应拦截器，
        从拦截到的 JSON 中提取结构化数据。
        """
        if not self._context:
            # 尝试自动启动浏览器（可能是 close 后重新搜索的场景）
            logger.warning("浏览器未启动，尝试自动启动...")
            try:
                async with self._get_launch_lock():
                    if not self._context:  # double-check after acquiring lock
                        await self.launch(config, allow_interactive_login=False)
            except Exception as e:
                logger.error(f"自动启动浏览器失败: {e}")
            if not self._context:
                logger.error("浏览器启动失败，无法搜索")
                return []

        await self._enforce_platform_interval(config.name)

        # 清空上次搜索的拦截数据
        self._intercepted_search.clear()

        page = await self._context.new_page()
        page.set_default_timeout(self.PAGE_TIMEOUT)

        try:
            # 注册 API 响应拦截器（混合模式）
            if config.use_hybrid_mode:
                page.on("response", self._intercept_response)

            # 打开搜索页
            search_url = config.search_url_template.format(query=quote(query))
            logger.info(f"搜索 {config.name}: {query}")
            try:
                await page.goto(
                    search_url, wait_until="domcontentloaded", timeout=self.PAGE_TIMEOUT
                )
            except Exception as e:
                logger.warning(f"搜索页加载异常 ({config.name}): {e}")

            await asyncio.sleep(_random_delay())

            # 检查登录状态
            if config.requires_login:
                logged_in = await self.ensure_logged_in(page, config)
                if not logged_in:
                    logger.warning(f"登录失效 ({config.name})，跳过搜索")
                    return []

            # 检查验证码/反爬页面
            if await self._detect_captcha(page):
                logger.warning(f"检测到验证码/反爬页面 ({config.name})，跳过")
                return []

            # 滚动加载更多结果
            for i in range(self.SCROLL_COUNT):
                await page.evaluate(f"window.scrollBy(0, {self.SCROLL_PX})")
                await asyncio.sleep(random.uniform(1.5, 2.5))

            # 提取结果：优先混合模式 > JS 提取 > CSS 提取
            if config.use_hybrid_mode and self._intercepted_search:
                results = ResourceCollector.extract_from_intercepted_json(
                    self._intercepted_search, config
                )
                logger.info(f"混合模式提取 {len(results)} 条结果 ({config.name})")
            elif config.use_js_extraction:
                results = await ResourceCollector.extract_search_results_js(page, config)
                logger.info(f"JS 提取 {len(results)} 条结果 ({config.name})")
            else:
                results = await ResourceCollector.extract_search_results(page, config)
                logger.info(f"CSS 提取 {len(results)} 条结果 ({config.name})")

            return results

        except Exception as e:
            logger.error(f"搜索失败 ({config.name}): {e}")
            return []
        finally:
            try:
                await page.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Detail fetching
    # ------------------------------------------------------------------

    async def fetch_details_parallel(
        self, notes: List[RawSearchResult], config: PlatformConfig, top_k: int = 20
    ) -> List[RawSearchResult]:
        """并行获取 top_k 条结果的详情页（正文 + 评论）。"""
        if not self._context:
            logger.warning("浏览器未启动，尝试自动启动以获取详情...")
            try:
                await self.launch(config, allow_interactive_login=False)
            except Exception as e:
                logger.error(f"自动启动浏览器失败: {e}")
            if not self._context:
                logger.error("浏览器启动失败，无法获取详情")
                return notes

        to_fetch = notes[:top_k]
        sem = asyncio.Semaphore(self.DETAIL_CONCURRENCY)

        async def _fetch_one(note: RawSearchResult, idx: int) -> None:
            async with sem:
                await self._enforce_platform_interval(config.name)
                detail = await self.fetch_detail(note.url, config)
                if detail:
                    if detail.content_snippet:
                        note.content_snippet = detail.content_snippet
                    if detail.top_comments:
                        note.top_comments = detail.top_comments
                        note.comments = [c.get("text", "") for c in detail.top_comments]
                    if detail.image_urls:
                        note.image_urls = detail.image_urls
                    if detail.likes > 0:
                        note.engagement_metrics["likes"] = detail.likes
                    if detail.favorites > 0:
                        note.engagement_metrics["collected"] = detail.favorites
                    if detail.comments_count > 0:
                        note.engagement_metrics["comments_count"] = detail.comments_count

        tasks = [_fetch_one(note, i) for i, note in enumerate(to_fetch)]
        await asyncio.gather(*tasks, return_exceptions=True)
        return notes

    async def fetch_detail(
        self, url: str, config: PlatformConfig, retry: int = 0
    ) -> Optional[ResourceDetail]:
        """进入详情页提取内容和评论，支持最多 DETAIL_MAX_RETRIES 次重试。"""
        if not self._context:
            return None

        page = await self._context.new_page()
        page.set_default_timeout(self.PAGE_TIMEOUT)

        note_id = ""
        m = re.search(r"/explore/([a-f0-9]+)", url)
        if m:
            note_id = m.group(1)

        detail_handler = self._make_detail_response_handler(note_id)
        if config.use_hybrid_mode:
            page.on("response", detail_handler)

        try:
            logger.debug(f"获取详情: {url[:80]}...")
            try:
                await page.goto(
                    url, wait_until="domcontentloaded", timeout=self.PAGE_TIMEOUT
                )
            except Exception as e:
                logger.warning(f"详情页加载异常: {e}")
                if retry < self.DETAIL_MAX_RETRIES:
                    await page.close()
                    await asyncio.sleep(_random_delay())
                    return await self.fetch_detail(url, config, retry + 1)
                return None

            await asyncio.sleep(_random_delay())
            await self._dismiss_login_popup(page)

            for _ in range(self.DETAIL_SCROLL_COUNT):
                await page.evaluate(f"window.scrollBy(0, {self.DETAIL_SCROLL_PX})")
                await asyncio.sleep(0.8)
            await asyncio.sleep(1)

            content = await self._extract_content_from_page(page)
            image_urls = await ResourceCollector.extract_image_urls(page)

            top_comments: List[Dict[str, str]] = []
            async with self._get_comment_lock():
                raw_comments = self._intercepted_comments.get(note_id, [])
            if raw_comments:
                top_comments = ResourceCollector.parse_intercepted_comments(raw_comments)
            else:
                top_comments = await ResourceCollector.extract_top_comments(page, config)

            detail = ResourceDetail(
                content_snippet=content,
                top_comments=top_comments,
                comments=[c.get("text", "") for c in top_comments],
                image_urls=image_urls,
            )

            status_parts = []
            if content:
                status_parts.append(f"正文{len(content)}字")
            if top_comments:
                status_parts.append(f"评论{len(top_comments)}条")
            if image_urls:
                status_parts.append(f"图片{len(image_urls)}张")
            logger.info(f"详情完成: {' '.join(status_parts) or '无数据'}")

            return detail

        except Exception as e:
            logger.error(f"详情获取失败: {e}")
            if retry < self.DETAIL_MAX_RETRIES:
                await asyncio.sleep(_random_delay())
                try:
                    await page.close()
                except Exception:
                    pass
                return await self.fetch_detail(url, config, retry + 1)
            return None
        finally:
            try:
                await page.close()
            except Exception:
                pass

    def _make_detail_response_handler(self, note_id: str):
        """为每个详情页 tab 创建独立的响应拦截器。"""
        async def handler(response: Any) -> None:
            url = response.url
            try:
                if "/api/sns/web/v2/comment/page" in url and response.status == 200:
                    data = await response.json()
                    if data.get("success") or data.get("code") == 0:
                        comments = data.get("data", {}).get("comments", [])
                        m = re.search(r"note_id=([a-f0-9]+)", url)
                        if m:
                            nid = m.group(1)
                            async with self._get_comment_lock():
                                self._intercepted_comments[nid] = comments
                elif "/api/sns/web/v1/feed" in url and response.status == 200:
                    data = await response.json()
                    if data.get("success") or data.get("code") == 0:
                        feed_items = data.get("data", {}).get("items", [])
                        for fi in feed_items:
                            nid = fi.get("id", "")
                            if nid:
                                self._intercepted_details[nid] = fi
            except Exception:
                pass
        return handler

    # ------------------------------------------------------------------
    # Content extraction (three-level fallback)
    # ------------------------------------------------------------------

    async def _extract_content_from_page(self, page: Any) -> str:
        """从详情页提取正文：三级回退策略。

        1. 优先：API 拦截数据（feed API）
        2. 回退：__INITIAL_STATE__ 内嵌 JSON
        3. 兜底：DOM 选择器
        """
        # Level 1: 检查拦截到的 feed API 数据
        m = re.search(r"/explore/([a-f0-9]+)", page.url)
        if m:
            nid = m.group(1)
            detail_data = self._intercepted_details.get(nid)
            if detail_data:
                try:
                    note = detail_data.get("note_card", detail_data.get("note", {}))
                    desc = note.get("desc", "")
                    if desc:
                        return desc[:800]
                except Exception:
                    pass

        # Level 2: __INITIAL_STATE__
        content = await ResourceCollector.extract_detail_from_initial_state(page)
        if content:
            return content

        # Level 3: DOM 选择器回退
        try:
            result = await page.evaluate("""() => {
                const selectors = ['#detail-desc', '.note-text', '.note-content', 'div.desc', 'article'];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText.trim().length > 20) {
                        return el.innerText.trim().substring(0, 800);
                    }
                }
                return '';
            }""")
            return result or ""
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Image content extraction (TODO stub)
    # ------------------------------------------------------------------

    async def extract_image_content(
        self, image_urls: List[str], max_images: int = 3
    ) -> List[str]:
        """[TODO: 未来实现] 下载前 max_images 张图片，调用多模态 LLM 提取图片内容。"""
        return []

    # ------------------------------------------------------------------
    # Login & anti-detection helpers
    # ------------------------------------------------------------------

    async def ensure_logged_in(self, page: Any, config: PlatformConfig) -> bool:
        """检查登录状态，失效时记录警告。

        通过检查 URL 是否被重定向（不再包含搜索关键词）来判断登录状态。
        """
        try:
            current_url = page.url
            if config.name == "xiaohongshu":
                if "search_result" not in current_url and "explore" not in current_url:
                    logger.warning(f"Cookie 过期 ({config.name})，需要重新登录")
                    return False
            return True
        except Exception:
            return False

    async def _dismiss_login_popup(self, page: Any) -> None:
        """自动检测并关闭登录弹窗（包括二维码登录弹窗）。"""
        try:
            close_selectors = [
                ".close-button",
                ".login-close",
                "[class*='close']",
                "button.close",
                # 小红书二维码登录弹窗的关闭按钮
                ".login-container [class*='close']",
                "[class*='modal'] [class*='close']",
            ]
            for sel in close_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        await el.click()
                        await asyncio.sleep(0.5)
                        logger.debug(f"已关闭弹窗 (selector: {sel})")
                        return
                except Exception:
                    continue
            # 尝试按 Escape 键关闭
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
        except Exception:
            pass

    async def _detect_captcha(self, page: Any) -> bool:
        """检测验证码/反爬页面。

        只检查可见的验证码元素，避免误判（小红书正常页面 JS 中也包含 captcha 字样）。
        """
        try:
            is_captcha_visible = await page.evaluate("""() => {
                const selectors = [
                    '#captcha-div',
                    '.captcha-container',
                    '.verify-container',
                    '.slide-verify',
                    '[class*="captcha"][class*="modal"]',
                    '[class*="verify"][class*="modal"]',
                    '[class*="captcha"][class*="wrapper"]',
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el) {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        if (rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden') {
                            return true;
                        }
                    }
                }
                const body = document.body;
                if (body && body.innerText.trim().length < 50) {
                    const title = document.title.toLowerCase();
                    if (title.includes('验证') || title.includes('captcha') || title.includes('安全')) {
                        return true;
                    }
                }
                return false;
            }""")
            return is_captcha_visible
        except Exception:
            return False
