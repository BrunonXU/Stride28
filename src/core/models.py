"""
数据模型

定义项目中使用的核心数据结构

设计亮点：
1. Pydantic BaseModel - 类型校验 + 序列化
2. 方法封装 - to_markdown() 方便输出
3. 枚举类型 - 限制取值范围

面试话术：
> "我用 Pydantic 定义数据模型，好处是自动类型校验、有默认值、
>  可以一键序列化成 JSON。比如 LearningPlan 可以直接调用
>  to_markdown() 转成人类可读格式。"
"""

from typing import List, Optional, Dict, Any, Union
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


# ==================== 学习相关模型 ====================

class PlatformType(str, Enum):
    """支持的搜索平台"""
    BILIBILI = "bilibili"
    YOUTUBE = "youtube"
    GOOGLE = "google"
    GITHUB = "github"
    XIAOHONGSHU = "xiaohongshu"
    WECHAT = "wechat"


class ResourceType(str, Enum):
    """资源类型"""
    VIDEO = "video"
    ARTICLE = "article"
    REPO = "repo"
    TUTORIAL = "tutorial"
    NOTE = "note"


class SearchResult(BaseModel):
    """资源搜索结果（扩展版：支持质量评分和互动指标）"""
    title: str
    url: str
    platform: str  # bilibili, youtube, google, github, xiaohongshu, wechat
    type: str      # video, article, repo, tutorial, note
    description: str = ""
    # 新增字段（均有默认值，保持向后兼容）
    quality_score: float = 0.0
    engagement_metrics: Dict[str, Any] = Field(default_factory=dict)
    comments_preview: List[str] = Field(default_factory=list)
    # 搜索体验重设计：AI 内容整理（markdown 格式）
    content_summary: str = ""  # AI 内容整理（markdown，含整体评价 + 各回答摘要）
    image_urls: List[str] = Field(default_factory=list)  # 图片 URL 列表
    content_text: str = ""  # 正文原文（用于加入素材后的完整阅读）

    def to_dict(self) -> dict:
        """序列化为字典"""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "SearchResult":
        """从字典反序列化"""
        return cls.model_validate(data)


class LearningGoal(str, Enum):
    """学习目标级别"""
    UNDERSTAND = "understand"      # 能看懂
    USE = "use"                    # 能用它开发
    CONTRIBUTE = "contribute"      # 能贡献代码


class LearningPhase(BaseModel):
    """学习阶段"""
    name: str                      # 阶段名称
    duration: str                  # 预计时长
    topics: List[str]              # 知识点列表
    resources: List[str] = []      # 推荐资源
    completed: bool = False        # 是否完成


class LearningDay(BaseModel):
    """单天的学习内容（替代 LearningPhase 的新模型）"""
    day_number: int                    # 天数编号
    title: str                         # 当天学习主题
    topics: List[str] = []             # 当天涉及的知识点
    resources: List[Union[str, SearchResult]] = []  # 学习资源（兼容旧格式）



class LearningPlan(BaseModel):
    """
    学习计划

    由 Planner Agent 生成。
    新版本以 days (LearningDay) 为单位组织，保留 phases 字段向后兼容。
    """
    domain: str                    # 学习领域
    goal: str = ""                 # 学习目标
    goal_level: LearningGoal = LearningGoal.USE
    duration: str = ""             # 预计总时长
    total_days: int = 0            # 总天数（新增）
    days: List[LearningDay] = []   # 每日学习内容（新增，替代 phases）
    phases: List[LearningPhase] = []  # 阶段列表（保留向后兼容）
    prerequisites: List[str] = []  # 前置知识
    raw_markdown: str = ""         # LLM 生成的原始 Markdown（用于展示）
    created_at: datetime = Field(default_factory=datetime.now)

    def to_markdown(self) -> str:
        """
        转换为 Markdown 格式

        优先使用 days 结构；如果 days 为空则回退到 phases 结构。
        """
        # 优先使用新的 days 结构
        if self.days:
            lines = [
                f"# {self.domain} 学习计划",
                "",
                f"**目标**: {self.goal}" if self.goal else "",
                f"**总天数**: {self.total_days} 天" if self.total_days else "",
                "",
            ]
            lines = [l for l in lines if l is not None]

            if self.prerequisites:
                lines.append("## 前置知识")
                for prereq in self.prerequisites:
                    lines.append(f"- {prereq}")
                lines.append("")

            lines.append("## 每日学习大纲")
            lines.append("")

            for day in self.days:
                lines.append(f"### Day {day.day_number}: {day.title}")
                lines.append("")
                for topic in day.topics:
                    lines.append(f"- {topic}")
                if day.resources:
                    lines.append("")
                    lines.append("**学习资源:**")
                    for resource in day.resources:
                        if isinstance(resource, SearchResult):
                            lines.append(f"- [{resource.title}]({resource.url}) ({resource.platform})")
                        else:
                            lines.append(f"- {resource}")
                lines.append("")

            return "\n".join(lines)

        # 回退到旧的 phases 结构
        has_real_phases = len(self.phases) > 1 or (
            len(self.phases) == 1 and self.phases[0].name != "完整学习计划" and self.phases[0].name != "学习计划"
        )

        if has_real_phases:
            lines = [
                f"# {self.domain} 学习计划",
                "",
                f"**目标**: {self.goal}",
                f"**预计时长**: {self.duration}",
                "",
            ]

            if self.prerequisites:
                lines.append("## 前置知识")
                for prereq in self.prerequisites:
                    lines.append(f"- {prereq}")
                lines.append("")

            lines.append("## 学习阶段")
            lines.append("")

            for i, phase in enumerate(self.phases, 1):
                status = "✅" if phase.completed else "⬜"
                lines.append(f"### {status} 阶段 {i}: {phase.name} ({phase.duration})")
                lines.append("")
                for topic in phase.topics:
                    lines.append(f"- {topic}")
                if phase.resources:
                    lines.append("")
                    lines.append("**推荐资源:**")
                    for resource in phase.resources:
                        lines.append(f"- {resource}")
                lines.append("")

            return "\n".join(lines)

        # 如果是兜底情况，展示 LLM 原始输出
        if self.raw_markdown:
            return f"# {self.domain} 学习计划\n\n{self.raw_markdown}"

        # 最终兜底
        return f"# {self.domain} 学习计划\n\n**目标**: {self.goal}\n**预计时长**: {self.duration}"


