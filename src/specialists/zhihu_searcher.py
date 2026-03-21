"""
知乎搜索器（浏览器 API 响应拦截模式 + Cookie 登录）

通过 Playwright 浏览器访问知乎搜索页，拦截浏览器自动发出的 API 响应获取 JSON 数据。
不需要自己计算签名——浏览器的 JS 引擎天然处理所有签名逻辑。

登录流程（与小红书 searcher 一致）：
1. 加载持久化 cookie，headless 启动浏览器
2. 导航到搜索页，检查是否能拦截到 200 的 search_v3 响应
3. 验证失败 → 清除数据 → 弹可见浏览器让用户扫码登录
4. 登录成功 → 保存 cookie → 关闭可见浏览器 → headless 重启

流程：
1. Playwright 启动浏览器，加载 cookie
2. 导航到搜索页，注册 response 拦截器捕获 /api/v4/search_v3 的 JSON 响应
3. 解析搜索结果，构造 RawSearchResult
4. 评论数从搜索结果的 comment_count 字段获取（不单独请求评论 API）
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
import re
import shutil
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

from playwright.async_api import BrowserContext, Page, Response, async_playwright

from src.specialists.browser_models import RawSearchResult

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
COOKIE_FILE = _PROJECT_ROOT / "scripts" / ".zhihu_cookies.json"
STEALTH_JS = _PROJECT_ROOT / "scripts" / "MediaCrawler" / "libs" / "stealth.min.js"
ZHIHU_URL = "https://www.zhihu.com"
ZHIHU_ZHUANLAN_URL = "https://zhuanlan.zhihu.com"


def _extract_text_from_html(html: str) -> str:
    """简单的 HTML 标签清理，提取纯文本。"""
    if not html:
        return ""
    return re.sub(r"<[^>]+>", "", html).strip()


class ZhihuSearcher:
    """知乎搜索器（浏览器 API 响应拦截模式）

    核心思路：让浏览器处理所有签名，我们只拦截 API 响应拿 JSON。
    需要登录态才能使用搜索 API。
    """

    INTERCEPT_TIMEOUT = 15  # 等待 API 响应的超时（秒）

    def __init__(self):
        self._browser_context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._playwright = None
        self._pw_cm = None
        self._initialized = False

    async def search(self, query: str, limit: int = 10) -> List[RawSearchResult]:
        """搜索知乎内容，返回 RawSearchResult 列表。"""
        try:
            if not self._initialized:
                await self._init_browser()

            search_data = await self._search_via_browser(query)
            if not search_data:
                logger.warning("知乎搜索无结果")
                return self._fallback_result(query)

            # 按类型分类处理：question 聚合多回答，article 提取完整正文，zvideo 透传
            enriched_data = await self._enrich_results(search_data)

            results: List[RawSearchResult] = []
            for item in enriched_data[:limit]:
                r = self._build_result(item)
                if r:
                    results.append(r)

            logger.info(f"知乎搜索完成: {len(results)} 条结果")
            return results if results else self._fallback_result(query)
        except Exception as e:
            logger.error(f"知乎搜索异常: {e}")
            return self._fallback_result(query)

    # ---- 浏览器初始化 + 登录 ----

    async def _init_browser(self):
        """启动 Playwright，加载 Cookie，验证登录态。"""
        logger.info("初始化知乎浏览器环境...")
        self._pw_cm = async_playwright()
        self._playwright = await self._pw_cm.start()

        cookies = self._load_cookies()
        self._browser_context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(_PROJECT_ROOT / "browser_data" / "zhihu"),
            headless=True,
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
            ),
        )
        if STEALTH_JS.exists():
            await self._browser_context.add_init_script(path=str(STEALTH_JS))
        if cookies:
            await self._browser_context.add_cookies(cookies)

        self._page = await self._browser_context.new_page()

        # 访问首页获取基础 cookie
        await self._page.goto(ZHIHU_URL, wait_until="domcontentloaded", timeout=30000)
        await self._page.wait_for_timeout(2000)

        # 验证登录态：尝试搜索一个简单关键词，看能否拦截到 200 响应
        need_login = not await self._verify_search_access()

        if need_login:
            logger.warning("知乎登录态无效，需要登录")
            await self._close_browser()

            # 清除旧数据
            zhihu_data = _PROJECT_ROOT / "browser_data" / "zhihu"
            if zhihu_data.exists():
                shutil.rmtree(zhihu_data, ignore_errors=True)
            if COOKIE_FILE.exists():
                COOKIE_FILE.unlink(missing_ok=True)

            await self._interactive_login()
            return  # _interactive_login 末尾递归调用 _init_browser

        self._initialized = True
        logger.info("知乎浏览器环境就绪（已登录）")

    async def _verify_search_access(self) -> bool:
        """验证当前登录态是否能正常搜索。

        导航到搜索页，检查是否能拦截到 200 的 search_v3 响应。
        """
        if not self._page:
            return False

        got_200 = asyncio.Event()

        async def _check_response(response: Response):
            if "/api/v4/search_v3" in response.url and response.status == 200:
                got_200.set()

        self._page.on("response", _check_response)
        try:
            search_url = f"{ZHIHU_URL}/search?q=python&type=content"
            await self._page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            try:
                await asyncio.wait_for(got_200.wait(), timeout=10)
                logger.info("知乎搜索验证通过")
                return True
            except asyncio.TimeoutError:
                logger.warning("知乎搜索验证失败：未拦截到 200 响应")
                return False
        except Exception as e:
            logger.warning(f"知乎搜索验证异常: {e}")
            return False
        finally:
            try:
                self._page.remove_listener("response", _check_response)
            except Exception:
                pass

    async def _interactive_login(self):
        """弹出可见浏览器让用户手动登录知乎。"""
        logger.info("=" * 50)
        logger.info("需要登录知乎，即将弹出浏览器窗口")
        logger.info("请手动登录（扫码/手机号），登录成功后自动检测（最多等 5 分钟）")
        logger.info("=" * 50)

        await self._close_browser()

        self._pw_cm = async_playwright()
        self._playwright = await self._pw_cm.start()
        self._browser_context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(_PROJECT_ROOT / "browser_data" / "zhihu"),
            headless=False,
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
            ),
        )
        if STEALTH_JS.exists():
            await self._browser_context.add_init_script(path=str(STEALTH_JS))

        self._page = await self._browser_context.new_page()
        await self._page.goto(f"{ZHIHU_URL}/signin", wait_until="domcontentloaded", timeout=30000)

        logged_in = False
        for i in range(60):  # 60 × 5s = 5 分钟
            await self._page.wait_for_timeout(5000)

            # 用 cookie 检查登录态，不做页面导航（避免打断用户输入）
            # 知乎登录成功后会设置 z_c0 cookie
            cookies = await self._browser_context.cookies()
            cookie_dict = {c["name"]: c["value"] for c in cookies}
            if cookie_dict.get("z_c0"):
                logger.info("检测到 z_c0 cookie，登录成功")
                self._save_cookies(cookies)
                logged_in = True
                break

            if i % 6 == 0:
                logger.info(f"等待知乎登录中... ({(i + 1) * 5}s / 300s)")

        if not logged_in:
            raise RuntimeError("知乎登录超时（5分钟）")

        # 登录成功，关闭可见浏览器，用 headless 重启
        await self._close_browser()
        await self._init_browser()

    # ---- 核心搜索：浏览器导航 + API 响应拦截 ----

    async def _search_via_browser(self, query: str) -> List[Dict]:
        """在浏览器中执行搜索，拦截 API 响应获取 JSON 数据。"""
        if not self._page:
            raise RuntimeError("浏览器未初始化")

        captured_data: List[dict] = []
        capture_event = asyncio.Event()

        async def _on_response(response: Response):
            """拦截搜索 API 响应。"""
            url = response.url
            if "/api/v4/search_v3" not in url:
                return
            try:
                if response.status != 200:
                    logger.warning(f"知乎搜索 API 响应 {response.status}: {url[:100]}")
                    return
                body = await response.json()
                items = body.get("data", [])
                if items:
                    captured_data.extend(items)
                    logger.info(f"拦截到知乎搜索响应: {len(items)} 条")
                capture_event.set()
            except Exception as e:
                logger.warning(f"解析知乎搜索响应失败: {e}")

        self._page.on("response", _on_response)

        try:
            search_url = f"{ZHIHU_URL}/search?q={quote(query)}&type=content"
            await self._page.goto(search_url, wait_until="domcontentloaded", timeout=30000)

            try:
                await asyncio.wait_for(capture_event.wait(), timeout=self.INTERCEPT_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning(f"等待知乎搜索 API 响应超时（{self.INTERCEPT_TIMEOUT}s）")
        finally:
            try:
                self._page.remove_listener("response", _on_response)
            except Exception:
                pass

        # 解析拦截到的数据
        valid_types = {"search_result", "zvideo"}
        results = []
        for item in captured_data:
            if item.get("type") not in valid_types:
                continue
            obj = item.get("object")
            if not obj:
                continue
            parsed = self._parse_content(obj)
            if parsed:
                results.append(parsed)

        return results

    # ---- 数据解析 ----

    def _parse_content(self, obj: Dict) -> Optional[Dict]:
        """解析搜索结果中的单个内容对象。"""
        content_type = obj.get("type", "")
        content_id = obj.get("id")
        if not content_id:
            return None

        title = _extract_text_from_html(obj.get("title", ""))
        if not title:
            title = _extract_text_from_html(obj.get("name", ""))
        if not title:
            return None

        # 构造 URL + 提取问题信息（answer 类型需要 question_id 用于聚合）
        question_id = ""
        question_title = ""
        if content_type == "answer":
            question_obj = obj.get("question", {})
            question_id = str(question_obj.get("id", ""))
            # 知乎 API 的问题标题在 question.name 字段（不是 title），带 <em> 高亮标签
            question_title = _extract_text_from_html(question_obj.get("name", ""))
            url = f"{ZHIHU_URL}/question/{question_id}/answer/{content_id}"
        elif content_type == "article":
            url = f"{ZHIHU_ZHUANLAN_URL}/p/{content_id}"
        elif content_type == "zvideo":
            url = obj.get("video_url") or f"{ZHIHU_URL}/zvideo/{content_id}"
        else:
            url = f"{ZHIHU_URL}/question/{content_id}"

        desc = _extract_text_from_html(
            obj.get("description", "") or obj.get("excerpt", "") or obj.get("content", "")
        )

        voteup = self._safe_int(obj.get("voteup_count", 0))
        comment_count = self._safe_int(obj.get("comment_count", 0))

        return {
            "content_id": str(content_id),
            "content_type": content_type,
            "title": title,
            "url": url,
            "description": desc[:500] if desc else "",
            "content_snippet": desc[:2000] if desc else "",
            "voteup_count": voteup,
            "comment_count": comment_count,
            "author": obj.get("author", {}).get("name", ""),
            "question_id": question_id,
            "question_title": question_title,
        }

    # ---- 问题级聚合（二次请求 top 回答） ----

    async def _fetch_question_answers(
        self, question_id: str, limit: int = 3, page: Optional[Page] = None
    ) -> List[Dict]:
        """导航到问题页，从渲染后的 DOM 提取 top 回答。

        知乎 answers API 有签名校验（x-zse-96），直接 fetch 会被拦截。
        改用页面导航 + DOM 选择器提取，SSR 渲染的回答在 DOM 中一定存在。

        Args:
            question_id: 知乎问题 ID
            limit: 最多返回回答数
            page: 可选的独立 tab，并行化时传入避免共享 self._page

        Returns:
            回答列表，每个元素包含 content_snippet, voteup_count, comment_count, author
        """
        target_page = page or self._page
        if not target_page:
            return []

        try:
            question_url = f"{ZHIHU_URL}/question/{question_id}"
            await target_page.goto(question_url, wait_until="domcontentloaded", timeout=15000)
            # 等待回答列表渲染
            try:
                await target_page.wait_for_selector(
                    ".AnswerItem,.List-item,.AnswerCard", timeout=5000
                )
            except Exception:
                logger.debug(f"问题 {question_id} 等待回答元素超时，尝试直接提取")

            # 从 DOM 提取问题描述 + 回答数据
            answers_data = await target_page.evaluate("""(limit) => {
                // 提取问题描述（问题页顶部的补充说明）
                const detailEl = document.querySelector(
                    '.QuestionRichText, .QuestionDetail-main .RichText, [class*="QuestionDetail"] .RichText'
                );
                const questionDetail = detailEl ? detailEl.innerText.trim().substring(0, 1000) : '';

                // 多种选择器兼容不同页面结构
                const containers = document.querySelectorAll(
                    '.AnswerItem, .List-item, .AnswerCard'
                );
                const answers = [];
                for (let i = 0; i < Math.min(containers.length, limit + 2); i++) {
                    const el = containers[i];
                    
                    // 提取回答正文（多种选择器 fallback）
                    const contentEl = el.querySelector(
                        '.RichContent-inner, .RichText, .css-376mun'
                    );
                    const text = contentEl ? contentEl.innerText.trim() : '';
                    if (!text) continue;
                    
                    // 提取赞数：按钮文本 "赞同 123" 或 "123 人赞同"
                    let voteup = 0;
                    const voteBtn = el.querySelector(
                        'button[aria-label*="赞同"], .VoteButton--up, .css-1mdbw0j'
                    );
                    if (voteBtn) {
                        const voteText = voteBtn.innerText || voteBtn.getAttribute('aria-label') || '';
                        const m = voteText.match(/([\d,.]+\\s*[万kK]?)/);
                        if (m) {
                            let v = m[1].replace(/,/g, '').trim();
                            if (v.includes('万')) {
                                voteup = Math.round(parseFloat(v) * 10000);
                            } else if (v.toLowerCase().includes('k')) {
                                voteup = Math.round(parseFloat(v) * 1000);
                            } else {
                                voteup = parseInt(v) || 0;
                            }
                        }
                    }
                    
                    // 提取评论数
                    let commentCount = 0;
                    const commentBtn = el.querySelector(
                        'button[class*="Comment"], .css-12cl38p'
                    );
                    if (commentBtn) {
                        const cText = commentBtn.innerText || '';
                        const cm = cText.match(/(\\d+)/);
                        if (cm) commentCount = parseInt(cm[1]) || 0;
                    }
                    
                    // 提取作者名
                    const authorEl = el.querySelector(
                        '.AuthorInfo-name a, .UserLink-link, .css-1gomreu'
                    );
                    const author = authorEl ? authorEl.innerText.trim() : '';
                    
                    answers.push({
                        content_snippet: text.substring(0, 3000),
                        voteup_count: voteup,
                        comment_count: commentCount,
                        author: author
                    });
                }
                return { questionDetail, answers };
            }""", limit)

            if not answers_data or not answers_data.get("answers"):
                logger.info(f"问题 {question_id} DOM 提取无回答")
                return []

            question_detail = answers_data.get("questionDetail", "")
            answers_list = answers_data["answers"]

            # 按赞数降序
            answers_list.sort(key=lambda x: x.get("voteup_count", 0), reverse=True)
            logger.info(
                f"问题 {question_id} DOM 提取 {len(answers_list)} 条回答"
                f"（top 赞数: {answers_list[0].get('voteup_count', 0)}）"
            )
            result = answers_list[:limit]
            # 把问题描述附加到返回值，供 _aggregate_by_question 使用
            for ans in result:
                ans["_question_detail"] = question_detail
            return result

        except Exception as e:
            logger.info(f"问题 {question_id} 页面提取失败: {e}")
            return []

    async def _fetch_article_content(
        self, article_url: str, page: Optional[Page] = None
    ) -> str:
        """导航到知乎专栏文章页，从 DOM 提取完整正文。

        Args:
            article_url: 专栏文章 URL（zhuanlan.zhihu.com/p/xxx）
            page: 可选的独立 tab，并行化时传入

        Returns:
            正文文本，截断到 5000 字。失败返回空字符串。
        """
        target_page = page or self._page
        if not target_page:
            return ""

        try:
            await target_page.goto(article_url, wait_until="domcontentloaded", timeout=15000)
            # 等待文章正文渲染
            try:
                await target_page.wait_for_selector(
                    ".Post-RichText, .RichText, article .RichContent", timeout=5000
                )
            except Exception:
                logger.debug(f"专栏文章等待正文元素超时: {article_url}")

            content = await target_page.evaluate("""() => {
                // 多种选择器兼容不同页面结构
                const selectors = [
                    '.Post-RichTextContainer .RichText',
                    '.Post-RichText',
                    'article .RichText',
                    '.RichContent-inner',
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText.trim().length > 50) {
                        return el.innerText.trim().substring(0, 5000);
                    }
                }
                return '';
            }""")

            if content:
                logger.info(f"专栏文章提取 {len(content)} 字: {article_url[:60]}")
            return content or ""

        except Exception as e:
            logger.info(f"专栏文章提取失败: {article_url} - {e}")
            return ""

    async def _enrich_results(self, items: List[Dict]) -> List[Dict]:
        """按内容类型分类处理，统一并发二次请求丰富搜索结果。

        分类策略：
        - answer → 按 question_id 聚合，Top 5 高赞问题并发提取多回答
        - article → 并发开 tab 提取专栏完整正文
        - zvideo → 不做二次请求，视频没有长文正文

        所有二次请求共享同一个 semaphore（=3），统一控制并发 tab 数。
        """
        import random
        from collections import defaultdict

        CONCURRENCY = 3  # 并发 tab 数，所有类型共享
        TOP_N_QUESTIONS = 5  # 对 top 5 问题做二次请求

        # ---- 按类型分组 ----
        question_groups: Dict[str, List[Dict]] = defaultdict(list)
        article_items: List[Dict] = []
        other_items: List[Dict] = []  # zvideo 等

        for item in items:
            if item["content_type"] == "answer" and item.get("question_id"):
                question_groups[item["question_id"]].append(item)
            elif item["content_type"] == "article":
                article_items.append(item)
            else:
                other_items.append(item)

        # ---- 准备并发任务 ----
        if not self._browser_context:
            # 无浏览器上下文，跳过所有二次请求
            return self._build_question_aggregates(
                question_groups, {}, TOP_N_QUESTIONS
            ) + article_items + other_items

        semaphore = asyncio.Semaphore(CONCURRENCY)

        # 1) 问题二次请求任务
        sorted_questions = sorted(
            question_groups.items(),
            key=lambda kv: max(a.get("voteup_count", 0) for a in kv[1]),
            reverse=True,
        )
        top_questions = sorted_questions[:TOP_N_QUESTIONS]

        async def _fetch_question(qid: str) -> tuple:
            """在独立 tab 中提取单个问题的回答。"""
            async with semaphore:
                await asyncio.sleep(random.uniform(0.3, 1.0))
                tab = None
                try:
                    tab = await self._browser_context.new_page()
                    fetched = await self._fetch_question_answers(qid, limit=3, page=tab)
                    return ("question", qid, fetched)
                except Exception as e:
                    logger.info(f"问题 {qid} 并发提取失败: {e}")
                    return ("question", qid, [])
                finally:
                    if tab:
                        try:
                            await tab.close()
                        except Exception:
                            pass

        # 2) 专栏文章二次请求任务
        async def _fetch_article(item: Dict) -> tuple:
            """在独立 tab 中提取专栏文章完整正文。"""
            async with semaphore:
                await asyncio.sleep(random.uniform(0.3, 1.0))
                tab = None
                try:
                    tab = await self._browser_context.new_page()
                    content = await self._fetch_article_content(item["url"], page=tab)
                    return ("article", item["content_id"], content)
                except Exception as e:
                    logger.info(f"专栏 {item['content_id']} 并发提取失败: {e}")
                    return ("article", item["content_id"], "")
                finally:
                    if tab:
                        try:
                            await tab.close()
                        except Exception:
                            pass

        # ---- 统一并发执行 ----
        all_tasks = []
        all_tasks.extend(_fetch_question(qid) for qid, _ in top_questions)
        all_tasks.extend(_fetch_article(item) for item in article_items)

        question_fetch_results: Dict[str, List[Dict]] = {}
        article_fetch_results: Dict[str, str] = {}  # content_id -> full_text

        if all_tasks:
            results = await asyncio.gather(*all_tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    logger.warning(f"并发二次请求异常: {r}")
                    continue
                result_type, result_id, result_data = r
                if result_type == "question" and result_data:
                    question_fetch_results[result_id] = result_data
                    logger.info(f"问题 {result_id} 二次请求获取 {len(result_data)} 条回答")
                elif result_type == "article" and result_data:
                    article_fetch_results[result_id] = result_data

        # ---- 构建最终结果 ----
        # 1) 问题聚合
        aggregated_questions = self._build_question_aggregates(
            question_groups, question_fetch_results, TOP_N_QUESTIONS
        )

        # 2) 文章：用二次请求的完整正文覆盖搜索 API 的 excerpt
        enriched_articles = []
        for item in article_items:
            full_text = article_fetch_results.get(item["content_id"], "")
            if full_text:
                item["content_snippet"] = full_text
                # description 保持搜索 API 的摘要（更简洁），不用正文覆盖
            enriched_articles.append(item)

        # 3) 日志
        q_fetched = len(question_fetch_results)
        q_total = min(len(sorted_questions), TOP_N_QUESTIONS)
        a_fetched = len(article_fetch_results)
        a_total = len(article_items)
        logger.info(
            f"知乎二次请求: 问题 {q_fetched}/{q_total} 成功, "
            f"专栏 {a_fetched}/{a_total} 成功"
        )
        logger.info(
            f"知乎聚合: {len(items)} 条原始 → {len(aggregated_questions)} 个问题"
            f" + {len(enriched_articles)} 篇专栏 + {len(other_items)} 条其他"
        )

        return aggregated_questions + enriched_articles + other_items

    def _build_question_aggregates(
        self,
        question_groups: Dict[str, List[Dict]],
        fetch_results: Dict[str, List[Dict]],
        top_n: int,
    ) -> List[Dict]:
        """从问题分组 + 二次请求结果构建聚合数据。

        纯数据转换，不涉及 IO。从 _enrich_results 中抽出来保持职责清晰。
        """
        if not question_groups:
            return []

        sorted_questions = sorted(
            question_groups.items(),
            key=lambda kv: max(a.get("voteup_count", 0) for a in kv[1]),
            reverse=True,
        )

        aggregated: List[Dict] = []

        for idx, (qid, search_answers) in enumerate(sorted_questions):
            q_title = search_answers[0].get("question_title") or search_answers[0].get("title", "")

            if qid in fetch_results:
                # 二次请求成功
                answers_to_use = fetch_results[qid]
                question_detail = answers_to_use[0].get("_question_detail", "") if answers_to_use else ""
            elif idx < top_n:
                # 二次请求失败，降级用搜索返回的回答
                logger.debug(f"问题 {qid} 二次请求无结果，使用搜索回答")
                answers_to_use = [
                    {"content_snippet": a.get("content_snippet", ""),
                     "voteup_count": a.get("voteup_count", 0),
                     "comment_count": a.get("comment_count", 0),
                     "author": a.get("author", "")}
                    for a in search_answers
                ]
                question_detail = ""
            else:
                # 非 top 问题：直接用搜索返回的回答
                answers_to_use = [
                    {"content_snippet": a.get("content_snippet", ""),
                     "voteup_count": a.get("voteup_count", 0),
                     "comment_count": a.get("comment_count", 0),
                     "author": a.get("author", "")}
                    for a in search_answers
                ]
                question_detail = ""

            # 构建聚合 content_snippet：统一加【回答N·赞X】标注
            snippets = []
            for i, ans in enumerate(answers_to_use, 1):
                voteup = ans.get("voteup_count", 0)
                snippet = ans.get("content_snippet", "")
                if snippet:
                    snippets.append(f"【回答{i}·赞{voteup}】{snippet}")

            total_likes = sum(a.get("voteup_count", 0) for a in answers_to_use)
            total_comments = sum(a.get("comment_count", 0) for a in answers_to_use)

            aggregated.append({
                "content_type": "question",
                "title": q_title,
                "url": f"{ZHIHU_URL}/question/{qid}",
                "description": question_detail or (snippets[0][:300] if snippets else ""),
                "content_snippet": "\n".join(snippets),
                "voteup_count": total_likes,
                "comment_count": total_comments,
                "answer_count": len(answers_to_use),
            })

        return aggregated

    # ---- 数据转换 ----

    def _build_result(self, item: Dict) -> Optional[RawSearchResult]:
        """将解析后的内容转换为 RawSearchResult。"""
        try:
            content_type = item.get("content_type", "article")

            # 按内容类型设置 resource_type，前端用于区分展示
            if content_type == "question":
                resource_type = "question"
                # 问题聚合：只展示回答数，加总赞数对用户没意义
                metrics = {
                    "answer_count": item.get("answer_count", 0),
                }
            elif content_type == "zvideo":
                resource_type = "video"
                metrics = {
                    "likes": item.get("voteup_count", 0),
                    "comments_count": item.get("comment_count", 0),
                }
            else:
                resource_type = "article"
                # article：正常展示赞数和评论数
                metrics = {
                    "likes": item.get("voteup_count", 0),
                    "comments_count": item.get("comment_count", 0),
                }

            return RawSearchResult(
                title=item["title"],
                url=item["url"],
                platform="zhihu",
                resource_type=resource_type,
                description=item.get("description", ""),
                content_snippet=item.get("content_snippet", ""),
                engagement_metrics=metrics,
                # 四层 metadata
                source_tier="community",
                author=item.get("author", ""),
                publish_time="",  # 知乎搜索 API 不返回发布时间
                fetched_at=datetime.now(timezone.utc).isoformat(),
                extraction_mode="zhihu_browser_intercept",
            )
        except Exception as e:
            logger.warning(f"构建知乎结果失败: {e}")
            return None

    @staticmethod
    def _safe_int(value) -> int:
        if value is None:
            return 0
        try:
            if isinstance(value, str):
                value = value.replace("万", "0000").replace("亿", "00000000").replace("+", "")
            return int(float(value))
        except (ValueError, TypeError):
            return 0

    def _fallback_result(self, query: str) -> List[RawSearchResult]:
        """降级结果：返回知乎搜索链接。"""
        search_url = f"{ZHIHU_URL}/search?type=content&q={quote(query)}"
        return [
            RawSearchResult(
                title=f"在知乎搜索「{query}」",
                url=search_url,
                platform="zhihu",
                resource_type="article",
                description="点击链接在知乎查看更多搜索结果",
                engagement_metrics={},
                source_tier="community",
                fetched_at=datetime.now(timezone.utc).isoformat(),
                extraction_mode="zhihu_fallback_link",
            )
        ]

    # ---- Cookie 管理 ----

    def _load_cookies(self) -> list:
        if not COOKIE_FILE.exists():
            return []
        try:
            with open(COOKIE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _save_cookies(self, cookies: list):
        try:
            COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(COOKIE_FILE, "w", encoding="utf-8") as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
            logger.info(f"知乎 cookie 已保存到 {COOKIE_FILE}")
        except Exception as e:
            logger.warning(f"保存知乎 cookie 失败: {e}")

    # ---- 资源清理 ----

    async def _close_browser(self):
        """关闭浏览器，释放资源（不重置 _initialized）。"""
        try:
            if self._browser_context:
                await self._browser_context.close()
                self._browser_context = None
                self._page = None
        except Exception:
            pass
        try:
            if self._pw_cm:
                await self._pw_cm.__aexit__(None, None, None)
                self._playwright = None
                self._pw_cm = None
        except Exception:
            pass

    async def close(self):
        """关闭浏览器，释放资源。"""
        self._initialized = False
        await self._close_browser()
