"""
搜索模块 (src/specialists/)

多平台资源搜索系统，支持 6 个平台的并发搜索、两阶段质量漏斗和流式进度推送。

架构分层：
─────────────────────────────────────────────────────────
  入口层
    resource_searcher.py    同步搜索包装（聊天内搜索用）
    search_orchestrator.py  异步搜索调度器（SSE 流式搜索用）

  调度层
    slot_allocator.py       平台配额分配（小红书 40% + 其余均分）
    pipeline_executor.py    详情提取 + LLM 评估流水线
    search_cache.py         搜索结果内存缓存（TTL 1h）

  评分层
    engagement_ranker.py    互动数据初筛（纯数值，不调 LLM）
    quality_assessor.py     LLM 精排评估（评分+摘要+推荐理由）
    quality_scorer.py       LLM 评分（同步路径用，含启发式降级）

  浏览器层
    browser_agent.py        Playwright 浏览器代理（反检测+API 拦截）
    resource_collector.py   页面/JSON 数据提取工具

  平台搜索器
    xhs_searcher.py         小红书（签名算法 + httpx API）
    bilibili_searcher.py    B站（httpx API 直连）
    zhihu_searcher.py       知乎（Playwright API 拦截）
    github_searcher.py      GitHub（REST API + README 抓取）
    arxiv_searcher.py       arXiv（arxiv Python 包，学术论文）

  共享
    browser_models.py       内部数据模型（RawSearchResult / ScoredResult）
    platform_configs.py     平台配置（URL 模板 / CSS 选择器 / 评分权重）
─────────────────────────────────────────────────────────

数据流：
  用户查询 → SlotAllocator 分配配额 → 各平台 Searcher 并发搜索
  → EngagementRanker 初筛 → PipelineExecutor(提取+评估)
  → SlotAllocator.redistribute 按比例选 top_k → 返回结果
"""

from .resource_searcher import ResourceSearcher
from .arxiv_searcher import ArxivSearcher
from .tavily_searcher import TavilySearcher

__all__ = [
    "ResourceSearcher",
    "ArxivSearcher",
    "TavilySearcher",
]
