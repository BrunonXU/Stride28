"""
ResourceCollector - 从浏览器页面提取结构化资源数据

从 Playwright Page 对象或拦截到的 API JSON 中提取搜索结果、详情、评论和图片 URL。
所有方法在提取失败时返回默认值，不抛出异常。
"""

import logging
import re
from typing import Any, Dict, List, Optional, Union

from src.specialists.browser_models import RawSearchResult, ResourceDetail
from src.specialists.platform_configs import PlatformConfig

logger = logging.getLogger(__name__)

# 广告评论过滤关键词
AD_KEYWORDS = [
    "私信", "加我", "免费领", "点击链接", "优惠券",
    "下单", "代购", "微信", "vx", "wx",
]

# 评论去重指纹长度
COMMENT_FINGERPRINT_LEN = 30

# 评论上限
MAX_COMMENTS = 10

# GitHub 基础 URL，用于将相对路径转为完整 URL
GITHUB_BASE_URL = "https://github.com"

# YouTube 基础 URL
YOUTUBE_BASE_URL = "https://www.youtube.com"

# Google 基础 URL
GOOGLE_BASE_URL = "https://www.google.com"

# 平台 URL 前缀映射（相对路径 → 完整 URL）
_PLATFORM_BASE_URLS = {
    "github": GITHUB_BASE_URL,
    "youtube": YOUTUBE_BASE_URL,
    "google": GOOGLE_BASE_URL,
}


def _normalize_url(url: str, platform: str) -> str:
    """将相对 URL 补全为完整 URL。已是完整 URL 则原样返回。"""
    if not url:
        return url
    if url.startswith("http://") or url.startswith("https://"):
        return url
    base = _PLATFORM_BASE_URLS.get(platform)
    if base and url.startswith("/"):
        return base + url
    return url


