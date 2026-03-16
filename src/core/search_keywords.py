"""统一搜索意图关键词模块。

集中维护搜索意图检测关键词，供 Orchestrator 和 TutorAgent 共同引用，
避免两处关键词列表不一致导致搜索漏触发或误触发。
"""

SEARCH_KEYWORDS: list[str] = [
    # 显式搜索请求
    "搜索资源", "找资源", "推荐资源", "search resource",
    "搜索更多资源", "找学习资源", "推荐学习资源",
    "有什么资源", "资源推荐", "有哪些资源", "学习资源",
    "find resource", "recommend", "搜索更多",
    # 隐式搜索意图（用户想找东西学习）
    "搜一下", "搜索一下", "帮我搜", "帮我找",
    "有没有教程", "哪里可以学", "去哪里学",
    "找教程", "找视频", "找文章", "找笔记",
    "推荐教程", "推荐视频", "推荐文章",
]


def is_search_intent(user_input: str) -> bool:
    """检测用户输入是否包含搜索意图关键词。

    对用户输入做 case-insensitive 匹配，只要包含任一关键词即返回 True。
    """
    input_lower = user_input.lower()
    return any(kw in input_lower for kw in SEARCH_KEYWORDS)
