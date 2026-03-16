"""
小红书搜索器

基于 MediaCrawler 签名算法，使用 Playwright + httpx 实现小红书搜索。
签名核心代码从 MediaCrawler 源码提取，避免导入 MediaCrawler 包（会触发 cv2 等依赖）。
流程：Playwright 加载小红书页面获取签名环境 → httpx 发送 API 请求。
"""

import asyncio
import ctypes
import hashlib
import json
import logging
import os
import random
import sys
import time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote as _url_quote

import httpx
from playwright.async_api import BrowserContext, Page, async_playwright

from src.specialists.browser_models import RawSearchResult

logger = logging.getLogger(__name__)

# 路径常量
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
COOKIE_FILE = _PROJECT_ROOT / "scripts" / ".xhs_cookies.json"
STEALTH_JS = _PROJECT_ROOT / "scripts" / "MediaCrawler" / "libs" / "stealth.min.js"
XHS_INDEX = "https://www.xiaohongshu.com/explore"
XHS_HOST = "https://edith.xiaohongshu.com"
REQUEST_INTERVAL = 1.0  # 请求间隔（秒）


# ============================================================
# 签名算法（提取自 MediaCrawler xhs_sign.py + playwright_sign.py + help.py）
# ============================================================

_BASE64_CHARS = list("ZmserbBoHQtNP+wOcza/LpngG8yJq42KWYj0DSfdikx3VT16IlUAFM97hECvuRX5")
_CRC32_TABLE = [
    0,1996959894,3993919788,2567524794,124634137,1886057615,3915621685,2657392035,
    249268274,2044508324,3772115230,2547177864,162941995,2125561021,3887607047,2428444049,
    498536548,1789927666,4089016648,2227061214,450548861,1843258603,4107580753,2211677639,
    325883990,1684777152,4251122042,2321926636,335633487,1661365465,4195302755,2366115317,
    997073096,1281953886,3579855332,2724688242,1006888145,1258607687,3524101629,2768942443,
    901097722,1119000684,3686517206,2898065728,853044451,1172266101,3705015759,2882616665,
    651767980,1373503546,3369554304,3218104598,565507253,1454621731,3485111705,3099436303,
    671266974,1594198024,3322730930,2970347812,795835527,1483230225,3244367275,3060149565,
    1994146192,31158534,2563907772,4023717930,1907459465,112637215,2680153253,3904427059,
    2013776290,251722036,2517215374,3775830040,2137656763,141376813,2439277719,3865271297,
    1802195444,476864866,2238001368,4066508878,1812370925,453092731,2181625025,4111451223,
    1706088902,314042704,2344532202,4240017532,1658658271,366619977,2362670323,4224994405,
    1303535960,984961486,2747007092,3569037538,1256170817,1037604311,2765210733,3554079995,
    1131014506,879679996,2909243462,3663771856,1141124467,855842277,2852801631,3708648649,
    1342533948,654459306,3188396048,3373015174,1466479909,544179635,3110523913,3462522015,
    1591671054,702138776,2966460450,3352799412,1504918807,783551873,3082640443,3233442989,
    3988292384,2596254646,62317068,1957810842,3939845945,2647816111,81470997,1943803523,
    3814918930,2489596804,225274430,2053790376,3826175755,2466906013,167816743,2097651377,
    4027552580,2265490386,503444072,1762050814,4150417245,2154129355,426522225,1852507879,
    4275313526,2312317920,282753626,1742555852,4189708143,2394877945,397917763,1622183637,
    3604390888,2714866558,953729732,1340076626,3518719985,2797360999,1068828381,1219638859,
    3624741850,2936675148,906185462,1090812512,3747672003,2825379669,829329135,1181335161,
    3412177804,3160834842,628085408,1382605366,3423369109,3138078467,570562233,1426400815,
    3317316542,2998733608,733239954,1555261956,3268935591,3050360625,752459403,1541320221,
    2607071920,3965973030,1969922972,40735498,2617837225,3943577151,1913087877,83908371,
    2512341634,3803740692,2075208622,213261112,2463272603,3855990285,2094854071,198958881,
    2262029012,4057260610,1759359992,534414190,2176718541,4139329115,1873836001,414664567,
    2282248934,4279200368,1711684554,285281116,2405801727,4167216745,1634467795,376229701,
    2685067896,3608007406,1308918612,956543938,2808555105,3495958263,1231636301,1047427035,
    2932959818,3654703836,1088359270,936918000,2847714899,3736837829,1202900863,817233897,
    3183342108,3401237130,1404277552,615818150,3134207493,3453421203,1423857449,601450431,
    3009837614,3294710456,1567103746,711928724,3020668471,3272380065,1510334235,755167117,
]