class ResourceCollector:
    """从浏览器页面提取结构化资源数据"""

    @staticmethod
    async def extract_search_results(
        page: Any, config: PlatformConfig
    ) -> List[RawSearchResult]:
        """从搜索结果页通过 CSS 选择器提取结果列表。

        适用于非 JS 提取模式的平台（StackOverflow、YouTube 等）。
        """
        results: List[RawSearchResult] = []
        try:
            items = await page.query_selector_all(config.result_selector)
            for item in items:
                try:
                    title_el = await item.query_selector(config.title_selector)
                    title = (await title_el.inner_text()).strip() if title_el else ""

                    link_el = await item.query_selector(config.link_selector)
                    url = (await link_el.get_attribute("href")) or "" if link_el else ""

                    desc_el = await item.query_selector(config.description_selector)
                    description = (await desc_el.inner_text()).strip() if desc_el else ""

                    # URL 修正：跳过空 URL，相对 URL 补全为完整 URL
                    url = _normalize_url(url, config.name)
                    if config.name in ("github",) and not url:
                        continue

                    if not title and not url:
                        continue

                    results.append(RawSearchResult(
                        title=title,
                        url=url,
                        platform=config.name,
                        resource_type=config.resource_type,
                        description=description,
                    ))
                except Exception as e:
                    logger.debug(f"提取单条搜索结果失败: {e}")
                    continue
        except Exception as e:
            logger.warning(f"提取搜索结果列表失败 ({config.name}): {e}")
        return results

    @staticmethod
    async def extract_search_results_js(
        page: Any, config: PlatformConfig
    ) -> List[RawSearchResult]:
        """使用 JS evaluate 整体提取搜索结果（适用于小红书等动态 class 平台）。

        在页面内执行 JS 一次性提取所有可见的搜索结果卡片数据。
        """
        results: List[RawSearchResult] = []
        try:
            raw_items = await page.evaluate("""() => {
                const items = [];
                const cards = document.querySelectorAll('section.note-item, [data-note-id]');
                for (const card of cards) {
                    try {
                        const titleEl = card.querySelector('.title span, .title, a.title');
                        const linkEl = card.querySelector('a[href*="/explore/"], a[href*="/discovery/"]');
                        const descEl = card.querySelector('.desc, .note-desc');
                        const authorEl = card.querySelector('.author-wrapper .name, .author .name');
                        items.push({
                            title: titleEl ? titleEl.innerText.trim() : '',
                            url: linkEl ? linkEl.href : '',
                            description: descEl ? descEl.innerText.trim() : '',
                            author: authorEl ? authorEl.innerText.trim() : '',
                        });
                    } catch(e) {}
                }
                return items;
            }""")
            for item in (raw_items or []):
                title = item.get("title", "")
                url = item.get("url", "")
                if not title and not url:
                    continue
                results.append(RawSearchResult(
                    title=title,
                    url=url,
                    platform=config.name,
                    resource_type=config.resource_type,
                    description=item.get("description", ""),
                ))
        except Exception as e:
            logger.warning(f"JS 提取搜索结果失败 ({config.name}): {e}")
        return results

    @staticmethod
    def extract_from_intercepted_json(
        items: List[dict], config: PlatformConfig
    ) -> List[RawSearchResult]:
        """从拦截到的 API JSON 中提取搜索结果（混合模式）。

        解析小红书 /api/sns/web/v1/search/notes 响应中的 items 列表。
        按 note_id 去重，优先保留带 xsec_token 的链接。
        """
        results: List[RawSearchResult] = []
        seen: Dict[str, int] = {}  # note_id -> index in results

        for item in items:
            try:
                nc = item.get("note_card", {})
                if not nc:
                    continue

                note_id = nc.get("note_id", item.get("id", ""))
                if not note_id:
                    continue

                xsec_token = item.get("xsec_token", "")
                interact = nc.get("interact_info", {})
                user = nc.get("user", {})

                title = nc.get("display_title", "")
                if xsec_token:
                    url = (
                        f"https://www.xiaohongshu.com/explore/{note_id}"
                        f"?xsec_token={xsec_token}&xsec_source=pc_search"
                    )
                else:
                    url = f"https://www.xiaohongshu.com/explore/{note_id}"

                likes = _safe_int(interact.get("liked_count", 0))
                collected = _safe_int(interact.get("collected_count", 0))
                comments_count = _safe_int(interact.get("comment_count", 0))
                share_count = _safe_int(interact.get("share_count", 0))

                # 提取图片 URL
                image_urls = _extract_image_urls_from_note_card(nc)

                raw = RawSearchResult(
                    title=title,
                    url=url,
                    platform=config.name,
                    resource_type=config.resource_type,
                    description=nc.get("desc", ""),
                    engagement_metrics={
                        "likes": likes,
                        "collected": collected,
                        "comments_count": comments_count,
                        "share_count": share_count,
                        "author": user.get("nickname", ""),
                    },
                    image_urls=image_urls,
                )

                # 去重：优先保留带 xsec_token 的
                if note_id in seen:
                    if xsec_token:
                        results[seen[note_id]] = raw
                else:
                    seen[note_id] = len(results)
                    results.append(raw)
            except Exception as e:
                logger.debug(f"解析拦截 JSON 单条失败: {e}")
                continue

        return results

    @staticmethod
    async def extract_detail(
        page: Any, config: PlatformConfig
    ) -> ResourceDetail:
        """从详情页提取正文、互动指标和前 10 条评论。

        对于小红书平台优先使用 __INITIAL_STATE__，其他平台使用 CSS 选择器。
        """
        detail = ResourceDetail()
        try:
            ds = config.detail_selectors

            # 正文提取
            if config.detail_extract_method == "js_state":
                content = await ResourceCollector.extract_detail_from_initial_state(page)
                if content:
                    detail.content_snippet = content
            if not detail.content_snippet and ds.content_selector:
                for sel in ds.content_selector.split(","):
                    sel = sel.strip()
                    if not sel:
                        continue
                    try:
                        el = await page.query_selector(sel)
                        if el:
                            text = (await el.inner_text()).strip()
                            if len(text) > 20:
                                detail.content_snippet = text[:800]
                                break
                    except Exception:
                        continue

            # 互动指标
            detail.likes = await _extract_int_from_selector(page, ds.likes_selector)
            detail.favorites = await _extract_int_from_selector(page, ds.favorites_selector)
            detail.comments_count = await _extract_int_from_selector(page, ds.comments_count_selector)

            # 额外指标
            for key, sel in ds.extra_metrics.items():
                val = await _extract_int_from_selector(page, sel)
                if val > 0:
                    detail.extra_metrics[key] = val

            # 评论提取（CSS 选择器方式，非拦截模式的回退）
            if ds.comment_item_selector:
                comments_data = await ResourceCollector.extract_top_comments(page, config)
                detail.top_comments = comments_data[:MAX_COMMENTS]
                detail.comments = [c.get("text", "") for c in detail.top_comments]

        except Exception as e:
            logger.warning(f"详情页提取失败 ({config.name}): {e}")

        return detail

    @staticmethod
    async def extract_detail_from_initial_state(page: Any) -> str:
        """从 __INITIAL_STATE__ 内嵌 JSON 提取正文（三级回退策略）。

        1. 尝试匹配 __INITIAL_STATE__ = {...}</script> 格式
        2. 尝试匹配 __INITIAL_STATE__ = {...} 格式（宽松）
        3. DOM 选择器回退
        """
        try:
            result = await page.evaluate("""() => {
                try {
                    const scripts = document.querySelectorAll('script');
                    for (const s of scripts) {
                        const t = s.textContent || '';
                        if (t.includes('__INITIAL_STATE__')) {
                            const m = t.match(/__INITIAL_STATE__\\s*=\\s*({.+?})\\s*<?\\/?\\/?\\/script/s)
                                || t.match(/__INITIAL_STATE__\\s*=\\s*({.+})/s);
                            if (m) {
                                const cleaned = m[1].replace(/undefined/g, 'null');
                                const state = JSON.parse(cleaned);
                                const nd = state?.note?.noteDetailMap;
                                if (nd) {
                                    const k = Object.keys(nd)[0];
                                    const n = nd[k]?.note;
                                    if (n?.desc) return n.desc.substring(0, 800);
                                }
                            }
                        }
                    }
                } catch(e) {}
                return '';
            }""")
            return result or ""
        except Exception as e:
            logger.debug(f"__INITIAL_STATE__ 提取失败: {e}")
            return ""

    @staticmethod
    async def extract_image_urls(page_or_json: Any) -> List[str]:
        """从 __INITIAL_STATE__ 或 API JSON 的 image_list 字段提取图片 URL 列表。

        Args:
            page_or_json: Playwright Page 对象或已解析的 JSON dict
        """
        # 如果是 dict（API JSON 数据），直接从中提取
        if isinstance(page_or_json, dict):
            return _extract_image_urls_from_json(page_or_json)

        # 否则当作 Playwright Page，从 __INITIAL_STATE__ 提取
        try:
            result = await page_or_json.evaluate("""() => {
                try {
                    const scripts = document.querySelectorAll('script');
                    for (const s of scripts) {
                        const t = s.textContent || '';
                        if (t.includes('__INITIAL_STATE__')) {
                            const m = t.match(/__INITIAL_STATE__\\s*=\\s*({.+?})\\s*<?\\/?\\/?\\/script/s)
                                || t.match(/__INITIAL_STATE__\\s*=\\s*({.+})/s);
                            if (m) {
                                const cleaned = m[1].replace(/undefined/g, 'null');
                                const state = JSON.parse(cleaned);
                                const nd = state?.note?.noteDetailMap;
                                if (nd) {
                                    const k = Object.keys(nd)[0];
                                    const n = nd[k]?.note;
                                    if (n?.imageList) {
                                        return n.imageList.map(img =>
                                            img.urlDefault || img.url || ''
                                        ).filter(u => u.length > 0).slice(0, 9);
                                    }
                                }
                            }
                        }
                    }
                } catch(e) {}
                return [];
            }""")
            return result or []
        except Exception as e:
            logger.debug(f"图片 URL 提取失败: {e}")
            return []

    @staticmethod
    async def extract_top_comments(
        page: Any, config: PlatformConfig
    ) -> List[Dict[str, str]]:
        """提取高赞评论（文本+点赞数），按赞数排序。

        通过 CSS 选择器从页面 DOM 中提取评论，含去重和广告过滤。
        返回最多 MAX_COMMENTS 条。
        """
        comments: List[Dict[str, str]] = []
        ds = config.detail_selectors
        if not ds.comment_item_selector:
            return comments

        try:
            items = await page.query_selector_all(ds.comment_item_selector)
            seen_texts: set = set()

            for item in items:
                try:
                    text_el = item
                    text = (await text_el.inner_text()).strip()
                    if not text or len(text) <= 2:
                        continue

                    # 去重
                    fingerprint = text[:COMMENT_FINGERPRINT_LEN].strip().lower()
                    if fingerprint in seen_texts:
                        continue
                    seen_texts.add(fingerprint)

                    # 广告过滤
                    if _is_ad_comment(text):
                        continue

                    # 点赞数
                    likes_str = "0"
                    if ds.comment_likes_selector:
                        try:
                            likes_el = await item.query_selector(ds.comment_likes_selector)
                            if likes_el:
                                likes_str = (await likes_el.inner_text()).strip()
                        except Exception:
                            pass

                    comments.append({
                        "text": text[:300],
                        "likes": likes_str,
                    })
                except Exception:
                    continue

            # 按赞数排序
            comments.sort(key=lambda c: _safe_int(c.get("likes", "0")), reverse=True)
        except Exception as e:
            logger.debug(f"评论提取失败: {e}")

        return comments[:MAX_COMMENTS]

    @staticmethod
    def parse_intercepted_comments(
        raw_comments: List[dict],
    ) -> List[Dict[str, str]]:
        """从拦截到的评论 API JSON 中解析评论，含去重和广告过滤。

        解析 /api/sns/web/v2/comment/page 响应中的 comments 列表。
        返回最多 MAX_COMMENTS 条，按点赞数降序排序。
        """
        parsed: List[Dict[str, str]] = []
        seen_texts: set = set()

        for c in raw_comments:
            try:
                text = c.get("content", "")
                if not text or len(text) <= 2:
                    continue

                # 去重：前 30 字指纹
                fingerprint = text[:COMMENT_FINGERPRINT_LEN].strip().lower()
                if fingerprint in seen_texts:
                    continue
                seen_texts.add(fingerprint)

                # 广告过滤
                if _is_ad_comment(text):
                    continue

                likes = _safe_int(c.get("like_count", 0))
                author = c.get("user_info", {}).get("nickname", "")

                parsed.append({
                    "text": text[:300],
                    "likes": str(likes),
                    "author": author,
                })
            except Exception:
                continue

        parsed.sort(key=lambda x: _safe_int(x.get("likes", "0")), reverse=True)
        return parsed[:MAX_COMMENTS]


