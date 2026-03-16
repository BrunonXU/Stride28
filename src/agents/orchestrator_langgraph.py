"""
LangGraph 版 Orchestrator - 状态机工作流编排

这是与手写 Orchestrator 等价的 LangGraph 实现，用于面试对比讲解。

核心概念映射：
  手写版                        LangGraph 版
  ─────────────────────────    ─────────────────────────
  OrchestratorState (Enum)  →  LearningState (TypedDict)
  _detect_intent() if-elif  →  add_conditional_edges()
  _run_coordinated()        →  graph.invoke()
  self.state = PLANNING     →  State["status"] = "planning"

面试话术：
> "我实现了两个版本的 Orchestrator 做对比。手写版用 if-elif 做路由，
>  LangGraph 版用 StateGraph + conditional_edges 做路由。
>  本质一样——都是有限状态机。但 LangGraph 的优势是：声明式定义、
>  内置 Checkpointer 持久化、可自动生成流程图。"

使用方式：
    from src.agents.orchestrator_langgraph import create_learning_graph
    graph = create_learning_graph(planner, tutor, validator, rag_engine)
    result = graph.invoke({"user_input": "帮我分析这篇论文", "domain": "AI"})
"""

from typing import TypedDict, Optional, List, Dict, Any, Literal
from langgraph.graph import StateGraph, END

from src.agents.planner import PlannerAgent
from src.agents.tutor import TutorAgent
from src.agents.validator import ValidatorAgent
from src.core.models import SessionMode
from src.rag import RAGEngine


# ============================================================================
# 1. State 定义 — 在图中流转的数据
# ============================================================================

class LearningState(TypedDict):
    """
    学习流程状态
    
    LangGraph 的核心：State 在 Node 之间流转，
    每个 Node 只返回要更新的字段，LangGraph 自动 merge。
    
    面试话术：
    > "State 是不可变的——每个 Node 只能返回要更新的字段，
    >  不能直接修改全局状态。这比手写版的 self.state = xxx 更安全。"
    """
    # 用户输入
    user_input: str
    # 对话历史
    history: List[Dict[str, str]]
    # 学习领域
    domain: str
    # 当前流程阶段
    status: str  # idle | planning | learning | validating | completed
    # 意图分类结果
    intent: str  # create_plan | ask_question | start_quiz | get_report
    # Agent 输出
    response: str
    # 学习计划（Markdown）
    plan: str
    # Quiz 得分
    quiz_score: float
    # RAG 上下文
    rag_context: str


# ============================================================================
# 2. Node 定义 — 每个 Node 是一个处理函数
# ============================================================================

def intent_router_node(state: LearningState) -> dict:
    """
    意图识别节点 — 等价于手写版的 _detect_intent()
    
    根据用户输入的关键词判断意图，返回 intent 字段。
    """
    user_input = state.get("user_input", "").lower()
    
    if any(kw in user_input for kw in ["测验", "quiz", "测试", "考试", "考考"]):
        intent = "start_quiz"
    elif any(kw in user_input for kw in ["报告", "进度", "report", "progress"]):
        intent = "get_report"
    elif any(kw in user_input for kw in ["计划", "plan", "规划"]):
        intent = "create_plan"
    else:
        intent = "ask_question"
    
    return {"intent": intent}


def _create_planner_node(planner: PlannerAgent, rag_engine: Optional[RAGEngine] = None):
    """工厂函数：创建 Planner Node（闭包捕获 Agent 实例）"""
    
    def planner_node(state: LearningState) -> dict:
        """
        规划节点 — 等价于手写版的 _handle_create_plan()
        
        1. 从 RAG 获取上下文
        2. 调用 PlannerAgent 生成计划
        3. 返回更新的 State
        """
        user_input = state.get("user_input", "")
        domain = state.get("domain", "")
        
        # RAG 增强
        rag_context = ""
        if rag_engine:
            if len(user_input) < 20:
                rag_context = rag_engine.build_context("summary overview", k=5)
            else:
                rag_context = rag_engine.build_context(user_input, k=5)
        
        # 构造 Planner 输入
        planner_input = user_input
        if rag_context:
            planner_input = f"用户目标: {user_input}\n\n参考资料内容:\n{rag_context}"
        
        # 调用 Planner
        plan = planner.run(planner_input)
        plan_md = plan.to_markdown()
        
        return {
            "plan": plan_md,
            "response": f"✅ 学习计划已生成！\n\n{plan_md}",
            "status": "learning",
            "rag_context": rag_context,
        }
    
    return planner_node


def _create_tutor_node(tutor: TutorAgent, rag_engine: Optional[RAGEngine] = None):
    """工厂函数：创建 Tutor Node"""
    
    def tutor_node(state: LearningState) -> dict:
        """
        教学节点 — 等价于手写版的 _handle_ask_question()
        """
        user_input = state.get("user_input", "")
        history = state.get("history", [])
        
        if rag_engine:
            tutor.set_rag_engine(rag_engine)
        
        response = tutor.run(user_input, mode=SessionMode.FREE, history=history)
        
        return {
            "response": response,
            "status": "learning",
        }
    
    return tutor_node


