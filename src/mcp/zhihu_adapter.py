"""MCP 知乎搜索适配器 —— API 拦截 + DOM 提取

搜索：导航到搜索页，拦截 /api/v4/search_v3 响应获取 JSON
问题详情：导航到问题页，从 DOM 提取 top N 回答
不需要登录即可搜索（登录后内容更完整）
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

from playwright.async_api import async_playwright, BrowserContext, Page, Response

from src.mcp.models import SearchResultItem, SearchData

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_BROWSER_DATA = _PROJECT_ROOT / "browser_data" / "zhihu"
_STEALTH_JS = _PROJECT_ROOT / "stealth.min.js"
_ZHIHU_URL = "https://www.zhihu.com"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """去除 HTML 标签，解码实体。"""
    if not text:
        return ""
    return html.unescape(_HTML_TAG_RE.sub("", text)).strip()


class ZhihuBrowserSearcher:
    """知乎浏览器搜索器：API 拦截 + DOM 提取"""

    INTERCEPT_TIMEOUT = 10  # 等待 API 响应的超时秒数

    def __init__(self):
        self._pw_cm = None
        self._playwright = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._initialized = False

    async def init_browser(self, headless: bool = True):
        if self._initialized:
            return
        logger.info("MCP: 初始化知乎浏览器 (headless=%s)...", headless)
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
        logger.info("MCP: 知乎浏览器就绪")

    async def check_auth(self) -> bool:
        """知乎不强制登录，只检查浏览器是否初始化。"""
        try:
            await self.init_browser(headless=True)
            return True
        except Exception as e:
            logger.warning("MCP: 知乎浏览器初始化失败: %s", e)
            return False

    async def search(self, query: str, limit: int = 10) -> SearchData:
        """搜索知乎，拦截 /api/v4/search_v3 响应。"""
        if not self._initialized:
            await self.init_browser(headless=True)

        captured: List[dict] = []
        capture_event = asyncio.Event()

        async def _on_response(response: Response):
            if "/api/v4/search_v3" not in response.url:
                return
            try:
                if response.status != 200:
                    return
                body = await response.json()
                items = body.get("data", [])
                if items:
                    captured.extend(items)
                    capture_event.set()
            except Exception:
                pass

        self._page.on("response", _on_response)
        try:
            search_url = f"{_ZHIHU_URL}/search?q={quote(query)}&type=content"
            logger.info("MCP: 导航到知乎搜索页: %s", search_url)
            await self._page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            try:
                await asyncio.wait_for(capture_event.wait(), timeout=self.INTERCEPT_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning("MCP: 知乎搜索 API 拦截超时")
        finally:
            try:
                self._page.remove_listener("response", _on_response)
            except Exception:
                pass

        # 解析结果
        items = []
        for raw in captured[:limit]:
            if raw.get("type") not in ("search_result", "zvideo"):
                continue
            obj = raw.get("object")
            if not obj:
                continue
            parsed = self._parse_search_item(obj)
            if parsed:
                items.append(parsed)

        logger.info("MCP: 知乎搜索完成，%d 条结果 (query='%s')", len(items), query)
        return SearchData(results=items, total_requested=limit, total_returned=len(items))

    async def get_question_answers(self, question_id: str, limit: int = 5) -> dict:
        """获取问题详情 + top N 回答（DOM 提取）。"""
        if not self._initialized:
            await self.init_browser(headless=True)

        tab = await self._context.new_page()
        try:
            url = f"{_ZHIHU_URL}/question/{question_id}"
            logger.info("MCP: 导航到知乎问题页: %s", url)
            await tab.goto(url, wait_until="domcontentloaded", timeout=15000)
            # 等待页面网络空闲
            try:
                await tab.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            try:
                await tab.wait_for_selector(".AnswerItem,.List-item,.AnswerCard", timeout=8000)
            except Exception:
                logger.warning("MCP: 知乎问题页回答元素未找到，等待额外 3 秒")
                await tab.wait_for_timeout(3000)

            data = await tab.evaluate("""(limit) => {
                const detailEl = document.querySelector(
                    '.QuestionRichText, .QuestionDetail-main .RichText'
                );
                const questionDetail = detailEl ? detailEl.innerText.trim().substring(0, 1000) : '';
                const titleEl = document.querySelector('.QuestionHeader-title');
                const title = titleEl ? titleEl.innerText.trim() : '';

                const containers = document.querySelectorAll('.AnswerItem, .List-item, .AnswerCard');
                const answers = [];
                for (let i = 0; i < Math.min(containers.length, limit + 2); i++) {
                    const el = containers[i];
                    const contentEl = el.querySelector('.RichContent-inner, .RichText');
                    const text = contentEl ? contentEl.innerText.trim() : '';
                    if (!text) continue;

                    let voteup = 0;
                    const voteBtn = el.querySelector('button[aria-label*="赞同"], .VoteButton--up');
                    if (voteBtn) {
                        const vt = voteBtn.innerText || voteBtn.getAttribute('aria-label') || '';
                        const m = vt.match(/([\\d,.]+\\s*[万kK]?)/);
                        if (m) {
                            let v = m[1].replace(/,/g, '').trim();
                            if (v.includes('万')) voteup = Math.round(parseFloat(v) * 10000);
                            else if (v.toLowerCase().includes('k')) voteup = Math.round(parseFloat(v) * 1000);
                            else voteup = parseInt(v) || 0;
                        }
                    }

                    let commentCount = 0;
                    const commentBtn = el.querySelector('button[class*="Comment"]');
                    if (commentBtn) {
                        const cm = (commentBtn.innerText || '').match(/(\\d+)/);
                        if (cm) commentCount = parseInt(cm[1]) || 0;
                    }

                    const authorEl = el.querySelector('.AuthorInfo-name a, .UserLink-link');
                    const author = authorEl ? authorEl.innerText.trim() : '';

                    answers.push({
                        content: text.substring(0, 3000),
                        voteup: voteup,
                        comments: commentCount,
                        author: author
                    });
                }
                answers.sort((a, b) => b.voteup - a.voteup);
                return { title, questionDetail, answers: answers.slice(0, limit) };
            }""", limit)

            logger.info("MCP: 知乎问题 %s 提取 %d 条回答", question_id, len(data.get("answers", [])))
            return {
                "question_id": question_id,
                "title": data.get("title", ""),
                "url": f"{_ZHIHU_URL}/question/{question_id}",
                "description": data.get("questionDetail", ""),
                "answers": data.get("answers", []),
            }
        except Exception as e:
            logger.warning("MCP: 知乎问题 %s 提取失败: %s", question_id, e)
            return {"question_id": question_id, "title": "", "url": f"{_ZHIHU_URL}/question/{question_id}", "description": "", "answers": []}
        finally:
            await tab.close()

    async def login(self, timeout: float = 300):
        """弹出可见浏览器让用户登录知乎。"""
        await self.close()
        logger.info("MCP: 弹出知乎登录窗口...")
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
        await self._page.goto(f"{_ZHIHU_URL}/signin", wait_until="domcontentloaded", timeout=30000)

        # 轮询检测登录（检查 URL 是否跳转离开 signin）
        logged_in = False
        for i in range(int(timeout / 5)):
            await self._page.wait_for_timeout(5000)
            current_url = self._page.url
            if "/signin" not in current_url and "zhihu.com" in current_url:
                logger.info("MCP: 知乎登录成功！")
                logged_in = True
                break
            if i % 6 == 0:
                logger.info("等待知乎登录... (%ds / %ds)", (i + 1) * 5, int(timeout))

        if not logged_in:
            await self.close()
            raise RuntimeError(f"知乎登录超时（{int(timeout)}秒）")
        await self.close()

    async def close(self):
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
    def _parse_search_item(obj: dict) -> Optional[SearchResultItem]:
        content_type = obj.get("type", "")
        content_id = obj.get("id")
        if not content_id:
            return None

        title = _strip_html(obj.get("title", "") or obj.get("name", ""))
        if not title:
            return None

        # URL
        question_id = ""
        if content_type == "answer":
            q = obj.get("question", {})
            question_id = str(q.get("id", ""))
            url = f"{_ZHIHU_URL}/question/{question_id}/answer/{content_id}"
            title = _strip_html(q.get("name", "")) or title
        elif content_type == "article":
            url = f"https://zhuanlan.zhihu.com/p/{content_id}"
        elif content_type == "zvideo":
            url = obj.get("video_url") or f"{_ZHIHU_URL}/zvideo/{content_id}"
        else:
            url = f"{_ZHIHU_URL}/question/{content_id}"

        desc = _strip_html(obj.get("description", "") or obj.get("excerpt", "") or obj.get("content", ""))
        voteup = int(obj.get("voteup_count", 0) or 0)
        comments = int(obj.get("comment_count", 0) or 0)
        author = (obj.get("author") or {}).get("name", "")

        return SearchResultItem(
            id=str(content_id),
            title=title,
            url=url,
            snippet=desc[:300] if desc else "",
            author=author,
            likes=voteup,
            xsec_token=question_id,  # 复用 xsec_token 字段存 question_id
            note_type=content_type,   # answer / article / zvideo
        )