# ============================================================
# 内部辅助函数
# ============================================================


def _safe_int(value: Any) -> int:
    """安全转换为 int，失败返回 0。"""
    try:
        return int(value or 0)
    except (ValueError, TypeError):
        # 处理 "1.3万" 等中文数字字符串
        if isinstance(value, str):
            value = value.strip().replace(",", "")
            m = re.match(r"([\d.]+)\s*万", value)
            if m:
                return int(float(m.group(1)) * 10000)
            m = re.match(r"([\d.]+)\s*千", value)
            if m:
                return int(float(m.group(1)) * 1000)
            m = re.match(r"[\d]+", value)
            if m:
                return int(m.group(0))
        return 0


def _is_ad_comment(text: str) -> bool:
    """检查评论是否为广告（包含 2 个及以上营销关键词）。"""
    text_lower = text.lower()
    ad_count = sum(1 for kw in AD_KEYWORDS if kw in text_lower)
    return ad_count >= 2


def _extract_image_urls_from_note_card(nc: dict) -> List[str]:
    """从 note_card JSON 中提取图片 URL 列表。"""
    urls: List[str] = []
    try:
        image_list = nc.get("image_list", nc.get("images_list", []))
        for img in (image_list or []):
            url = img.get("url_default", img.get("url", img.get("urlDefault", "")))
            if url and (url.startswith("http://") or url.startswith("https://")):
                urls.append(url)
    except Exception:
        pass
    return urls[:9]


