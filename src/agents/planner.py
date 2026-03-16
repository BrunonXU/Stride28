"""
Planner Agent - 规划 Agent

职责：
1. 识别用户输入类型（领域描述/GitHub URL/PDF）
2. 调用相应的分析工具
3. 生成个性化学习计划

使用 ReAct 模式：Thought → Action → Observation → ... → Finish

设计亮点：
1. 输入类型自动识别 - URL/PDF/文本
2. 集成 RepoAnalyzer 和 PDFAnalyzer
3. JSON 结构化输出 + 正则 fallback + raw_markdown 兜底

面试话术：
> "PlannerAgent 能自动识别输入类型。如果是 GitHub URL，
>  调用 RepoAnalyzer 分析仓库结构；如果是 PDF，用 PDFAnalyzer 提取内容。
>  然后用 LLM 以 JSON 格式输出结构化计划。我做了三层防御：
>  JSON 解析 → 正则提取 → raw_markdown 兜底，保证任何情况下都有输出。"
"""

from typing import Optional, Dict, Any, List
import re
import json
import logging

from .base import BaseAgent
from src.core.models import LearningPlan, LearningPhase, LearningDay, LearningGoal, SearchResult
from src.specialists.repo_analyzer import RepoAnalyzer
from src.specialists.pdf_analyzer import PDFAnalyzer, PDFContent
from src.specialists.resource_searcher import ResourceSearcher

logger = logging.getLogger(__name__)


