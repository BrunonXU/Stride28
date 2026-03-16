"""
配置管理模块

集中管理所有配置项，支持环境变量和默认值

设计亮点：
1. 单例模式 - 保证全局配置一致性
2. Pydantic 模型 - 类型安全 + 默认值
3. 环境变量优先 - 配置和代码分离

面试话术：
> "我用单例模式管理配置，保证全局只有一份配置实例。
>  配置项用 Pydantic 定义，支持类型校验和默认值。
>  实际值从 .env 环境变量读取，这样改配置不用改代码。"
"""

import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel
from dotenv import load_dotenv


# 加载 .env 文件
load_dotenv()


class ProviderConfig(BaseModel):
    """Provider 配置"""
    name: str = "deepseek"
    model: str = "deepseek-chat"
    embedding_model: str = "text-embedding-v2"


class RAGConfig(BaseModel):
    """RAG 配置"""
    chunk_size: int = 1000
    chunk_overlap: int = 200
    top_k: int = 5
    collection_name: str = "knowledge_base"


class LangSmithConfig(BaseModel):
    """LangSmith 配置"""
    enabled: bool = True
    project: str = "stride28"


class Config:
    """
    全局配置类
    
    使用单例模式，确保全局配置一致
    """
    
    _instance: Optional["Config"] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """初始化配置"""
        # 基础路径：config.py → core → src → 项目根（3 层）
        self.project_root = Path(__file__).parent.parent.parent
        self.data_dir = Path(os.getenv("DATA_DIR", self.project_root / "data"))
        self.chroma_dir = Path(os.getenv("CHROMA_PERSIST_DIR", self.data_dir / "chroma"))
        
        # 用户数据目录（存储学习计划、笔记等）
        self.user_data_dir = Path.home() / ".learningAgent"
        
        # 确保目录存在
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        
        # Provider 配置
        self.provider = ProviderConfig(
            name=os.getenv("DEFAULT_PROVIDER", "tongyi"),
            model=os.getenv("DEFAULT_MODEL", "qwen-turbo"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-v2"),
        )
        
        # RAG 配置
        self.rag = RAGConfig(
            chunk_size=int(os.getenv("RAG_CHUNK_SIZE", "1000")),
            chunk_overlap=int(os.getenv("RAG_CHUNK_OVERLAP", "200")),
            top_k=int(os.getenv("RAG_TOP_K", "5")),
        )
        
        # LangSmith 配置
        self.langsmith = LangSmithConfig(
            enabled=os.getenv("LANGCHAIN_TRACING_V2", "true").lower() == "true",
            project=os.getenv("LANGCHAIN_PROJECT", "stride28"),
        )
        
        # API Keys（只检查，不存储）
        self._check_api_keys()
    
    def _check_api_keys(self):
        """检查必要的 API Keys"""
        self.has_dashscope_key = bool(os.getenv("DASHSCOPE_API_KEY"))
        self.has_langsmith_key = bool(os.getenv("LANGCHAIN_API_KEY") or os.getenv("LANGSMITH_API_KEY"))
        
        if not self.has_dashscope_key:
            print("⚠️  Warning: DASHSCOPE_API_KEY not set. LLM and Embedding won't work.")
        
        if self.langsmith.enabled and not self.has_langsmith_key:
            print("⚠️  Warning: LangSmith enabled but API key not set. Tracing won't work.")
    
    def get_domain_dir(self, domain: str) -> Path:
        """获取特定领域的数据目录"""
        domain_dir = self.user_data_dir / domain.replace(" ", "_").lower()
        domain_dir.mkdir(parents=True, exist_ok=True)
        return domain_dir
    
    @classmethod
    def get(cls) -> "Config":
        """获取配置单例"""
        return cls()
    
    def __repr__(self):
        return f"Config(provider={self.provider.name}, model={self.provider.model})"


# 便捷函数
def get_config() -> Config:
    """获取全局配置"""
    return Config.get()