# ==================== Quiz 相关模型 ====================

class QuestionType(str, Enum):
    """题目类型"""
    SINGLE_CHOICE = "single_choice"    # 单选题
    MULTIPLE_CHOICE = "multiple_choice" # 多选题
    TRUE_FALSE = "true_false"          # 判断题
    FILL_BLANK = "fill_blank"          # 填空题


class Question(BaseModel):
    """题目"""
    question: str                      # 题目内容
    type: QuestionType = QuestionType.SINGLE_CHOICE
    options: List[str] = []            # 选项（选择题）
    correct_answer: str                # 正确答案
    explanation: str = ""              # 解析
    topic: str = ""                    # 所属知识点
    difficulty: float = 0.5            # 难度 0-1


class Quiz(BaseModel):
    """
    测验
    
    由 Validator Agent 生成
    """
    domain: str                        # 学习领域
    topic: str                         # 测验主题
    questions: List[Question]          # 题目列表
    difficulty: float = 0.5            # 整体难度
    created_at: datetime = Field(default_factory=datetime.now)
    
    def get_question_count(self) -> int:
        return len(self.questions)


class QuizResult(BaseModel):
    """测验结果"""
    quiz_id: str
    answers: List[str]                 # 用户答案
    correct_count: int                 # 正确数量
    total_count: int                   # 总题数
    accuracy: float                    # 准确率
    wrong_topics: List[str] = []       # 错误的知识点
    feedback: str = ""                 # 反馈建议


# ==================== 进度报告相关模型 ====================

class ProgressReport(BaseModel):
    """
    进度报告
    
    由 Validator Agent 生成
    """
    domain: str                        # 学习领域
    total_sessions: int                # 总会话数
    total_time: str = ""               # 总学习时长
    quiz_attempts: int = 0             # Quiz 尝试次数
    average_accuracy: float = 0.0      # 平均准确率
    mastered_topics: List[str] = []    # 已掌握知识点
    weak_topics: List[str] = []        # 薄弱知识点
    suggestions: List[str] = []        # 改进建议
    created_at: datetime = Field(default_factory=datetime.now)
    
    def to_markdown(self) -> str:
        """转换为 Markdown 格式"""
        lines = [
            f"# {self.domain} 学习进度报告",
            "",
            f"**生成时间**: {self.created_at.strftime('%Y-%m-%d %H:%M')}",
            "",
            "## 📊 统计数据",
            "",
            f"- 总会话数: {self.total_sessions}",
            f"- Quiz 尝试次数: {self.quiz_attempts}",
            f"- 平均准确率: {self.average_accuracy:.1%}",
            "",
        ]
        
        if self.mastered_topics:
            lines.append("## ✅ 已掌握知识点")
            lines.append("")
            for topic in self.mastered_topics:
                lines.append(f"- {topic}")
            lines.append("")
        
        if self.weak_topics:
            lines.append("## ⚠️ 需加强知识点")
            lines.append("")
            for topic in self.weak_topics:
                lines.append(f"- {topic}")
            lines.append("")
        
        if self.suggestions:
            lines.append("## 💡 改进建议")
            lines.append("")
            for suggestion in self.suggestions:
                lines.append(f"- {suggestion}")
            lines.append("")
        
        return "\n".join(lines)


# ==================== 会话相关模型 ====================

class SessionMode(str, Enum):
    """会话模式"""
    FREE = "free"    # 自由对话
    QUIZ = "quiz"    # 测验模式


class SessionState(BaseModel):
    """会话状态"""
    domain: str
    mode: SessionMode = SessionMode.FREE
    current_topic: str = ""
    messages: List[Dict[str, str]] = []  # 对话历史
    quiz: Optional[Quiz] = None          # 当前 Quiz
    quiz_progress: int = 0               # Quiz 进度
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