def _rshift_unsigned(num, bit=0):
    val = ctypes.c_uint32(num).value >> bit
    M = 4294967295
    return (val + (M + 1)) % (2 * (M + 1)) - M - 1


def _mrc(e):
    o = -1
    for n in range(min(57, len(e))):
        o = _CRC32_TABLE[(o & 255) ^ ord(e[n])] ^ _rshift_unsigned(o, 8)
    return o ^ -1 ^ 3988292384


def _encode_utf8(s):
    encoded = _url_quote(s, safe="~()*!.'")
    result, i = [], 0
    while i < len(encoded):
        if encoded[i] == "%":
            result.append(int(encoded[i+1:i+3], 16)); i += 3
        else:
            result.append(ord(encoded[i])); i += 1
    return result


def _triplet_b64(e):
    return _BASE64_CHARS[(e>>18)&63] + _BASE64_CHARS[(e>>12)&63] + _BASE64_CHARS[(e>>6)&63] + _BASE64_CHARS[e&63]


def _b64_encode(data):
    L = len(data); rem = L % 3; chunks = []; main = L - rem
    for i in range(0, main, 16383):
        end = min(i+16383, main); parts = []
        for j in range(i, end, 3):
            c = ((data[j]<<16)&0xFF0000)+((data[j+1]<<8)&0xFF00)+(data[j+2]&0xFF)
            parts.append(_triplet_b64(c))
        chunks.append("".join(parts))
    if rem == 1:
        a = data[L-1]; chunks.append(_BASE64_CHARS[a>>2]+_BASE64_CHARS[(a<<4)&63]+"==")
    elif rem == 2:
        a = (data[L-2]<<8)+data[L-1]
        chunks.append(_BASE64_CHARS[a>>10]+_BASE64_CHARS[(a>>4)&63]+_BASE64_CHARS[(a<<2)&63]+"=")
    return "".join(chunks)


def _get_trace_id():
    return "".join(random.choice("abcdef0123456789") for _ in range(16))


def _build_sign_string(uri, data=None, method="POST"):
    if method.upper() == "POST":
        c = uri
        if data is not None:
            c += json.dumps(data, separators=(",",":"), ensure_ascii=False) if isinstance(data, dict) else str(data)
        return c
    if not data or (isinstance(data, dict) and not data):
        return uri
    if isinstance(data, dict):
        parts = []
        for k, v in data.items():
            vs = ",".join(str(x) for x in v) if isinstance(v, list) else (str(v) if v is not None else "")
            parts.append(f"{k}={_url_quote(vs, safe='')}")
        return f"{uri}?{'&'.join(parts)}"
    return f"{uri}?{data}" if isinstance(data, str) else uri