def _create_validator_node(validator: ValidatorAgent, tutor: TutorAgent,
                           rag_engine: Optional[RAGEngine] = None, domain: str = ""):
    """工厂函数：创建 Validator Node"""
    
    def validator_node(state: LearningState) -> dict:
        """
        验证节点 — 等价于手写版的 _handle_start_quiz()
        """
        current_domain = state.get("domain", domain) or "学习测验"
        
        # 获取 RAG 内容作为参考
        content = ""
        if rag_engine:
            content = rag_engine.build_context(current_domain, k=3)
        
        quiz = validator.generate_quiz(
            topic=current_domain,
            content=content,
            num_questions=5,
        )
        
        response = tutor.start_quiz(quiz)
        
        return {
            "response": response,
            "status": "validating",
        }
    
    return validator_node


def _create_report_node(validator: ValidatorAgent, domain: str = ""):
    """工厂函数：创建 Report Node"""
    
    def report_node(state: LearningState) -> dict:
        """
        报告节点 — 等价于手写版的 _handle_get_report()
        """
        current_domain = state.get("domain", domain) or "Unknown"
        report = validator.generate_report(domain=current_domain)
        
        return {
            "response": report.to_markdown(),
            "status": "completed",
        }
    
    return report_node


# ============================================================================
# 3. 条件边 — 根据 intent 路由到不同 Node
# ============================================================================

def route_by_intent(state: LearningState) -> str:
    """
    条件路由函数 — 等价于手写版的 if-elif 分支
    
    面试话术：
    > "手写版里是 if intent == 'create_plan': return self._handle_create_plan()
    >  LangGraph 版里是 add_conditional_edges('router', route_by_intent, {...})
    >  本质一样，但 LangGraph 版更声明式。"
    """
    intent = state.get("intent", "ask_question")
    
    if intent == "create_plan":
        return "planner"
    elif intent == "start_quiz":
        return "validator"
    elif intent == "get_report":
        return "reporter"
    else:
        return "tutor"


# ============================================================================
# 4. Graph 构建 — 组装完整的状态图
# ============================================================================

def create_learning_graph(
    planner: PlannerAgent,
    tutor: TutorAgent,
    validator: ValidatorAgent,
    rag_engine: Optional[RAGEngine] = None,
    domain: str = "",
) -> Any:
    """
    创建 LangGraph 版学习工作流
    
    等价于手写版 Orchestrator 的 Standalone 模式。
    
    状态流转图：
    
        user_input
            │
            ▼
      ┌─────────────┐
      │ intent_router│
      └──────┬──────┘
             │
        ┌────┼────┬────────┐
        ▼    ▼    ▼        ▼
    planner tutor validator reporter
        │    │    │        │
        └────┴────┴────────┘
             │
             ▼
            END
    
    Args:
        planner: PlannerAgent 实例
        tutor: TutorAgent 实例
        validator: ValidatorAgent 实例
        rag_engine: RAG 引擎（可选）
        domain: 学习领域
        
    Returns:
        编译后的 LangGraph Runnable
    """
    
    # 创建 StateGraph
    graph = StateGraph(LearningState)
    
    # 添加节点
    graph.add_node("intent_router", intent_router_node)
    graph.add_node("planner", _create_planner_node(planner, rag_engine))
    graph.add_node("tutor", _create_tutor_node(tutor, rag_engine))
    graph.add_node("validator", _create_validator_node(validator, tutor, rag_engine, domain))
    graph.add_node("reporter", _create_report_node(validator, domain))
    
    # 设置入口
    graph.set_entry_point("intent_router")
    
    # 添加条件边：从 router 根据 intent 路由到不同 Node
    graph.add_conditional_edges(
        "intent_router",
        route_by_intent,
        {
            "planner": "planner",
            "tutor": "tutor",
            "validator": "validator",
            "reporter": "reporter",
        }
    )
    
    # 所有功能节点执行完后 → 结束
    graph.add_edge("planner", END)
    graph.add_edge("tutor", END)
    graph.add_edge("validator", END)
    graph.add_edge("reporter", END)
    
    # 编译
    compiled = graph.compile()
    
    return compiled


# ============================================================================
# 5. 便捷运行函数
# ============================================================================

def run_learning_graph(
    graph,
    user_input: str,
    domain: str = "",
    history: Optional[List[Dict[str, str]]] = None,
) -> str:
    """
    运行 LangGraph 版学习工作流
    
    Args:
        graph: compile() 后的 graph
        user_input: 用户输入
        domain: 学习领域
        history: 对话历史
        
    Returns:
        Agent 响应文本
        
    使用示例：
        graph = create_learning_graph(planner, tutor, validator)
        response = run_learning_graph(graph, "什么是 Transformer?", domain="AI")
    """
    initial_state = {
        "user_input": user_input,
        "history": history or [],
        "domain": domain,
        "status": "idle",
        "intent": "",
        "response": "",
        "plan": "",
        "quiz_score": 0.0,
        "rag_context": "",
    }
    
    result = graph.invoke(initial_state)
    
    return result.get("response", "未生成响应")
