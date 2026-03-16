"""
本地 Embedding Provider（免费，无需 API Key）

使用 sentence-transformers 在本地运行 embedding 模型。
默认模型 paraphrase-multilingual-MiniLM-L12-v2 支持中英文，
首次运行会自动下载模型（约 500MB），之后离线可用。

面试话术：
> "为了降低成本和消除 API 依赖，我实现了本地 Embedding Provider。
>  使用 sentence-transformers 的多语言模型，支持中英文，
>  通过 LangChain 的 Embeddings 接口无缝集成到 RAG 流程中。"
"""

from typing import List
from langchain_core.embeddings import Embeddings


class LocalEmbeddingProvider:
    """本地 Embedding Provider，基于 sentence-transformers"""

    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        self._model_name = model_name
        self._model = None  # lazy load

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
        return self._model

    @property
    def embedding_dim(self) -> int:
        return 384  # MiniLM-L12-v2 输出维度

    def embed_text(self, text: str) -> List[float]:
        return self._get_model().encode(text).tolist()

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        return self._get_model().encode(texts).tolist()

    def embed_query(self, query: str) -> List[float]:
        return self.embed_text(query)


class LocalLangChainEmbedding(Embeddings):
    """LangChain 兼容的本地 Embedding 包装器，可直接传给 Chroma"""

    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        self._provider = LocalEmbeddingProvider(model_name)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._provider.embed_texts(texts)

    def embed_query(self, text: str) -> List[float]:
        return self._provider.embed_query(text)
