"""
PDF 分析器

职责：
1. 提取 PDF 正文内容
2. 识别标题、章节结构
3. 提取关键信息

风险控制：
- 只提取正文，跳过复杂结构（表格、公式）
- 避免质量问题导致 RAG 效果差

面试话术：
> "PDFAnalyzer 专门负责解析用户上传的 PDF，用 PyMuPDF 提取文本。
>  有 analyze_from_bytes() 方法处理内存中的文件，
>  to_learning_context() 方法把内容转成学习上下文格式。"

TODO (Day 8):
- 实现 PyMuPDF 解析
- 改进结构化提取
"""

import os
from typing import Optional, List, Dict, Any
from pathlib import Path
from pydantic import BaseModel


class PDFContent(BaseModel):
    """PDF 内容"""
    title: str = ""
    authors: List[str] = []
    abstract: str = ""
    content: str = ""
    sections: List[Dict[str, str]] = []  # [{"title": "...", "content": "..."}]
    total_pages: int = 0
    

class PDFAnalyzer:
    """
    PDF 分析器
    
    解析 PDF 文件，提取学习相关内容
    """
    
    def __init__(self):
        """初始化分析器"""
        # 检查 PyMuPDF 是否可用
        self._fitz_available = False
        try:
            import fitz
            self._fitz_available = True
        except ImportError:
            print("⚠️  PyMuPDF (fitz) not installed. PDF parsing will be limited.")
    
    def analyze(self, pdf_path: str) -> PDFContent:
        """
        分析 PDF 文件
        
        Args:
            pdf_path: PDF 文件路径
            
        Returns:
            PDFContent 对象
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        if self._fitz_available:
            return self._analyze_with_fitz(pdf_path)
        else:
            return self._analyze_fallback(pdf_path)
    
    def _analyze_with_fitz(self, pdf_path: str) -> PDFContent:
        """使用 PyMuPDF 解析 PDF"""
        import fitz
        
        doc = fitz.open(pdf_path)
        
        # 提取所有文本
        all_text = []
        for page in doc:
            text = page.get_text()
            all_text.append(text)
        
        content = "\n".join(all_text)
        
        # 尝试提取标题（第一页的第一行通常是标题）
        title = ""
        if all_text and all_text[0]:
            first_page_lines = all_text[0].strip().split("\n")
            if first_page_lines:
                title = first_page_lines[0].strip()
        
        # 尝试提取摘要
        abstract = self._extract_abstract(content)
        
        doc.close()
        
        return PDFContent(
            title=title,
            content=content,
            abstract=abstract,
            total_pages=len(all_text),
        )
    
    def _analyze_fallback(self, pdf_path: str) -> PDFContent:
        """
        降级处理：当 PyMuPDF 不可用时
        """
        return PDFContent(
            title=Path(pdf_path).stem,
            content=f"PDF 解析需要安装 PyMuPDF。文件路径: {pdf_path}",
            total_pages=0,
        )
    
    def _extract_abstract(self, content: str) -> str:
        """
        提取摘要
        
        简化版：查找 Abstract/摘要 关键词后的内容
        """
        import re
        
        # 英文论文
        match = re.search(r'abstract[:\s]*(.{100,1000}?)(?=\n\n|\d\.|introduction)', 
                         content, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
        
        # 中文论文
        match = re.search(r'摘\s*要[：:\s]*(.{50,500}?)(?=\n\n|关键词|1[.\s])', 
                         content, re.DOTALL)
        if match:
            return match.group(1).strip()
        
        return ""
    
    def analyze_from_bytes(self, pdf_bytes: bytes, filename: str = "upload.pdf") -> PDFContent:
        """
        从字节流分析 PDF
        
        用于处理上传的文件
        """
        if not self._fitz_available:
            return PDFContent(
                title=filename,
                content="PDF 解析需要安装 PyMuPDF。",
                total_pages=0,
            )
        
        import fitz
        
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        
        all_text = []
        for page in doc:
            text = page.get_text()
            all_text.append(text)
        
        content = "\n".join(all_text)
        
        title = filename
        if all_text and all_text[0]:
            first_page_lines = all_text[0].strip().split("\n")
            if first_page_lines:
                title = first_page_lines[0].strip() or filename
        
        abstract = self._extract_abstract(content)
        
        doc.close()
        
        return PDFContent(
            title=title,
            content=content,
            abstract=abstract,
            total_pages=len(all_text),
        )
    
    def to_learning_context(self, pdf_content: PDFContent) -> str:
        """
        将 PDF 内容转换为学习上下文
        """
        parts = [
            f"# {pdf_content.title}",
            "",
        ]
        
        if pdf_content.abstract:
            parts.extend([
                "## 摘要",
                "",
                pdf_content.abstract,
                "",
            ])
        
        parts.extend([
            "## 正文内容",
            "",
            "## 正文内容",
            "",
            pdf_content.content,
        ])
        
        return "\n".join(parts)
    
    def import_to_rag(
        self, 
        pdf_content: PDFContent,
        rag_engine = None,
    ) -> List[str]:
        """
        将 PDF 内容导入 RAG 知识库
        
        Args:
            pdf_content: PDFContent 对象
            rag_engine: RAGEngine 实例（可选，默认创建新的）
            
        Returns:
            导入的 chunk IDs
            
        面试话术：
        > "import_to_rag 实现了 PDF → RAG 的自动导入。
        >  用户上传 PDF 后，先用 PDFAnalyzer 提取内容，
        >  然后调用这个方法把内容切分、向量化存入知识库。"
        """
        if rag_engine is None:
            from src.rag import RAGEngine
            rag_engine = RAGEngine()
        
        # 准备文本内容
        text = self.to_learning_context(pdf_content)
        
        # 准备元数据
        metadata = {
            "source": pdf_content.title or "PDF Document",
            "type": "pdf",
            "pages": pdf_content.total_pages,
        }
        
        # 导入 RAG
        ids = rag_engine.add_document(text, metadata)
        
        return ids

