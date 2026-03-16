"""
GitHub 仓库分析器

职责：
1. 调用 GitHub REST API 获取仓库元数据
2. 获取 README 内容（Base64 解码）
3. 获取 languages 统计识别技术栈
4. 尝试读取 requirements.txt 提取 Python 依赖

风险控制：
- 只读 README + requirements + languages，不做代码遍历
- API 失败时降级返回 URL 信息

面试话术：
> "RepoAnalyzer 通过 GitHub REST API 获取仓库的 README 和语言统计。
>  我用 httpx 做 HTTP 调用，做了完整的降级策略——API 不通时返回 URL
>  基本信息，保证 Planner 总能拿到上下文。这就是 Tool 层的健壮性设计。"
"""

import os
import re
import base64
from typing import Optional, Dict, Any, List
from pydantic import BaseModel
import httpx


class RepoInfo(BaseModel):
    """仓库信息"""
    name: str
    full_name: str
    description: str = ""
    readme: str = ""
    tech_stack: List[str] = []
    topics: List[str] = []
    stars: int = 0
    language: str = ""


class RepoAnalyzer:
    """
    GitHub 仓库分析器
    
    通过 GitHub REST API 分析仓库，提取学习相关信息。
    降级策略：API 失败 → 返回 URL 中的基本信息。
    """
    
    BASE_URL = "https://api.github.com"
    TIMEOUT = 15  # 秒
    
    def __init__(self, github_token: Optional[str] = None):
        """
        初始化分析器
        
        Args:
            github_token: GitHub API Token（可选，用于提高 API 限额）
        """
        self.github_token = github_token or os.getenv("GITHUB_TOKEN")
        self.headers = {"Accept": "application/vnd.github.v3+json"}
        if self.github_token:
            self.headers["Authorization"] = f"token {self.github_token}"
    
    def analyze(self, url: str) -> RepoInfo:
        """
        分析 GitHub 仓库
        
        Args:
            url: GitHub 仓库 URL
            
        Returns:
            RepoInfo 对象（即使 API 失败也会返回基本信息）
        """
        # 提取 owner/repo
        match = re.search(r'github\.com/([^/]+)/([^/\s?#]+)', url)
        if not match:
            raise ValueError(f"Invalid GitHub URL: {url}")
        
        owner, repo = match.groups()
        repo = repo.rstrip('.git')
        
        # 获取仓库信息（含降级）
        repo_info = self._get_repo_info(owner, repo)
        
        # 获取 README（含降级）
        readme = self._get_readme(owner, repo)
        repo_info["readme"] = readme
        
        # 获取技术栈（含降级）
        tech_stack = self._get_tech_stack(owner, repo)
        repo_info["tech_stack"] = tech_stack
        
        return RepoInfo(**repo_info)
    
    def _get_repo_info(self, owner: str, repo: str) -> Dict[str, Any]:
        """获取仓库基本信息 — GET /repos/{owner}/{repo}"""
        try:
            resp = httpx.get(
                f"{self.BASE_URL}/repos/{owner}/{repo}",
                headers=self.headers,
                timeout=self.TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "name": data.get("name", repo),
                "full_name": data.get("full_name", f"{owner}/{repo}"),
                "description": data.get("description") or f"{repo} 项目",
                "stars": data.get("stargazers_count", 0),
                "language": data.get("language") or "Unknown",
                "topics": data.get("topics", []),
            }
        except Exception as e:
            print(f"[RepoAnalyzer] Failed to get repo info: {e}")
            # 降级：返回 URL 中能提取的信息
            return {
                "name": repo,
                "full_name": f"{owner}/{repo}",
                "description": f"{repo} 项目 (API 暂不可用)",
                "stars": 0,
                "language": "Unknown",
                "topics": [],
            }
    
    def _get_readme(self, owner: str, repo: str) -> str:
        """获取 README 内容 — GET /repos/{owner}/{repo}/readme"""
        try:
            resp = httpx.get(
                f"{self.BASE_URL}/repos/{owner}/{repo}/readme",
                headers=self.headers,
                timeout=self.TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            
            # GitHub API 返回 Base64 编码的 README 内容
            content_b64 = data.get("content", "")
            if content_b64:
                readme_bytes = base64.b64decode(content_b64)
                return readme_bytes.decode("utf-8", errors="replace")
            return ""
            
        except Exception as e:
            print(f"[RepoAnalyzer] Failed to get README: {e}")
            return f"# {repo}\n\n(README 获取失败，请稍后重试或检查 URL)"
    
    def _get_tech_stack(self, owner: str, repo: str) -> List[str]:
        """
        获取技术栈 — 两步策略：
        1. GET /repos/{owner}/{repo}/languages → 语言统计
        2. 尝试 GET requirements.txt → Python 依赖
        """
        tech_stack = []
        
        # Step 1: Languages API
        try:
            resp = httpx.get(
                f"{self.BASE_URL}/repos/{owner}/{repo}/languages",
                headers=self.headers,
                timeout=self.TIMEOUT,
            )
            resp.raise_for_status()
            languages = resp.json()
            # 按字节数排序，取前 5
            sorted_langs = sorted(languages.items(), key=lambda x: x[1], reverse=True)
            tech_stack = [lang for lang, _ in sorted_langs[:5]]
        except Exception as e:
            print(f"[RepoAnalyzer] Failed to get languages: {e}")
        
        # Step 2: 尝试读 requirements.txt
        try:
            resp = httpx.get(
                f"{self.BASE_URL}/repos/{owner}/{repo}/contents/requirements.txt",
                headers=self.headers,
                timeout=self.TIMEOUT,
            )
            if resp.status_code == 200:
                content_b64 = resp.json().get("content", "")
                if content_b64:
                    req_text = base64.b64decode(content_b64).decode("utf-8", errors="replace")
                    # 提取包名（去掉版本号和注释）
                    for line in req_text.strip().split("\n"):
                        line = line.strip()
                        if line and not line.startswith("#") and not line.startswith("-"):
                            pkg = re.split(r'[><=!~\[]', line)[0].strip()
                            if pkg and pkg not in tech_stack:
                                tech_stack.append(pkg)
        except Exception:
            pass  # requirements.txt 可能不存在，正常
        
        return tech_stack if tech_stack else ["Unknown"]
    
    def to_learning_context(self, repo_info: RepoInfo) -> str:
        """
        将仓库信息转换为学习上下文
        
        用于传递给 Planner Agent
        """
        parts = [
            f"# {repo_info.full_name}",
            "",
            f"**项目描述**: {repo_info.description}",
            f"**主要语言**: {repo_info.language}",
            f"**Stars**: {repo_info.stars}",
            f"**技术栈**: {', '.join(repo_info.tech_stack)}",
        ]
        
        if repo_info.topics:
            parts.append(f"**Topics**: {', '.join(repo_info.topics)}")
        
        parts.extend([
            "",
            "## README 内容",
            "",
            repo_info.readme[:3000] if len(repo_info.readme) > 3000 else repo_info.readme,
        ])
        return "\n".join(parts)
