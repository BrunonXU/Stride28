"""
文件上传端点

支持：
- PDF 文件上传（multipart/form-data）
- GitHub URL 粘贴（JSON body）

上传后异步进行 parsing → chunking → ready 状态流转。
"""

import uuid
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend import database

logger = logging.getLogger(__name__)
router = APIRouter(tags=["upload"])

UPLOAD_DIR = Path("data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


class UrlUploadRequest(BaseModel):
    planId: str
    url: str  # GitHub URL 或其他网页 URL


class UploadResponse(BaseModel):
    id: str
    name: str
    type: str
    status: str
    addedAt: str


def _detect_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext in (".md", ".markdown"):
        return "markdown"
    if ext == ".txt":
        return "text"
    return "other"


async def _process_pdf(material_id: str, plan_id: str, file_path: Path, filename: str):
    """后台任务：PDF 解析 → chunking → ready，更新数据库状态"""
    try:
        database.update_material_status(material_id, "parsing")
        await asyncio.sleep(0.5)  # 模拟解析延迟

        # 尝试用 RAGEngine 真实解析
        try:
            from src.rag import RAGEngine
            rag = RAGEngine(collection_name=f"plan_{plan_id}")
            content = file_path.read_bytes()
            text = _extract_pdf_text(content)
            if text:
                # 存储全文到 extra_data.contentText（read-merge-write，不覆盖已有字段）
                existing = database.get_material_extra_data(material_id) or {}
                existing["contentText"] = text.strip()
                database.update_material_extra_data(material_id, existing)

                database.update_material_status(material_id, "chunking")
                await asyncio.sleep(0.3)
                rag.add_document(
                    content=text,
                    metadata={"source": filename, "plan_id": plan_id, "material_id": material_id},
                    doc_id=material_id,
                )
        except Exception as e:
            logger.warning(f"RAG ingest failed for {filename}: {e}")

        database.update_material_status(material_id, "ready")
    except Exception as e:
        logger.error(f"PDF processing failed: {e}")
        database.update_material_status(material_id, "error")


def _extract_pdf_text(content: bytes) -> str:
    """提取 PDF 纯文本（用于 RAG 索引）"""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=content, filetype="pdf")
        return "\n".join(page.get_text() for page in doc)
    except ImportError:
        pass
    try:
        import pdfplumber, io
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            return "\n".join(p.extract_text() or "" for p in pdf.pages)
    except ImportError:
        pass
    return ""


def _extract_pdf_rich_content(content: bytes) -> str:
    """提取 PDF 图文混排内容（文本 + base64 图片），返回 Markdown 格式"""
    import base64
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=content, filetype="pdf")
        parts: list[str] = []
        for page_idx, page in enumerate(doc):
            # 提取文本
            text = page.get_text().strip()
            if text:
                parts.append(text)

            # 提取图片
            for img_info in page.get_images(full=True):
                xref = img_info[0]
                try:
                    img_data = doc.extract_image(xref)
                    if img_data and img_data.get("image"):
                        ext = img_data.get("ext", "png")
                        mime = f"image/{ext}" if ext != "jpg" else "image/jpeg"
                        b64 = base64.b64encode(img_data["image"]).decode("ascii")
                        parts.append(f"\n![图片](data:{mime};base64,{b64})\n")
                except Exception:
                    continue  # 跳过无法提取的图片

            # 页面分隔
            if page_idx < len(doc) - 1:
                parts.append("\n---\n")

        return "\n".join(parts)
    except ImportError:
        # PyMuPDF 不可用，降级到纯文本
        return _extract_pdf_text(content)


async def _process_text_file(material_id: str, plan_id: str, file_path: Path, filename: str):
    """后台任务：MD/TXT 文件解析 → chunking → ready"""
    try:
        database.update_material_status(material_id, "parsing")
        await asyncio.sleep(0.3)

        text = file_path.read_text(encoding="utf-8", errors="replace")
        if text.strip():
            # 存储全文到 extra_data.contentText（read-merge-write，不覆盖已有字段）
            existing = database.get_material_extra_data(material_id) or {}
            existing["contentText"] = text.strip()
            database.update_material_extra_data(material_id, existing)

            database.update_material_status(material_id, "chunking")
            await asyncio.sleep(0.2)
            try:
                from src.rag import RAGEngine
                rag = RAGEngine(collection_name=f"plan_{plan_id}")
                rag.add_document(
                    content=text,
                    metadata={"source": filename, "plan_id": plan_id, "material_id": material_id},
                    doc_id=material_id,
                )
            except Exception as e:
                logger.warning(f"RAG ingest failed for {filename}: {e}")

        database.update_material_status(material_id, "ready")
    except Exception as e:
        logger.error(f"Text file processing failed: {e}")
        database.update_material_status(material_id, "error")


