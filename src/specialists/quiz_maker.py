"""
Quiz 生成器

职责：
1. 根据学习内容生成测验题目
2. 控制题目难度
3. 保证知识点覆盖

这是一个工具类，被 ValidatorAgent 调用

面试话术：
> "QuizMaker 负责生成测验题，被 ValidatorAgent 调用。
>  有个 adjust_difficulty() 方法根据用户表现动态调整难度，
>  表现好就加难度，表现差就降难度。"

TODO:
- 实现更智能的题目生成
- 支持更多题型
"""

from typing import List, Optional
from src.core.models import Quiz, Question, QuestionType


class QuizMaker:
    """
    Quiz 生成器
    
    专门负责生成高质量的测验题目
    """
    
    def __init__(self):
        """初始化生成器"""
        pass
    
    def create_quiz(
        self,
        topic: str,
        content: str,
        num_questions: int = 5,
        difficulty: float = 0.5,
        question_types: Optional[List[QuestionType]] = None,
    ) -> Quiz:
        """
        创建测验
        
        Args:
            topic: 测验主题
            content: 参考内容
            num_questions: 题目数量
            difficulty: 难度 0-1
            question_types: 题目类型列表
            
        Returns:
            Quiz 对象
        """
        # TODO: 使用 LLM 生成题目
        # 目前返回模板题目
        
        if question_types is None:
            question_types = [QuestionType.SINGLE_CHOICE]
        
        questions = []
        for i in range(num_questions):
            questions.append(
                Question(
                    question=f"关于 {topic} 的第 {i+1} 题",
                    type=question_types[0],
                    options=["选项 A", "选项 B", "选项 C", "选项 D"],
                    correct_answer="A",
                    explanation=f"这是第 {i+1} 题的解析",
                    topic=topic,
                    difficulty=difficulty,
                )
            )
        
        return Quiz(
            domain=topic,
            topic=topic,
            questions=questions,
            difficulty=difficulty,
        )
    
    def adjust_difficulty(
        self,
        quiz: Quiz,
        performance: float,
    ) -> Quiz:
        """
        根据表现调整难度
        
        Args:
            quiz: 原测验
            performance: 表现（正确率）
            
        Returns:
            难度调整后的新测验
        """
        # 表现好 → 提高难度
        # 表现差 → 降低难度
        if performance > 0.8:
            new_difficulty = min(1.0, quiz.difficulty + 0.2)
        elif performance < 0.5:
            new_difficulty = max(0.0, quiz.difficulty - 0.2)
        else:
            new_difficulty = quiz.difficulty
        
        return self.create_quiz(
            topic=quiz.topic,
            content="",
            num_questions=len(quiz.questions),
            difficulty=new_difficulty,
        )