def _extract_image_urls_from_json(data: dict) -> List[str]:
    """从 API JSON 数据中提取图片 URL 列表。

    支持多种 JSON 结构：
    - note_card.image_list
    - note.imageList
    - data.note.imageList
    """
    urls: List[str] = []
    try:
        # 尝试 note_card 结构
        nc = data.get("note_card", data)
        image_list = (
            nc.get("image_list")
            or nc.get("images_list")
            or nc.get("imageList")
            or []
        )

        # 尝试嵌套 note 结构
        if not image_list:
            note = nc.get("note", data.get("note", {}))
            image_list = note.get("imageList", note.get("image_list", []))

        for img in (image_list or []):
            if isinstance(img, str):
                url = img
            elif isinstance(img, dict):
                url = img.get("urlDefault", img.get("url_default", img.get("url", "")))
            else:
                continue
            if url and (url.startswith("http://") or url.startswith("https://")):
                urls.append(url)
    except Exception:
        pass
    return urls[:9]


async def _extract_int_from_selector(page: Any, selector: str) -> int:
    """从页面选择器提取整数值，失败返回 0。"""
    if not selector:
        return 0
    try:
        el = await page.query_selector(selector)
        if el:
            text = (await el.inner_text()).strip()
            return _safe_int(text)
    except Exception:
        pass
    return 0
