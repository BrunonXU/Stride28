"""
browser_models — 搜索模块内部数据模型

定义搜索流水线各阶段的数据结构，仅在 specialists 模块内部流转。
外部调用者通过 src.core.models.SearchResult 获取最终结果。

RawSearchResult  — 平台搜索器返回的原始结果（标题/URL/互动数据/评论）
ResourceDetail   — 详情页提取的结构化数据（正文/点赞/收藏/图片）
ScoredResult     — 经 LLM 评估后的带分结果（评分/摘要/推荐理由）
"""

from typing import Dict, Any, List
from pydantic import BaseModel, Field

# source_tier 有效值（四层架构）
# "broad_web" / "community" / "developer" / "academic" / ""（未分类）


class RawSearchResult(BaseModel):
    """浏览器采集的原始搜索结果"""
    title: str
    url: str
    platform: str
    resource_type: str
    description: str = ""
    engagement_metrics: Dict[str, Any] = Field(default_factory=dict)
    comments: List[str] = Field(default_factory=list)
    content_snippet: str = ""
    top_comments: List[Dict[str, Any]] = Field(default_factory=list)  # 高赞评论 [{text, likes, author}]
    image_urls: List[str] = Field(default_factory=list)  # 笔记图片 URL 列表
    deduplicated_comment_count: int = 0  # 去重后的评论数量，用于替代 API 返回的原始 comments_count 参与互动分计算

    # 四层架构新增字段（全部可选，默认空值，不影响现有平台）
    source_tier: str = ""              # 所属层级：broad_web / community / developer / academic
    author: str = ""                   # 作者（arXiv 第一作者 / Tavily 无）
    publish_time: str = ""             # 发表时间（ISO 8601）
    fetched_at: str = ""               # 抓取时间（ISO 8601 带 UTC 时区）
    extraction_mode: str = ""          # 提取方式：arxiv_api / tavily_search / tavily_extract
    source_metadata: Dict[str, Any] = Field(default_factory=dict)  # 平台特有元数据，独立于 engagement_metrics


class ResourceDetail(BaseModel):
    """详情页提取的数据"""
    content_snippet: str = ""
    likes: int = 0
    favorites: int = 0
    comments_count: int = 0
    comments: List[str] = Field(default_factory=list)
    top_comments: List[Dict[str, Any]] = Field(default_factory=list)  # 高赞评论 [{text, likes, author}]
    extra_metrics: Dict[str, Any] = Field(default_factory=dict)
    image_urls: List[str] = Field(default_factory=list)  # 笔记图片 URL 列表
    image_descriptions: List[str] = Field(default_factory=list)  # [TODO] 多模态 LLM 图片内容描述


class ScoredResult(BaseModel):
    """带评分的搜索结果"""
    raw: RawSearchResult
    quality_score: float = 0.0
    # AI 内容整理（markdown 格式，含整体评价 + 各回答摘要）
    content_summary: str = ""
    extracted_content: str = ""       # 提取的正文内容（用于缓存）
    # P0 新增：pipeline 处理追踪
    trace: Dict[str, Any] = Field(default_factory=dict)

