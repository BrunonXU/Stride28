"""
文件管理模块

负责学习计划、笔记、会话记录的持久化存储

借鉴来源：Yixiang-Wu-LearningAgent 的 FileManager
改进：增加 RAG 集成、更清晰的目录结构

设计亮点：
1. 按领域分目录 - 隔离不同学习主题的数据
2. Markdown 格式 - 人类可读，方便检查
3. get_all_content() - 合并所有内容用于 RAG 导入

面试话术：
> "FileManager 负责用户数据持久化。我按学习领域分目录，
>  用 Markdown 存计划和笔记（人类可读），用 JSON 存
>  会话状态（结构化）。有个 get_all_content() 方法
>  可以合并所有内容，用于导入 RAG 知识库。"
"""

import os
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from .config import get_config


class FileManager:
    """
    文件管理器
    
    管理用户的学习数据，包括：
    - 学习计划 (plan.md)
    - 知识笔记 (knowledge/)
    - 会话记录 (sessions/)
    - 当前会话状态 (.current_session.json)
    
    目录结构：
    ~/.learningAgent/
    └── {domain}/
        ├── plan.md              # 学习计划
        ├── knowledge/           # 知识笔记
        │   ├── summary.md       # 知识总结
        │   └── *.md             # 各章节笔记
        ├── sessions/            # 会话记录
        │   └── session_*.json   # 每次会话
        └── .current_session.json # 当前会话状态
    """
    
    def __init__(self, domain: str):
        """
        初始化文件管理器
        
        Args:
            domain: 学习领域名称
        """
        self.domain = domain
        self.config = get_config()
        
        # 设置路径
        self.domain_dir = self.config.get_domain_dir(domain)
        self.plan_path = self.domain_dir / "plan.md"
        self.knowledge_dir = self.domain_dir / "knowledge"
        self.sessions_dir = self.domain_dir / "sessions"
        self.current_session_path = self.domain_dir / ".current_session.json"
        
        # 确保目录存在
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
    
    # ==================== 学习计划 ====================
    
    def save_plan(self, plan_content: str) -> Path:
        """
        保存学习计划
        
        Args:
            plan_content: 计划内容（Markdown 格式）
            
        Returns:
            保存路径
        """
        self.plan_path.write_text(plan_content, encoding="utf-8")
        return self.plan_path
    
    def load_plan(self) -> Optional[str]:
        """
        加载学习计划
        
        Returns:
            计划内容，如果不存在返回 None
        """
        if self.plan_path.exists():
            return self.plan_path.read_text(encoding="utf-8")
        return None
    
    def has_plan(self) -> bool:
        """检查是否已有学习计划"""
        return self.plan_path.exists()
    
    # ==================== 知识笔记 ====================
    
    def save_knowledge(self, filename: str, content: str) -> Path:
        """
        保存知识笔记
        
        Args:
            filename: 文件名（不含路径）
            content: 笔记内容
            
        Returns:
            保存路径
        """
        if not filename.endswith(".md"):
            filename += ".md"
        
        path = self.knowledge_dir / filename
        path.write_text(content, encoding="utf-8")
        return path
    
    def load_knowledge(self, filename: str) -> Optional[str]:
        """加载知识笔记"""
        if not filename.endswith(".md"):
            filename += ".md"
        
        path = self.knowledge_dir / filename
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None
    
    def list_knowledge_files(self) -> List[str]:
        """列出所有知识笔记文件"""
        return [f.name for f in self.knowledge_dir.glob("*.md")]
    
    def save_knowledge_summary(self, summary: str) -> Path:
        """保存知识总结"""
        return self.save_knowledge("summary", summary)
    
    # ==================== 会话记录 ====================
    
    def save_session(self, session_data: Dict[str, Any]) -> Path:
        """
        保存会话记录
        
        Args:
            session_data: 会话数据
            
        Returns:
            保存路径
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"session_{timestamp}.json"
        path = self.sessions_dir / filename
        
        with open(path, "w", encoding="utf-8") as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)
        
        return path
    
    def load_session(self, filename: str) -> Optional[Dict[str, Any]]:
        """加载会话记录"""
        path = self.sessions_dir / filename
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None
    
    def list_sessions(self) -> List[str]:
        """列出所有会话记录"""
        return sorted([f.name for f in self.sessions_dir.glob("session_*.json")])
    
    def get_latest_session(self) -> Optional[Dict[str, Any]]:
        """获取最新的会话记录"""
        sessions = self.list_sessions()
        if sessions:
            return self.load_session(sessions[-1])
        return None
    
    # ==================== 当前会话状态 ====================
    
    def save_current_session(self, state: Dict[str, Any]):
        """
        保存当前会话状态
        
        用于在会话中断后恢复状态
        """
        with open(self.current_session_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    
    def load_current_session(self) -> Optional[Dict[str, Any]]:
        """加载当前会话状态"""
        if self.current_session_path.exists():
            with open(self.current_session_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None
    
    def clear_current_session(self):
        """清除当前会话状态"""
        if self.current_session_path.exists():
            self.current_session_path.unlink()
    
    # ==================== 工具方法 ====================
    
    def get_all_content(self) -> str:
        """
        获取所有内容（用于 RAG 导入）
        
        Returns:
            合并的所有内容
        """
        parts = []
        
        # 学习计划
        plan = self.load_plan()
        if plan:
            parts.append(f"# 学习计划\n\n{plan}")
        
        # 知识笔记
        for filename in self.list_knowledge_files():
            content = self.load_knowledge(filename)
            if content:
                parts.append(f"# {filename}\n\n{content}")
        
        return "\n\n---\n\n".join(parts)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "domain": self.domain,
            "has_plan": self.has_plan(),
            "knowledge_files": len(self.list_knowledge_files()),
            "sessions": len(self.list_sessions()),
        }