class PlannerAgent(BaseAgent):
    """
    规划 Agent
    
    负责分析用户输入并生成学习计划
    """
    
    name = "PlannerAgent"
    description = "分析学习资料，生成个性化学习计划"
    
    system_prompt = """你是一个专业的学习规划师。你必须严格按照 JSON 格式输出学习计划。

你的任务是：
1. 分析用户想要学习的内容
2. 评估内容的复杂度和前置知识要求
3. 制定一个以「天」为最小单位的结构化学习计划（Day 1, Day 2...），以 JSON 格式输出"""
    
    def run(
        self,
        input_data: str,
        goal: str = "能熟练使用",
        **kwargs
    ) -> LearningPlan:
        """
        生成学习计划
        
        Args:
            input_data: 用户输入（领域描述、GitHub URL 或 PDF 内容）
            goal: 学习目标
            
        Returns:
            LearningPlan 对象
        """
        self._emit_event("tool_start", self.name, f"Detecting input type for: {input_data[:50]}...")
        
        # 1. 识别输入类型
        input_type = self._detect_input_type(input_data)
        self._emit_event("progress", self.name, f"Input detected as: {input_type}")
        
        # 2. 根据类型处理
        if input_type == "github_url":
            self._emit_event("progress", self.name, "Analyzing GitHub repository...")
            domain, context = self._process_github_url(input_data)
        elif input_type == "pdf_content":
            self._emit_event("progress", self.name, "Processing PDF content...")
            domain, context = self._process_pdf_content(input_data)
        else:
            domain = input_data[:80]  # 取合理长度作为 domain
            context = input_data
            self._emit_event("progress", self.name, "Processing text description...")
        
        # 3. 生成计划（JSON 格式，按天组织）
        prompt = f"""请为以下学习内容制定学习计划，以「天」为最小单位组织。

**学习主题**: {domain}
**学习目标**: {goal}

**背景信息**:
{context[:3000]}

请严格按照以下 JSON 格式输出，不要输出任何其他内容：

```json
{{
  "domain": "学习领域名称",
  "goal": "学习目标描述",
  "total_days": 5,
  "prerequisites": ["前置知识1", "前置知识2"],
  "days": [
    {{
      "day_number": 1,
      "title": "当天学习主题",
      "topics": ["知识点1", "知识点2", "知识点3"]
    }},
    {{
      "day_number": 2,
      "title": "当天学习主题",
      "topics": ["知识点1", "知识点2"]
    }}
  ]
}}
```

要求：
- days 数量为 3-7 天，由浅入深
- 每天的 title 要简洁明确，概括当天学习重点
- 每天的 topics 要具体，必须包含背景信息中提到的真实术语、章节名和概念
- 如果背景信息中包含用户上传的资料内容，计划必须紧密围绕该资料的实际章节和知识点展开
- total_days 等于 days 数组的长度
- prerequisites 列出实际需要的前置知识
- 只输出 JSON，不要输出其他文字"""
        
        self._emit_event("progress", self.name, "Generating structured learning plan via LLM...")
        plan_text = self._call_llm(prompt)
        
        # 4. 解析为结构化对象（三层防御）
        plan = self._parse_plan(domain, goal, plan_text)
        
        # 5. 为每天搜索资源
        plan = self._search_resources_for_plan(plan)
        
        self._emit_event("tool_end", self.name, f"Plan generated for {plan.domain}")
        return plan
    
    def _search_resources_for_plan(self, plan: LearningPlan) -> LearningPlan:
        """
        为学习计划中每天的主题搜索资源
        
        降级逻辑：搜索失败时标注"暂无推荐资源"，不阻塞计划生成
        """
        if not plan.days:
            return plan
        
        try:
            resource_searcher = ResourceSearcher()
        except Exception as e:
            logger.warning(f"[PlannerAgent] ResourceSearcher init failed: {e}, skipping resource search")
            for day in plan.days:
                if not day.resources:
                    day.resources.append("暂无推荐资源")
            return plan
        
        for day in plan.days:
            try:
                self._emit_event("progress", self.name, f"Searching resources for Day {day.day_number}: {day.title}")
                results = resource_searcher.search(f"{plan.domain} {day.title}")
                if results:
                    day.resources.extend(results)
                else:
                    day.resources.append("暂无推荐资源")
            except Exception as e:
                logger.warning(f"[PlannerAgent] Resource search failed for Day {day.day_number}: {e}")
                day.resources.append("暂无推荐资源")
        
        return plan
    
    def _process_github_url(self, url: str) -> tuple:
        """
        处理 GitHub URL
        
        面试话术：
        > "遇到 GitHub URL，我先用 RepoAnalyzer 获取仓库信息，
        >  包括 README、项目结构等，作为生成学习计划的上下文。"
        """
        try:
            analyzer = RepoAnalyzer()
            repo_info = analyzer.analyze(url)
            
            domain = repo_info.get("name", self._extract_domain_from_url(url))
            
            # 构建上下文
            context_parts = [
                f"项目名称: {repo_info.get('name', 'Unknown')}",
                f"描述: {repo_info.get('description', '无描述')}",
                f"主要语言: {repo_info.get('language', '未知')}",
            ]
            
            if repo_info.get("readme"):
                context_parts.append(f"\nREADME 内容:\n{repo_info['readme'][:2000]}")
            
            context = "\n".join(context_parts)
            
        except Exception as e:
            # 降级处理
            domain = self._extract_domain_from_url(url)
            context = f"GitHub 项目: {url}\n(无法获取详细信息: {str(e)})"
        
        return domain, context
    
    def _process_pdf_content(self, content: str) -> tuple:
        """
        处理 PDF 内容
        
        注意：这里接收的是已经提取的文本内容
        如果是 bytes，应该先用 PDFAnalyzer.analyze_from_bytes()
        """
        # 尝试从内容中提取标题
        lines = content.strip().split("\n")
        title = lines[0][:50] if lines else "PDF 文档"
        
        # 截取内容作为上下文
        context = content[:3000]
        
        return title, context
    
    def _detect_input_type(self, input_data: str) -> str:
        """检测输入类型"""
        if re.match(r'https?://github\.com/', input_data):
            return "github_url"
        elif len(input_data) > 1000:
            return "pdf_content"
        else:
            return "domain_description"
    
    def _extract_domain_from_url(self, url: str) -> str:
        """从 GitHub URL 提取项目名"""
        match = re.search(r'github\.com/[\w-]+/([\w-]+)', url)
        if match:
            return match.group(1)
        return "Unknown Project"
    
    def _parse_plan(self, domain: str, goal: str, plan_text: str) -> LearningPlan:
        """
        解析 LLM 输出为结构化 LearningPlan
        
        三层防御策略：
        1. JSON 解析 — LLM 按要求输出了标准 JSON
        2. 正则提取 — LLM 输出了带杂文的 JSON（如 "好的，以下是计划：{...}"）
        3. raw_markdown 兜底 — 完全解析失败，用 LLM 原始输出作为展示内容
        
        新版本优先解析 days 结构，回退到 phases 结构以保持向后兼容。
        """
        parsed_data = None
        
        # ===== 第一层：直接 JSON 解析 =====
        try:
            clean_text = plan_text.strip()
            if clean_text.startswith("```"):
                clean_text = re.sub(r'^```(?:json)?\s*', '', clean_text)
                clean_text = re.sub(r'\s*```$', '', clean_text)
            parsed_data = json.loads(clean_text)
        except (json.JSONDecodeError, ValueError):
            pass
        
        # ===== 第二层：正则提取 JSON 块 =====
        if parsed_data is None:
            json_match = re.search(r'\{[\s\S]*\}', plan_text)
            if json_match:
                try:
                    raw_json = json_match.group()
                    raw_json = re.sub(r',\s*([}\]])', r'\1', raw_json)
                    parsed_data = json.loads(raw_json)
                except (json.JSONDecodeError, ValueError):
                    pass
        
        # ===== 第三层：兜底 — 用 raw_markdown 展示 =====
        if parsed_data is None:
            self._emit_event("progress", self.name, "JSON parse failed, using raw markdown fallback")
            return LearningPlan(
                domain=domain,
                goal=goal,
                goal_level=LearningGoal.USE,
                duration="待定",
                total_days=1,
                days=[
                    LearningDay(
                        day_number=1,
                        title="完整学习计划",
                        topics=["详见 LLM 生成的完整计划"],
                    ),
                ],
                prerequisites=[],
                raw_markdown=plan_text,
            )
        
        # ===== 从 parsed_data 构建 LearningPlan =====
        try:
            # 优先解析 days 结构（新格式）
            if "days" in parsed_data and parsed_data["days"]:
                days = []
                for d in parsed_data["days"]:
                    days.append(LearningDay(
                        day_number=d.get("day_number", len(days) + 1),
                        title=d.get("title", f"Day {len(days) + 1}"),
                        topics=d.get("topics", []),
                        resources=d.get("resources", []),
                    ))
                
                if not days:
                    days = [LearningDay(day_number=1, title="学习计划", topics=["详见完整计划"])]
                
                plan = LearningPlan(
                    domain=parsed_data.get("domain", domain),
                    goal=parsed_data.get("goal", goal),
                    goal_level=LearningGoal.USE,
                    duration=parsed_data.get("duration", ""),
                    total_days=parsed_data.get("total_days", len(days)),
                    days=days,
                    prerequisites=parsed_data.get("prerequisites", []),
                    raw_markdown=plan_text,
                )
                
                self._emit_event("progress", self.name, f"Successfully parsed plan: {len(days)} days")
                return plan
            
            # 回退到 phases 结构（旧格式兼容）
            phases = []
            for p in parsed_data.get("phases", []):
                phases.append(LearningPhase(
                    name=p.get("name", "未命名阶段"),
                    duration=p.get("duration", "待定"),
                    topics=p.get("topics", []),
                    resources=p.get("resources", []),
                ))
            
            if not phases:
                phases = [LearningPhase(name="学习计划", duration="待定", topics=["详见完整计划"])]
            
            plan = LearningPlan(
                domain=parsed_data.get("domain", domain),
                goal=parsed_data.get("goal", goal),
                goal_level=LearningGoal.USE,
                duration=parsed_data.get("duration", "2 周"),
                phases=phases,
                prerequisites=parsed_data.get("prerequisites", []),
                raw_markdown=plan_text,
            )
            
            self._emit_event("progress", self.name, f"Successfully parsed plan: {len(phases)} phases (legacy)")
            return plan
            
        except Exception as e:
            self._emit_event("progress", self.name, f"Plan object build failed: {e}, using fallback")
            return LearningPlan(
                domain=domain,
                goal=goal,
                goal_level=LearningGoal.USE,
                duration="待定",
                total_days=1,
                days=[LearningDay(day_number=1, title="学习计划", topics=["详见完整计划"])],
                raw_markdown=plan_text,
            )
