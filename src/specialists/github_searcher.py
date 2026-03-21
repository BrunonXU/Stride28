"""
GitHub 仓库搜索器

使用 GitHub Search API 搜索仓库，按 stars 降序排列。
抓取 README 内容供 QualityAssessor LLM 评估学习价值。
API 失败时回退到构造 GitHub 搜索链接作为降级结果。

两阶段设计：
1. 初筛：GitHub Search API + stars 降序 + fork:false + stars>=10
2. 精排：抓 README → 送 QualityAssessor LLM 评估（由 PipelineExecutor 驱动）
"""

import logging
import re
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import quote

import httpx

from src.specialists.browser_models import RawSearchResult

logger = logging.getLogger(__name__)


class GithubSearcher:
    """GitHub 仓库搜索（httpx API 直连）"""

    SEARCH_API = "https://api.github.com/search/repositories"
    README_RAW_URL = "https://raw.githubusercontent.com/{owner}/{repo}/HEAD/README.md"
    TIMEOUT = 10  # 秒
    README_TIMEOUT = 5  # 单个 README 抓取超时
    MIN_STARS = 10  # 最低 stars 阈值，过滤噪音

    HEADERS = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Stride28-Learning-Agent/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    def __init__(self, github_token: Optional[str] = None, api_cache=None):
        """
        初始化 GithubSearcher。

        Args:
            github_token: GitHub Personal Access Token（可选）。
                          无 token 时 API 限制 10 次/分钟，有 token 30 次/分钟。
            api_cache: APICache 实例（可选），用于缓存 API 响应。
        """
        self._token = github_token
        self._api_cache = api_cache
        if github_token:
            self.HEADERS["Authorization"] = f"Bearer {github_token}"

    async def search(self, query: str, limit: int = 10) -> List[RawSearchResult]:
        """搜索 GitHub 仓库，返回 RawSearchResult 列表。

        Args:
            query: 搜索关键词
            limit: 返回结果数量限制

        Returns:
            RawSearchResult 列表，失败时返回降级搜索链接
        """
        try:
            # Search API 缓存
            if self._api_cache:
                cached = self._api_cache.get("github_search", query=query, limit=limit)
                if cached is not None:
                    logger.debug(f"GitHub Search 缓存命中: query={query[:30]}")
                    results = cached
                else:
                    results = await self._search_api(query, limit)
                    if results and self._api_cache:
                        self._api_cache.set("github_search", results, query=query, limit=limit)
            else:
                results = await self._search_api(query, limit)

            if results:
                results = await self._enrich_with_readme(results)
                logger.info(f"GitHub API 搜索成功: {len(results)} 条结果")
                return results
        except Exception as e:
            logger.warning(f"GitHub API 搜索失败: {e}")

        return self._fallback_result(query)

    async def _search_api(self, query: str, limit: int) -> List[RawSearchResult]:
        """调用 GitHub Search API 搜索仓库。

        查询自动附加 fork:false + stars>=MIN_STARS，按 stars 降序排列。
        """
        # 构造查询：排除 fork，最低 stars 阈值
        q = f"{query} fork:false stars:>={self.MIN_STARS}"

        params = {
            "q": q,
            "sort": "stars",
            "order": "desc",
            "per_page": min(limit, 30),  # GitHub API 单页最多 100，但搜索建议 ≤30
        }

        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            response = await client.get(
                self.SEARCH_API,
                params=params,
                headers=self.HEADERS,
            )
            response.raise_for_status()
            data = response.json()

        items = data.get("items", [])
        if not items:
            return []

        results = []
        for item in items[:limit]:
            result = self._parse_repo_item(item)
            if result:
                results.append(result)

        return results

    async def _enrich_with_readme(
        self, results: List[RawSearchResult]
    ) -> List[RawSearchResult]:
        """并发抓取每个仓库的 README，填充到 content_snippet。

        README 抓取失败不影响结果，content_snippet 保持为空或 description。
        """
        import asyncio

        async def _fetch_readme(result: RawSearchResult) -> None:
            """抓取单个仓库的 README（带 APICache）。"""
            owner_repo = self._extract_owner_repo(result.url)
            if not owner_repo:
                return

            owner, repo = owner_repo

            # README 缓存
            if self._api_cache:
                cached = self._api_cache.get("github_readme", owner=owner, repo=repo)
                if cached is not None:
                    result.content_snippet = cached
                    return

            readme_url = self.README_RAW_URL.format(owner=owner, repo=repo)

            try:
                async with httpx.AsyncClient(timeout=self.README_TIMEOUT) as client:
                    resp = await client.get(readme_url, headers=self.HEADERS)
                    if resp.status_code == 200:
                        readme_text = resp.text
                        cleaned = self._clean_readme(readme_text)
                        result.content_snippet = cleaned[:3000]
                        # 写入缓存
                        if self._api_cache:
                            self._api_cache.set("github_readme", result.content_snippet, owner=owner, repo=repo)
                    else:
                        logger.debug(f"README 获取失败 ({resp.status_code}): {owner}/{repo}")
            except Exception as e:
                logger.debug(f"README 抓取异常 {owner}/{repo}: {e}")

        tasks = [_fetch_readme(r) for r in results]
        await asyncio.gather(*tasks, return_exceptions=True)

        return results

    def _parse_repo_item(self, item: dict) -> Optional[RawSearchResult]:
        """解析单个仓库搜索结果。"""
        try:
            full_name = item.get("full_name", "")
            name = item.get("name", "")
            html_url = item.get("html_url", "")

            if not full_name or not html_url:
                return None

            title = full_name
            description = item.get("description") or ""

            # 互动数据
            stars = self._safe_int(item.get("stargazers_count", 0))
            forks = self._safe_int(item.get("forks_count", 0))
            open_issues = self._safe_int(item.get("open_issues_count", 0))
            watchers = self._safe_int(item.get("watchers_count", 0))

            # 额外元数据
            language = item.get("language") or ""
            topics = item.get("topics", [])
            updated_at = item.get("updated_at", "")
            license_info = item.get("license")
            license_name = license_info.get("spdx_id", "") if license_info else ""

            # 构造描述：包含语言、topics、license 等关键信息
            desc_parts = []
            if description:
                desc_parts.append(description[:300])
            meta_parts = []
            if language:
                meta_parts.append(f"语言: {language}")
            if topics:
                meta_parts.append(f"标签: {', '.join(topics[:5])}")
            if license_name:
                meta_parts.append(f"许可: {license_name}")
            if updated_at:
                meta_parts.append(f"更新: {updated_at[:10]}")
            if meta_parts:
                desc_parts.append(" | ".join(meta_parts))

            full_description = "\n".join(desc_parts)

            return RawSearchResult(
                title=title,
                url=html_url,
                platform="github",
                resource_type="repo",
                description=full_description,
                engagement_metrics={
                    "stars": stars,
                    "forks": forks,
                    "open_issues": open_issues,
                    "watchers": watchers,
                    "language": language,
                    "updated_at": updated_at,
                },
                # 四层 metadata
                source_tier="developer",
                author=item.get("owner", {}).get("login", ""),
                publish_time=item.get("created_at", ""),
                fetched_at=datetime.now(timezone.utc).isoformat(),
                extraction_mode="github_api",
                source_metadata={
                    "language": language,
                    "topics": topics[:5],
                    "license": license_name,
                    "default_branch": item.get("default_branch", ""),
                },
            )
        except Exception as e:
            logger.debug(f"解析 GitHub 仓库项失败: {e}")
            return None

    @staticmethod
    def _clean_readme(text: str) -> str:
        """清理 README 中的 HTML 标签和 Markdown 噪音，提取可读纯文本。

        处理顺序：
        1. 移除 HTML 注释
        2. 移除 HTML 标签（保留标签内文本）
        3. 移除 Markdown 图片/badge（![alt](url)）
        4. 保留 Markdown 链接文本（[text](url) → text）
        5. 移除 Markdown 标题符号（### → 空）
        6. 清理多余空行
        """
        if not text:
            return ""

        # HTML 注释
        text = re.sub(r"<!--[\s\S]*?-->", "", text)
        # HTML 标签（保留内部文本）
        text = re.sub(r"<[^>]+>", "", text)
        # Markdown 图片/badge
        text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
        # Markdown 链接 → 保留文本
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
        # Markdown 标题符号
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        # Markdown 粗体/斜体
        text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
        # Markdown 分隔线
        text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
        # 多余空行压缩为单个
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()

    @staticmethod
    def _extract_owner_repo(url: str) -> Optional[tuple]:
        """从 GitHub URL 提取 owner/repo。

        例如 https://github.com/owner/repo → ("owner", "repo")
        """
        try:
            parts = url.rstrip("/").split("/")
            if len(parts) >= 2:
                return parts[-2], parts[-1]
        except Exception:
            pass
        return None

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
        """降级结果：返回 GitHub 搜索链接。"""
        search_url = f"https://github.com/search?q={quote(query)}&type=repositories&s=stars&o=desc"
        return [
            RawSearchResult(
                title=f"在 GitHub 搜索「{query}」",
                url=search_url,
                platform="github",
                resource_type="repo",
                description="点击链接在 GitHub 查看更多搜索结果",
                engagement_metrics={},
                source_tier="developer",
                fetched_at=datetime.now(timezone.utc).isoformat(),
                extraction_mode="github_fallback_link",
            )
        ]

    async def close(self):
        """资源清理（GitHub 不使用浏览器，无需清理，但保持接口一致）。"""
        pass
