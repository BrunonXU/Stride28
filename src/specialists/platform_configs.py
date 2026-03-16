"""
平台搜索配置

每个平台的搜索逻辑通过 PlatformConfig 数据类配置（URL 模板、CSS 选择器、资源类型映射），
新增平台只需添加配置，无需修改核心逻辑。
"""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class DetailSelectors:
    """详情页选择器"""
    content_selector: str = ""
    likes_selector: str = ""
    favorites_selector: str = ""
    comments_count_selector: str = ""
    comment_item_selector: str = ""
    comment_likes_selector: str = ""
    extra_metrics: Dict[str, str] = field(default_factory=dict)
    initial_state_path: str = ""


@dataclass
class PlatformConfig:
    """平台搜索配置"""
    name: str
    search_url_template: str
    result_selector: str
    title_selector: str
    link_selector: str
    description_selector: str
    resource_type: str
    detail_selectors: DetailSelectors
    requires_login: bool = False
    cookie_file: str = ""
    use_js_extraction: bool = False
    js_extract_fn: str = ""
    use_hybrid_mode: bool = False
    api_intercept_patterns: List[str] = field(default_factory=list)
    detail_extract_method: str = "css"
    platform_category: str = "article"  # "note" | "article" | "video"
    scoring_weights: Dict[str, float] = field(default_factory=dict)
    use_api_search: bool = False  # True = use API instead of browser
    default_search_count: int = 10
    focused_search_count: int = 60



# ============================================================
# 平台配置实例
# ============================================================

_xiaohongshu_config = PlatformConfig(
    name="xiaohongshu",
    search_url_template="https://www.xiaohongshu.com/search_result?keyword={query}&source=web_search_result_note",
    result_selector="section.note-item",
    title_selector=".title span",
    link_selector="a",
    description_selector=".desc",
    resource_type="note",
    requires_login=False,  # XhsSearcher 自行管理登录
    cookie_file="scripts/.xhs_cookies.json",
    use_js_extraction=True,
    js_extract_fn="",
    use_hybrid_mode=True,
    api_intercept_patterns=[
        "/api/sns/web/v1/search/notes",
        "/api/sns/web/v2/comment/page",
        "/api/sns/web/v1/feed",
    ],
    detail_extract_method="js_state",
    detail_selectors=DetailSelectors(
        content_selector="#detail-desc,.note-text,.note-content,div.desc,article",
        likes_selector=".like-wrapper .count",
        favorites_selector=".collect-wrapper .count",
        comments_count_selector=".chat-wrapper .count",
        comment_item_selector=".comment-item",
        comment_likes_selector=".like-count",
        initial_state_path="note.noteDetailMap",
    ),
    platform_category="note",
    scoring_weights={"comments": 5, "collected": 2, "likes": 1},
)

_stackoverflow_config = PlatformConfig(
    name="stackoverflow",
    search_url_template="https://stackoverflow.com/search?q={query}",
    result_selector=".s-post-summary",
    title_selector=".s-post-summary--content-title a",
    link_selector=".s-post-summary--content-title a",
    description_selector=".s-post-summary--content-excerpt",
    resource_type="article",
    detail_selectors=DetailSelectors(
        content_selector=".s-prose",
        likes_selector=".js-vote-count",
        comments_count_selector=".js-show-link",
        comment_item_selector=".comment-body",
    ),
)

_youtube_config = PlatformConfig(
    name="youtube",
    search_url_template="https://www.youtube.com/results?search_query={query}",
    result_selector="ytd-video-renderer",
    title_selector="#video-title",
    link_selector="#video-title",
    description_selector="#description-text",
    resource_type="video",
    detail_selectors=DetailSelectors(
        content_selector="#description-inner",
        likes_selector="#segmented-like-button button",
        comments_count_selector="#count .count-text",
        comment_item_selector="ytd-comment-thread-renderer",
        extra_metrics={"views": "#info span.view-count"},
    ),
    platform_category="video",
    scoring_weights={"views": 1, "likes": 2, "comments": 3},
)

_github_config = PlatformConfig(
    name="github",
    search_url_template="https://github.com/search?q={query}&type=repositories",
    result_selector=".search-title",
    title_selector="a",
    link_selector="a",
    description_selector=".search-match",
    resource_type="repo",
    detail_selectors=DetailSelectors(
        content_selector="article.markdown-body",
        extra_metrics={
            "stars": "#repo-stars-counter-star",
            "forks": "#repo-network-counter",
        },
    ),
    use_api_search=True,  # 使用 GithubSearcher API 模式
    platform_category="repo",
    scoring_weights={},  # GitHub 不用加权公式，初筛按 stars 排序，精排交给 LLM
    default_search_count=10,
    focused_search_count=30,
)

_google_config = PlatformConfig(
    name="google",
    search_url_template="https://www.google.com/search?q={query}",
    result_selector="div.g",
    title_selector="h3",
    link_selector="a",
    description_selector=".VwiC3b",
    resource_type="article",
    detail_selectors=DetailSelectors(
        content_selector="article, main, .post-content, .entry-content",
    ),
)

_wechat_config = PlatformConfig(
    name="wechat",
    search_url_template="https://weixin.sogou.com/weixin?type=2&query={query}",
    result_selector=".news-list li",
    title_selector="h3 a",
    link_selector="h3 a",
    description_selector=".txt-info",
    resource_type="article",
    detail_selectors=DetailSelectors(
        content_selector="#js_content",
        likes_selector="#js_like_num",
    ),
)

_bilibili_config = PlatformConfig(
    name="bilibili",
    search_url_template="https://search.bilibili.com/all?keyword={query}",
    result_selector="",
    title_selector="",
    link_selector="",
    description_selector="",
    resource_type="video",
    detail_selectors=DetailSelectors(),
    use_api_search=True,
    platform_category="video",
    scoring_weights={"views": 1, "danmaku": 3, "collected": 2, "likes": 1},
    default_search_count=10,
    focused_search_count=60,
)

_zhihu_config = PlatformConfig(
    name="zhihu",
    search_url_template="https://www.zhihu.com/search?type=content&q={query}",
    result_selector="",
    title_selector="",
    link_selector="",
    description_selector="",
    resource_type="article",
    detail_selectors=DetailSelectors(),
    requires_login=True,  # 知乎搜索 API 需要登录态
    use_api_search=True,
    platform_category="article",
    scoring_weights={"likes": 2, "comments": 3},
    default_search_count=10,
    focused_search_count=40,
)


PLATFORM_CONFIGS: Dict[str, PlatformConfig] = {
    "xiaohongshu": _xiaohongshu_config,
    "stackoverflow": _stackoverflow_config,
    "youtube": _youtube_config,
    "github": _github_config,
    "google": _google_config,
    "wechat": _wechat_config,
    "bilibili": _bilibili_config,
    "zhihu": _zhihu_config,
}