async def _process_url(material_id: str, plan_id: str, url: str):
    """后台任务：抓取 URL 内容 → chunking → ready"""
    try:
        database.update_material_status(material_id, "parsing")
        await asyncio.sleep(1.0)
        # TODO: 接入 GitHub README 抓取 / 网页爬取
        database.update_material_status(material_id, "ready")
    except Exception as e:
        logger.error(f"URL processing failed: {e}")
        database.update_material_status(material_id, "error")


def _sync_source_count(plan_id: str):
    """Sync plan's source_count with actual material count in database."""
    materials = database.get_materials(plan_id)
    database.update_plan(plan_id, {"sourceCount": len(materials)})


@router.post("/upload", response_model=UploadResponse, status_code=201)
async def upload_file(
    background_tasks: BackgroundTasks,
    plan_id: str = "",
    file: UploadFile = File(...),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename")

    material_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    mat_type = _detect_type(file.filename)

    # 保存文件
    save_path = UPLOAD_DIR / f"{material_id}_{file.filename}"
    content = await file.read()
    save_path.write_bytes(content)

    # 写入数据库
    database.insert_material({
        "id": material_id,
        "planId": plan_id,
        "name": file.filename,
        "type": mat_type,
        "url": None,
        "status": "parsing",
        "addedAt": now,
        "extraData": {},
    })

    # Sync source_count
    _sync_source_count(plan_id)

    # 后台处理
    if mat_type == "pdf":
        background_tasks.add_task(_process_pdf, material_id, plan_id, save_path, file.filename)
    elif mat_type in ("markdown", "text"):
        background_tasks.add_task(_process_text_file, material_id, plan_id, save_path, file.filename)
    else:
        background_tasks.add_task(_process_text_file, material_id, plan_id, save_path, file.filename)

    return UploadResponse(
        id=material_id,
        name=file.filename,
        type=mat_type,
        status="parsing",
        addedAt=now,
    )


@router.post("/upload/url", response_model=UploadResponse, status_code=201)
async def upload_url(body: UrlUploadRequest, background_tasks: BackgroundTasks):
    material_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # 从 URL 推断名称
    name = body.url.split("/")[-1] or body.url[:40]
    mat_type = "github" if "github.com" in body.url else "web"

    # 写入数据库
    database.insert_material({
        "id": material_id,
        "planId": body.planId,
        "name": name,
        "type": mat_type,
        "url": body.url,
        "status": "parsing",
        "addedAt": now,
        "extraData": {},
    })

    # Sync source_count
    _sync_source_count(body.planId)

    background_tasks.add_task(_process_url, material_id, body.planId, body.url)

    return UploadResponse(
        id=material_id,
        name=name,
        type=mat_type,
        status="parsing",
        addedAt=now,
    )


@router.get("/material/{material_id}/status")
async def get_material_status(material_id: str, plan_id: str = ""):
    """轮询材料处理状态"""
    # Query database for the material
    if plan_id:
        materials = database.get_materials(plan_id)
        for m in materials:
            if m["id"] == material_id:
                return {"id": material_id, "status": m["status"]}

    # Fallback: check disk for uploaded files
    for f in UPLOAD_DIR.iterdir():
        if f.name.startswith(f"{material_id}_"):
            return {"id": material_id, "status": "ready"}

    raise HTTPException(status_code=404, detail="Material not found")


@router.get("/material/{material_id}/summary")
async def get_material_summary(material_id: str, plan_id: str = ""):
    """获取材料摘要，点击材料时插入对话区"""
    if plan_id:
        materials = database.get_materials(plan_id)
        for m in materials:
            if m["id"] == material_id:
                name = m.get("name", "未知材料")
                return {
                    "id": material_id,
                    "name": name,
                    "summary": f"📄 已加载材料：{name}。你可以向 AI 提问关于此材料的内容。",
                }

    # Fallback: try to find from disk
    for f in UPLOAD_DIR.iterdir():
        if f.name.startswith(f"{material_id}_"):
            name = f.name[len(material_id) + 1:]
            return {
                "id": material_id,
                "name": name,
                "summary": f"📄 已加载材料：{name}。你可以向 AI 提问关于此材料的内容。",
            }

    raise HTTPException(status_code=404, detail="Material not found")


@router.delete("/material/{material_id}", status_code=204)
async def delete_material(material_id: str, plan_id: str = ""):
    """移除材料"""
    deleted = database.delete_material(material_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Material not found")


@router.patch("/material/{material_id}/viewed", status_code=200)
async def mark_material_viewed(material_id: str):
    """标记材料为已读"""
    conn = database.get_connection()
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        cur = conn.execute(
            "UPDATE materials SET viewed_at = ? WHERE id = ? AND viewed_at IS NULL",
            (now, material_id),
        )
    return {"ok": True, "updated": cur.rowcount > 0}


@router.get("/material/{material_id}/content")
async def get_material_content(material_id: str, plan_id: str = ""):
    """获取材料的原始文本内容（用于 ContentViewer 展示）"""
    mat = None
    if plan_id:
        materials = database.get_materials(plan_id)
        for m in materials:
            if m["id"] == material_id:
                mat = m
                break

    mat_type = mat.get("type", "text") if mat else None

    # 查找上传文件
    for f in UPLOAD_DIR.iterdir():
        if f.name.startswith(f"{material_id}_"):
            if mat_type is None:
                ext = f.suffix.lower()
                if ext == ".pdf":
                    mat_type = "pdf"
                elif ext in (".md", ".markdown"):
                    mat_type = "markdown"
                else:
                    mat_type = "text"

            file_type = "markdown" if mat_type == "markdown" else ("pdf" if mat_type == "pdf" else "text")
            try:
                if mat_type == "pdf":
                    content = _extract_pdf_text(f.read_bytes())
                else:
                    content = f.read_text(encoding="utf-8", errors="replace")
                return {"id": material_id, "content": content, "fileType": file_type}
            except Exception as e:
                logger.error(f"读取材料内容失败: {e}")
                raise HTTPException(status_code=500, detail="读取内容失败")

    if not mat:
        raise HTTPException(status_code=404, detail="Material not found")

    if mat.get("status") != "ready":
        return {"id": material_id, "content": "", "fileType": "text", "error": "材料尚未处理完成"}

    return {"id": material_id, "content": "", "fileType": "text", "error": "文件未找到"}


@router.get("/material/{material_id}/raw")
async def get_material_raw(material_id: str):
    """返回原始上传文件（PDF 内嵌渲染用）"""
    for f in UPLOAD_DIR.iterdir():
        if f.name.startswith(f"{material_id}_"):
            ext = f.suffix.lower()
            media = "application/pdf" if ext == ".pdf" else "text/plain; charset=utf-8"
            return FileResponse(
                f,
                media_type=media,
                headers={"Content-Disposition": "inline"},
            )
    raise HTTPException(status_code=404, detail="File not found")


class SearchMaterialItem(BaseModel):
    id: str
    planId: str
    platform: str
    name: str
    url: str
    extraData: Optional[dict] = None


class BatchAddRequest(BaseModel):
    items: list[SearchMaterialItem]


class ReorderRequest(BaseModel):
    orderedIds: list[str]


@router.patch("/plans/{plan_id}/materials/reorder", status_code=200)
async def reorder_materials(plan_id: str, body: ReorderRequest):
    """持久化材料拖拽排序"""
    database.update_material_order(plan_id, body.orderedIds)
    return {"ok": True}


@router.post("/materials/from-search", status_code=201)
async def add_materials_from_search(body: BatchAddRequest):
    """将搜索结果批量加入学习材料（持久化到数据库 + ChromaDB）"""
    added = []
    for item in body.items:
        try:
            database.insert_material({
                "id": item.id,
                "planId": item.planId,
                "type": item.platform,
                "name": item.name,
                "url": item.url,
                "status": "ready",
                "addedAt": datetime.now(timezone.utc).isoformat(),
                "extraData": item.extraData or {},
            })
            added.append(item.id)

            # 写入 ChromaDB，使 Studio 全局 RAG 可检索
            _ingest_search_material_to_chroma(item)
        except (ValueError, RuntimeError) as e:
            logger.warning("Skip duplicate or failed material %s: %s", item.id, e)
    # Sync source count for each unique plan
    plan_ids = set(item.planId for item in body.items)
    for pid in plan_ids:
        _sync_source_count(pid)
    return {"added": added, "count": len(added)}


def _ingest_search_material_to_chroma(item: SearchMaterialItem) -> None:
    """将搜索来源材料的 extra_data 内容写入 ChromaDB。"""
    extra = item.extraData or {}
    if not extra:
        return

    # 拼接有效内容
    parts = []
    content_text = extra.get("contentText") or ""
    if content_text:
        parts.append(content_text)
    summary = extra.get("contentSummary") or ""
    if summary:
        parts.append(summary)
    key_points = extra.get("keyPoints") or []
    if key_points:
        parts.append("\n".join(key_points))
    key_facts = extra.get("keyFacts") or []
    if key_facts:
        parts.append("；".join(key_facts))

    content = "\n\n".join(parts).strip()
    if not content:
        return

    try:
        from src.rag import RAGEngine
        rag = RAGEngine(collection_name=f"plan_{item.planId}")
        rag.add_document(
            content=content,
            metadata={
                "material_id": item.id,
                "source": item.name,
                "plan_id": item.planId,
            },
        )
        logger.info(f"[upload] ChromaDB ingest OK for search material {item.id}")
    except Exception as e:
        logger.warning(f"[upload] ChromaDB ingest failed for {item.id}: {e}")