def _md5(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _build_xs_payload(x3, dtype="object"):
    s = {"x0":"4.2.1","x1":"xhs-pc-web","x2":"Mac OS","x3":x3,"x4":dtype}
    return "XYS_" + _b64_encode(_encode_utf8(json.dumps(s, separators=(",",":"))))


def _build_xs_common(a1, b1, x_s, x_t):
    p = {"s0":3,"s1":"","x0":"1","x1":"4.2.2","x2":"Mac OS","x3":"xhs-pc-web",
         "x4":"4.74.0","x5":a1,"x6":x_t,"x7":x_s,"x8":b1,"x9":_mrc(x_t+x_s+b1),"x10":154,"x11":"normal"}
    return _b64_encode(_encode_utf8(json.dumps(p, separators=(",",":"))))


async def _call_mnsv2(page, sign_str, md5_str):
    s = sign_str.replace("\\","\\\\").replace("'","\\'").replace("\n","\\n")
    m = md5_str.replace("\\","\\\\").replace("'","\\'")
    try:
        r = await page.evaluate(f"window.mnsv2('{s}','{m}')")
        return r or ""
    except Exception:
        return ""


async def _sign_xs(page, uri, data=None, method="POST"):
    ss = _build_sign_string(uri, data, method)
    x3 = await _call_mnsv2(page, ss, _md5(ss))
    return _build_xs_payload(x3, "object" if isinstance(data, (dict, list)) else "string")


async def _sign_full(page, uri, data=None, a1="", method="POST"):
    """生成完整签名头"""
    try:
        ls = await page.evaluate("()=>window.localStorage")
        b1 = ls.get("b1", "")
    except Exception:
        b1 = ""
    x_s = await _sign_xs(page, uri, data, method)
    x_t = str(int(time.time()*1000))
    return {"x-s": x_s, "x-t": x_t, "x-s-common": _build_xs_common(a1, b1, x_s, x_t), "x-b3-traceid": _get_trace_id()}


def _base36encode(number):
    alpha = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    if 0 <= number < 36:
        return alpha[number]
    r = ''
    while number:
        number, i = divmod(number, 36)
        r = alpha[i] + r
    return r


def _get_search_id():
    e = int(time.time()*1000) << 64
    t = int(random.uniform(0, 2147483646))
    return _base36encode((e+t) & 0xFFFFFFFFFFFFFFFF)


class SearchSortType(Enum):
    GENERAL = "general"
    MOST_POPULAR = "popularity_descending"
    LATEST = "time_descending"

class SearchNoteType(Enum):
    ALL = 0
    VIDEO = 1
    IMAGE = 2


# ============================================================
# XhsSearcher 主类
# ============================================================

class XhsSearcher:
    """小红书搜索器"""

    def __init__(self):
        self._browser_context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._playwright = None
        self._pw_cm = None
        self._cookie_dict: Dict[str, str] = {}
        self._cookie_str: str = ""
        self._headers: Dict[str, str] = {}
        self._initialized = False

    async def search(self, query: str, limit: int = 10) -> List[RawSearchResult]:
        """搜索小红书笔记，返回含正文、互动数据、评论的 RawSearchResult 列表。"""
        try:
            if not self._initialized:
                await self._init_browser()

            notes_res = await self._search_notes(query, limit)
            if not notes_res:
                logger.warning(f"小红书搜索无结果 (query='{query}')")
                return []

            items = [it for it in notes_res.get("items", [])
                     if it.get("model_type") not in ("rec_query", "hot_query")][:limit]
            logger.info(f"小红书搜索 items: 总 {len(notes_res.get('items', []))} 条, 过滤后 {len(items)} 条 (query='{query}')")
            if not items:
                return []

            # 串行获取详情+评论（签名依赖同一个 page，不能并发 evaluate）
            results: List[RawSearchResult] = []
            for item in items:
                try:
                    nid = item.get("id", "")
                    xsec_src = item.get("xsec_source", "pc_search")
                    xsec_tok = item.get("xsec_token", "")
                    detail = await self._get_note_detail(nid, xsec_src, xsec_tok)
                    comments = await self._get_comments(nid, xsec_tok, max_count=10)
                    await asyncio.sleep(REQUEST_INTERVAL)
                    r = self._build_result(item, detail, comments)
                    if r:
                        results.append(r)
                except Exception as e:
                    logger.warning(f"处理笔记失败 [{item.get('id','')}]: {e}")

            logger.info(f"小红书搜索完成: {len(results)} 条结果")
            return results
        except Exception as e:
            logger.error(f"小红书搜索异常: {e}")
            return []

    # ---- 浏览器初始化 ----

    async def _init_browser(self):
        """启动 Playwright，加载 Cookie，初始化签名环境。"""
        logger.info("初始化小红书签名浏览器...")
        self._pw_cm = async_playwright()
        self._playwright = await self._pw_cm.start()

        cookies = self._load_cookies()
        self._browser_context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(_PROJECT_ROOT / "browser_data" / "xhs"),
            headless=True,
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        )
        if STEALTH_JS.exists():
            await self._browser_context.add_init_script(path=str(STEALTH_JS))
        if cookies:
            await self._browser_context.add_cookies(cookies)

        self._page = await self._browser_context.new_page()
        await self._page.goto(XHS_INDEX, wait_until="domcontentloaded", timeout=30000)
        await self._page.wait_for_timeout(3000)

        await self._refresh_cookies()
        need_login = not self._cookie_dict.get("web_session")

        # web_session 存在但可能被封禁，用 selfinfo 接口验证（参照 MediaCrawler pong）
        if not need_login:
            try:
                self._build_base_headers()
                self_info = await self._signed_request("GET", "/api/sns/web/v1/user/selfinfo", params={})
                if self_info and self_info.get("result", {}).get("success"):
                    logger.info("小红书 cookie 验证通过")
                else:
                    logger.warning("小红书 cookie 验证失败（selfinfo 无效），需要重新登录")
                    need_login = True
            except Exception as e:
                logger.warning(f"小红书 cookie 验证失败: {e}，需要重新登录")
                need_login = True

        if need_login:
            # 关闭当前 headless 浏览器，清数据，弹可见浏览器登录
            try:
                if self._browser_context:
                    await self._browser_context.close()
                    self._browser_context = None
                    self._page = None
                if self._pw_cm:
                    await self._pw_cm.__aexit__(None, None, None)
                    self._playwright = None
                    self._pw_cm = None
            except Exception:
                pass

            import shutil
            xhs_data = _PROJECT_ROOT / "browser_data" / "xhs"
            if xhs_data.exists():
                shutil.rmtree(xhs_data, ignore_errors=True)
            if COOKIE_FILE.exists():
                COOKIE_FILE.unlink(missing_ok=True)

            await self._interactive_login()
            return  # _interactive_login 末尾会递归调用 _init_browser 完成初始化

        self._build_base_headers()
        self._initialized = True
        logger.info("小红书签名环境就绪")

        self._build_base_headers()
        self._initialized = True
        logger.info("小红书签名环境就绪")

    async def _interactive_login(self):
        """弹出可见浏览器让用户手动登录。"""
        logger.info("=" * 50)
        logger.info("需要登录小红书，即将弹出浏览器窗口")
        logger.info("请手动登录，登录成功后自动检测（最多等 5 分钟）")
        logger.info("=" * 50)

        # 确保之前的浏览器已关闭
        try:
            if self._browser_context:
                await self._browser_context.close()
                self._browser_context = None
                self._page = None
            if self._pw_cm:
                await self._pw_cm.__aexit__(None, None, None)
                self._playwright = None
                self._pw_cm = None
        except Exception:
            pass

        self._pw_cm = async_playwright()
        self._playwright = await self._pw_cm.start()
        self._browser_context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(_PROJECT_ROOT / "browser_data" / "xhs"),
            headless=False,
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        )
        if STEALTH_JS.exists():
            await self._browser_context.add_init_script(path=str(STEALTH_JS))
        self._page = await self._browser_context.new_page()
        await self._page.goto(XHS_INDEX, wait_until="domcontentloaded", timeout=30000)

        logged_in = False
        for i in range(60):  # 60 * 5s = 5 分钟
            await self._page.wait_for_timeout(5000)
            await self._refresh_cookies()
            if not self._cookie_dict.get("web_session"):
                if i % 6 == 0:
                    logger.info(f"等待登录中... ({(i+1)*5}s / 300s)")
                continue
            # web_session 存在，用 selfinfo 验证是否真的登录了
            try:
                self._build_base_headers()
                self_info = await self._signed_request("GET", "/api/sns/web/v1/user/selfinfo", params={})
                if self_info and self_info.get("result", {}).get("success"):
                    logger.info("登录验证通过！")
                    self._save_cookies(await self._browser_context.cookies())
                    logged_in = True
                    break
                else:
                    if i % 6 == 0:
                        logger.info(f"web_session 存在但未真正登录，继续等待... ({(i+1)*5}s / 300s)")
            except Exception:
                if i % 6 == 0:
                    logger.info(f"等待登录中... ({(i+1)*5}s / 300s)")

        if not logged_in:
            raise RuntimeError("登录超时（5分钟）")

        # 登录成功，关闭可见浏览器，重新用 headless 启动
        try:
            await self._browser_context.close()
            self._browser_context = None
            self._page = None
            await self._pw_cm.__aexit__(None, None, None)
            self._playwright = None
            self._pw_cm = None
        except Exception:
            pass

        # 重新初始化 headless 浏览器（这次 cookie 有效，不会再弹登录）
        await self._init_browser()

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
        except Exception as e:
            logger.warning(f"保存 Cookie 失败: {e}")

    async def _refresh_cookies(self):
        cookies = await self._browser_context.cookies()
        self._cookie_dict = {c["name"]: c["value"] for c in cookies}
        self._cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)

    def _build_base_headers(self):
        self._headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9",
            "cache-control": "no-cache",
            "content-type": "application/json;charset=UTF-8",
            "origin": "https://www.xiaohongshu.com",
            "pragma": "no-cache",
            "referer": "https://www.xiaohongshu.com/",
            "sec-ch-ua": '"Chromium";v="136","Google Chrome";v="136","Not.A/Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
            "Cookie": self._cookie_str,
        }

    # ---- API 请求 ----

    async def _signed_request(self, method: str, uri: str,
                               params: Optional[Dict] = None,
                               payload: Optional[Dict] = None) -> Dict:
        a1 = self._cookie_dict.get("a1", "")
        data = params if method.upper() == "GET" else payload
        signs = await _sign_full(self._page, uri, data, a1, method.upper())

        headers = {**self._headers}
        headers["X-S"] = signs["x-s"]
        headers["X-T"] = signs["x-t"]
        headers["x-S-Common"] = signs["x-s-common"]
        headers["X-B3-Traceid"] = signs["x-b3-traceid"]

        url = f"{XHS_HOST}{uri}"
        async with httpx.AsyncClient() as client:
            if method.upper() == "GET":
                resp = await client.get(url, headers=headers, params=params, timeout=15)
            else:
                body = json.dumps(payload, separators=(",",":"), ensure_ascii=False)
                resp = await client.post(url, headers=headers, content=body, timeout=15)

        d = resp.json()
        if d.get("success"):
            return d.get("data", {})
        code, msg = d.get("code", -1), d.get("msg", "")
        raise RuntimeError(f"XHS API [{code}]: {msg}")

    async def _search_notes(self, keyword: str, limit: int = 20) -> Dict:
        return await self._signed_request("POST", "/api/sns/web/v1/search/notes", payload={
            "keyword": keyword, "page": 1, "page_size": min(limit, 20),
            "search_id": _get_search_id(),
            "sort": SearchSortType.GENERAL.value,
            "note_type": SearchNoteType.ALL.value,
        })

    async def _get_note_detail(self, note_id: str, xsec_source: str, xsec_token: str) -> Dict:
        try:
            res = await self._signed_request("POST", "/api/sns/web/v1/feed", payload={
                "source_note_id": note_id,
                "image_formats": ["jpg", "webp", "avif"],
                "extra": {"need_body_topic": 1},
                "xsec_source": xsec_source or "pc_search",
                "xsec_token": xsec_token,
            })
            if res and res.get("items"):
                return res["items"][0].get("note_card", {})
        except Exception as e:
            logger.warning(f"获取笔记详情失败 [{note_id}]: {e}")
        return {}

    async def _get_comments(self, note_id: str, xsec_token: str, max_count: int = 10) -> List[Dict]:
        result, cursor, has_more = [], "", True
        while has_more and len(result) < max_count:
            try:
                res = await self._signed_request("GET", "/api/sns/web/v2/comment/page", params={
                    "note_id": note_id, "cursor": cursor, "top_comment_id": "",
                    "image_formats": "jpg,webp,avif", "xsec_token": xsec_token,
                })
                has_more = res.get("has_more", False)
                cursor = res.get("cursor", "")
                comments = res.get("comments", [])
                if not comments:
                    break
                result.extend(comments[:max_count - len(result)])
                if has_more and len(result) < max_count:
                    await asyncio.sleep(REQUEST_INTERVAL)
            except Exception as e:
                logger.warning(f"获取评论失败 [{note_id}]: {e}")
                break
        return result

    # ---- 数据转换 ----

    def _build_result(self, search_item: Dict, detail: Dict, comments: List[Dict]) -> Optional[RawSearchResult]:
        try:
            note_id = search_item.get("id", "")
            xsec_token = search_item.get("xsec_token", "")
            xsec_src = search_item.get("xsec_source", "pc_search")
            title = (detail.get("title", "")
                     or search_item.get("note_card", {}).get("display_title", "")
                     or "")
            if not title:
                return None

            desc = detail.get("desc", "") or ""
            interact = detail.get("interact_info", {})
            liked = self._safe_int(interact.get("liked_count", 0))
            collected = self._safe_int(interact.get("collected_count", 0))
            comment_cnt = self._safe_int(interact.get("comment_count", 0))
            shares = self._safe_int(interact.get("share_count", 0))

            imgs = []
            for img in detail.get("image_list", []):
                info = img.get("info_list", [])
                if info:
                    imgs.append(info[0].get("url", ""))
                elif img.get("url_default"):
                    imgs.append(img["url_default"])

            top_comments, texts = [], []
            for c in comments:
                t = c.get("content", "")
                if t:
                    texts.append(t)
                    top_comments.append({
                        "text": t,
                        "likes": self._safe_int(c.get("like_count", 0)),
                        "author": c.get("user_info", {}).get("nickname", ""),
                    })

            # 带 xsec_token 的链接才能在浏览器中直接打开，与 resource_collector 保持一致
            if xsec_token:
                url = (
                    f"https://www.xiaohongshu.com/explore/{note_id}"
                    f"?xsec_token={xsec_token}&xsec_source={xsec_src}"
                )
            else:
                url = f"https://www.xiaohongshu.com/explore/{note_id}"

            return RawSearchResult(
                title=title,
                url=url,
                platform="xiaohongshu",
                resource_type="note",
                description=desc[:500],
                content_snippet=desc[:1000],
                engagement_metrics={"likes": liked, "collected": collected, "comments_count": comment_cnt, "shares": shares},
                comments=texts[:10],
                top_comments=top_comments[:10],
                image_urls=imgs[:9],
                deduplicated_comment_count=len(set(texts)),
            )
        except Exception as e:
            logger.warning(f"构建结果失败: {e}")
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

    # ---- 资源清理 ----

    async def close(self):
        self._initialized = False
        try:
            if self._browser_context:
                try:
                    cookies = await self._browser_context.cookies()
                    if cookies:
                        self._save_cookies(cookies)
                except Exception:
                    pass
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
