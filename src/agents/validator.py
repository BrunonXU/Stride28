"""
Validator Agent - 验证 Agent

职责：
1. 生成 Quiz 测验题目
2. 评估答案正确性
3. 生成进度报告

设计亮点：
1. JSON 格式输出 - 让 LLM 生成结构化题目
2. 自动判分 - 支持选择题评估
3. 进度追踪 - 统计正确率和薄弱知识点

面试话术：
> "ValidatorAgent 负责学习效果评估。我用 JSON 格式让 LLM 生成选择题，
>  自动判分并追踪用户的薄弱知识点。generate_quiz() 可以基于 RAG 内容
>  生成针对性题目。"
"""

from typing import Optional, List, Dict, Any

from .base import BaseAgent
from src.core.models import Quiz, Question, QuestionType, QuizResult, ProgressReport
from src.core.file_manager import FileManager


class ValidatorAgent(BaseAgent):
    """
    验证 Agent
    
    负责评估学习效果
    """
    
    name = "ValidatorAgent"
    description = "生成测验，评估学习效果，生成进度报告"
    
    system_prompt = """你是一个专业的学习评估专家。

你的任务是：
1. 根据学习内容生成测验题目
2. 评估学习者的回答
3. 提供建设性的反馈
4. 生成学习进度报告

生成题目的原则：
- 覆盖关键知识点
- 难度适中，循序渐进
- 题目表述清晰无歧义
- 选项设计合理（干扰项有吸引力但明确错误）

评估的原则：
- 客观公正
- 既指出错误，也肯定进步
- 提供具体的改进建议"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.quiz_history: List[QuizResult] = []
    
    def run(
        self,
        action: str,
        **kwargs
    ) -> Any:
        """
        执行验证任务
        
        Args:
            action: 动作类型（generate_quiz/evaluate/report）
            **kwargs: 其他参数
            
        Returns:
            对应的输出
        """
        if action == "generate_quiz":
            return self.generate_quiz(
                topic=kwargs.get("topic", ""),
                content=kwargs.get("content", ""),
                num_questions=kwargs.get("num_questions", 5),
                difficulty=kwargs.get("difficulty", 0.5),
            )
        elif action == "evaluate":
            return self.evaluate_answers(
                quiz=kwargs.get("quiz"),
                answers=kwargs.get("answers", []),
            )
        elif action == "report":
            return self.generate_report(
                domain=kwargs.get("domain", ""),
                file_manager=kwargs.get("file_manager"),
            )
        else:
            raise ValueError(f"Unknown action: {action}")
    
    def generate_quiz(
        self,
        topic: str,
        content: str = "",
        num_questions: int = 5,
        difficulty: float = 0.5,
    ) -> Quiz:
        """
        生成测验
        """
        self._emit_event("tool_start", self.name, f"Generating quiz for topic: {topic}")
        difficulty_desc = "简单" if difficulty < 0.3 else "中等" if difficulty < 0.7 else "困难"
        
        prompt = f"""请根据以下内容生成 {num_questions} 道选择题：

**主题**: {topic}
**难度**: {difficulty_desc}

**参考内容**:
{content if content else '请根据你的知识生成题目'}

请按以下 JSON 格式输出：
```json
[
  {{
    "question": "题目内容",
    "options": ["A选项", "B选项", "C选项", "D选项"],
    "correct_answer": "A",
    "explanation": "解析内容",
    "topic": "知识点"
  }}
]
```

