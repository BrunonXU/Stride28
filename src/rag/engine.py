"""
RAG Engine - 检索增强生成引擎

核心功能：
1. 文档切分（RecursiveCharacterTextSplitter）
2. 向量化存储（ChromaDB + Embedding）
3. 相似度检索（Top-K）
4. 上下文组装

技术选型理由：
- ChromaDB：轻量级、支持本地持久化、LangChain 原生支持
- RecursiveCharacterTextSplitter：智能切分，保持语义完整性
- chunk_size=1000, overlap=200：经验值，平衡上下文和召回

面试话术：
> "RAG 解决了 LLM 知识时效性和个性化的问题。用户上传的资料会被
>  切分、向量化、存入 ChromaDB。提问时先检索相关内容，再让 LLM
>  基于这些内容回答，既利用了 LLM 的推理能力，又保证了准确性。"
"""

import logging
import os
from typing import List, Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

import dashscope
from pydantic import BaseModel
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma




class Document(BaseModel):
    """文档模型"""
    content: str
    metadata: Dict[str, Any] = {}


class RetrievalResult(BaseModel):
    """检索结果模型"""
    content: str
    metadata: Dict[str, Any]
    score: float  # 相似度分数


class RAGEngine:
    """
    RAG 引擎
    
    负责文档的存储和检索
    """
    
    def __init__(
        self,
        collection_name: str = "knowledge_base",
        persist_directory: Optional[str] = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ):
        """
        初始化 RAG 引擎
        
        Args:
            collection_name: ChromaDB collection 名称
            persist_directory: 持久化目录，默认从环境变量读取
            chunk_size: 切分块大小
            chunk_overlap: 切分重叠大小
        """
        self.collection_name = collection_name
        self.persist_directory = persist_directory or os.getenv(
            "CHROMA_PERSIST_DIR", 
            "./data/chroma"
        )
        
        # 确保目录存在
        Path(self.persist_directory).mkdir(parents=True, exist_ok=True)
        
        # 初始化文本切分器
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""],
        )
        
        # 初始化 ChromaDB（使用 LangChain 包装）
        self._vectorstore = Chroma(
            collection_name=collection_name,
            embedding_function=self._create_langchain_embedding(),
            persist_directory=self.persist_directory,
        )
    
    def _create_langchain_embedding(self):
        """
        创建 LangChain 兼容的 Embedding 函数
        
        使用 DashScope text-embedding-v2（阿里云通义千问）。
        如果 API 不可用，回退到本地 sentence-transformers（需能访问 HuggingFace）。
        """
        from langchain_community.embeddings import DashScopeEmbeddings
        
        api_key = os.getenv("DASHSCOPE_API_KEY")
        
        # 显式设置全局 API key，确保 SDK 能读取到
        if api_key:
            dashscope.api_key = api_key
        
        return DashScopeEmbeddings(
            model="text-embedding-v2",
            dashscope_api_key=api_key,
        )
    
    def add_document(
        self,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        doc_id: Optional[str] = None,
    ) -> List[str]:
        """
        添加文档到知识库
        
        Args:
            content: 文档内容
            metadata: 元数据（来源、类型等）
            doc_id: 文档 ID（可选）
            
        Returns:
            切分后的 chunk IDs
        """
        metadata = metadata or {}
        
        # 切分文档
        chunks = self._splitter.split_text(content)
        
        # 为每个 chunk 添加元数据
        metadatas = []
        for i, chunk in enumerate(chunks):
            chunk_meta = {
                **metadata,
                "chunk_index": i,
                "total_chunks": len(chunks),
            }
            metadatas.append(chunk_meta)
        
        # 添加到向量库（embedding 可能因 API 欠费等原因失败）
        try:
            ids = self._vectorstore.add_texts(
                texts=chunks,
                metadatas=metadatas,
            )
        except Exception as e:
            err_msg = str(e)
            if "Arrearage" in err_msg or "overdue" in err_msg.lower():
                raise RuntimeError(
                    "⚠️ DashScope API 账户欠费，无法生成向量。\n"
                    "请前往 https://dashscope.console.aliyun.com/ 充值后重试。"
                ) from e
            raise RuntimeError(f"⚠️ 向量化失败: {err_msg}") from e
        
        return ids
    
    def add_documents(
        self,
        documents: List[Document],
    ) -> List[str]:
        """
        批量添加文档
        
        Args:
            documents: 文档列表
            
        Returns:
            所有 chunk IDs
        """
        all_ids = []
        for doc in documents:
            ids = self.add_document(doc.content, doc.metadata)
            all_ids.extend(ids)
        return all_ids
    
    def retrieve(
        self,
        query: str,
        k: int = 5,
        filter: Optional[Dict[str, Any]] = None,
        rerank: bool = True,
        retrieve_k: Optional[int] = None,
    ) -> List[RetrievalResult]:
        """检索相关文档（支持两阶段检索：embedding 召回 → reranker 精排）。

        Args:
            query: 查询文本
            k: 最终返回结果数量（reranker 精排后保留量）
            filter: 元数据过滤条件
            rerank: 是否启用 reranker 精排
            retrieve_k: embedding 初始召回量，默认 k*3（仅 rerank=True 时生效）

        Returns:
            检索结果列表（按相关性降序）
        """
        from src.rag.reranker import get_reranker

        reranker = get_reranker() if rerank else None

        if reranker and reranker.is_available():
            # 两阶段检索：大范围召回 → 精排
            initial_k = retrieve_k or (k * 3)
            results = self._vectorstore.similarity_search_with_score(
                query=query, k=initial_k, filter=filter,
            )
            if not results:
                return []

            passages = [doc.page_content for doc, _ in results]
            try:
                reranked = reranker.rerank(query, passages, top_k=k)
            except Exception as e:
                logger.error("[RAGEngine] Reranker 运行时异常，降级为 embedding-only: %s", e)
                return [
                    RetrievalResult(content=doc.page_content, metadata=doc.metadata, score=float(score))
                    for doc, score in results[:k]
                ]

            # 用 reranker 结果的 index 映射回原始 metadata
            retrieval_results = []
            for rr in reranked:
                doc, _orig_score = results[rr.index]
                retrieval_results.append(RetrievalResult(
                    content=doc.page_content,
                    metadata=doc.metadata,
                    score=rr.score,
                ))
            return retrieval_results
        else:
            # 降级：embedding-only（用 k 而非 retrieve_k，避免噪声）
            results = self._vectorstore.similarity_search_with_score(
                query=query, k=k, filter=filter,
            )
            return [
                RetrievalResult(content=doc.page_content, metadata=doc.metadata, score=float(score))
                for doc, score in results
            ]
    
    def build_context(
        self,
        query: str,
        k: int = 5,
        separator: str = "\n\n---\n\n",
        rerank: bool = True,
        retrieve_k: Optional[int] = None,
    ) -> str:
        """构建 RAG 上下文。

        Args:
            query: 查询文本
            k: 最终检索结果数量
            separator: 结果分隔符
            rerank: 是否启用 reranker 精排
            retrieve_k: embedding 初始召回量

        Returns:
            组装好的上下文字符串
        """
        results = self.retrieve(query, k=k, rerank=rerank, retrieve_k=retrieve_k)
        
        if not results:
            return ""
        
        context_parts = []
        for i, result in enumerate(results, 1):
            source = result.metadata.get("source", "未知来源")
            context_parts.append(f"[来源 {i}: {source}]\n{result.content}")
        
        return separator.join(context_parts)
    
    def delete_collection(self):
        """删除整个 collection"""
        self._vectorstore.delete_collection()
    
    def count(self) -> int:
        """返回文档数量"""
        return self._vectorstore._collection.count()
    
    def query_with_context(
        self,
        query: str,
        k: int = 5,
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        RAG 问答：检索 + LLM 生成
        
        这是 RAG 的核心方法，实现了：
        1. 从知识库检索相关内容
        2. 将检索结果作为上下文注入 Prompt
        3. 调用 LLM 生成回答
        
        Args:
            query: 用户问题
            k: 检索结果数量
            system_prompt: 自定义系统提示词
            
        Returns:
            LLM 生成的回答
            
        面试话术：
        > "query_with_context 是 RAG 的核心。先用向量检索找相关内容，
        >  然后把内容塞进 Prompt 让 LLM 基于这些内容回答。
        >  这样既利用了 LLM 的推理能力，又保证了回答有据可依。"
        """
        from src.providers import ProviderFactory
        
        # Step 1: 检索相关内容
        context = self.build_context(query, k=k)
        
        # Step 2: 构建 Prompt
        if not system_prompt:
            system_prompt = """你是一个智能学习助手。请基于以下参考资料回答用户的问题。

如果参考资料中没有相关信息，请如实告知，不要编造。
回答时请引用资料来源。"""

        if context:
            full_prompt = f"""{system_prompt}

## 参考资料

{context}

## 用户问题

{query}

请基于以上参考资料回答问题："""
        else:
            full_prompt = f"""{system_prompt}

（注意：知识库中没有找到相关内容，请基于你的通用知识回答）

用户问题：{query}"""

        # Step 3: 调用 LLM
        from src.providers.base import Message
        llm = ProviderFactory.create_llm()
        
        messages = [
            Message(role="user", content=full_prompt)
        ]
        
        response = llm.chat(messages)
        return response.content
    
    def search(
        self,
        query: str,
        k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        简化版检索接口，返回字典列表
        
        用于 UI 展示检索结果
        """
        results = self.retrieve(query, k=k)
        return [
            {
                "content": r.content,
                "source": r.metadata.get("source", "未知"),
                "score": r.score,
            }
            for r in results
        ]
    
    def clear(self):
        """清空知识库"""
        self.delete_collection()
        # 重新创建
        self._vectorstore = Chroma(
            collection_name=self.collection_name,
            embedding_function=self._create_langchain_embedding(),
            persist_directory=self.persist_directory,
        )