只输出 JSON，不要其他内容。"""
        
        self._emit_event("progress", self.name, "Requesting structured JSON quiz from LLM...")
        response = self._call_llm(prompt)
        
        # 解析 JSON（简化处理，实际应更健壮）
        self._emit_event("progress", self.name, "Parsing quiz items...")
        questions = self._parse_questions(response)
        
        self._emit_event("tool_end", self.name, f"Quiz generated successfully with {len(questions)} questions")
        return Quiz(
            domain=topic,
            topic=topic,
            questions=questions,
            difficulty=difficulty,
        )

    def evaluate_answers(
        self,
        quiz: Quiz,
        answers: List[int],
    ) -> QuizResult:
        """
        评估测验答案
        """
        self._emit_event("tool_start", self.name, "Evaluating quiz answers...")
        correct_count = 0
        wrong_topics = []
        
        # Handle both integer indices and string answers (compatibility)
        normalized_answers = []
        for ans in answers:
            if isinstance(ans, str):
                # Simple heuristic: if answer is "A"/"B" etc, convert to index? 
                # Or just keep as is if quiz expects strings. 
                # For now assuming index based on Quiz model.
                # But generic QuizResult expects list of answers.
                normalized_answers.append(ans)
            else:
                normalized_answers.append(ans)

        for i, (question, answer) in enumerate(zip(quiz.questions, answers)):
            # Normalize answer: if int, convert to letter
            user_ans = answer
            if isinstance(answer, int):
                user_ans = "ABCD"[answer] if 0 <= answer < 4 else "?"
            
            # Compare with correct_answer (string)
            if user_ans == question.correct_answer:
                correct_count += 1
            else:
                if question.topic:
                    wrong_topics.append(question.topic)
        
        total = len(quiz.questions)
        accuracy = correct_count / total if total > 0 else 0
        
        # Generte feedback
        if accuracy >= 0.8:
            feedback = "🎉 太棒了！你对这个主题掌握得很好！"
        elif accuracy >= 0.6:
            feedback = "👍 不错！继续努力，还有一些知识点需要加强。"
        else:
            feedback = "💪 需要多复习一下这部分内容，不要气馁！"

        self._emit_event("tool_end", self.name, f"Evaluation complete. Accuracy: {accuracy:.1%}")
        
        result = QuizResult(
            quiz_id=str(id(quiz)),
            answers=answers,
            correct_count=correct_count,
            total_count=total,
            accuracy=accuracy,
            wrong_topics=list(set(wrong_topics)),
            feedback=feedback,
        )
        self.quiz_history.append(result)
        return result

    def _parse_questions(self, response: str) -> List[Question]:
        """解析 LLM 返回的题目 JSON"""
        import json
        import re
        
        # 尝试提取 JSON
        json_match = re.search(r'\[[\s\S]*\]', response)
        if not json_match:
            # 返回默认题目
            return [
                Question(
                    qid="mock_q1",
                    question="这是一道示例题目（解析失败）",
                    type=QuestionType.SINGLE_CHOICE,
                    choices=["选项A", "选项B", "选项C", "选项D"],
                    answer_index=0,
                    explanation="这是解析",
                    topic="示例知识点",
                )
            ]
        
        try:
            data = json.loads(json_match.group())
            questions = []
            for i, item in enumerate(data):
                options = item.get("options", [])
                correct_answer = item.get("correct_answer", "A")
                
                # Check mapping if necessary
                
                questions.append(Question(
                    qid="mock_q1", # Dummy field if needed, or check model
                    question=item.get("question", ""),
                    type=QuestionType.SINGLE_CHOICE,
                    options=options, # Use options
                    correct_answer=correct_answer, # Use correct_answer
                    explanation=item.get("explanation", ""),
                    topic=item.get("topic", item.get("question", "")[:10]),
                ))
            return questions
        except json.JSONDecodeError:
            return [
                Question(
                    question="解析失败，这是默认题目",
                    type=QuestionType.SINGLE_CHOICE,
                    options=["A", "B", "C", "D"],
                    correct_answer="A",
                )
            ]
    
    def generate_report(
        self,
        domain: str,
        file_manager: Optional[FileManager] = None,
    ) -> ProgressReport:
        """
        生成进度报告
        
        Args:
            domain: 学习领域
            file_manager: 文件管理器（用于获取历史数据）
            
        Returns:
            ProgressReport 对象
        """
        # 统计数据
        total_sessions = len(self.quiz_history) if self.quiz_history else 0
        
        if self.quiz_history:
            avg_accuracy = sum(r.accuracy for r in self.quiz_history) / len(self.quiz_history)
            all_wrong_topics = []
            for r in self.quiz_history:
                all_wrong_topics.extend(r.wrong_topics)
        else:
            avg_accuracy = 0.0
            all_wrong_topics = []
        
        # 生成建议
        suggestions = []
        if avg_accuracy < 0.6:
            suggestions.append("建议重新学习基础内容")
        if all_wrong_topics:
            top_weak = list(set(all_wrong_topics))[:3]
            suggestions.append(f"需要加强的知识点：{', '.join(top_weak)}")
        
        return ProgressReport(
            domain=domain,
            total_sessions=total_sessions,
            quiz_attempts=total_sessions,
            average_accuracy=avg_accuracy,
            weak_topics=list(set(all_wrong_topics)),
            suggestions=suggestions,
        )
