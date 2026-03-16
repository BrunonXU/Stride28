"""
笔记 CRUD 端点 — 使用 SQLite 持久化
"""

import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from backend import database

router = APIRouter(tags=["notes"])


class NoteCreate(BaseModel):
    planId: str
    title: str
    content: str


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None


class NoteResponse(BaseModel):
    id: str
    planId: str
    title: str
    content: str
    createdAt: str
    updatedAt: str


@router.post("/notes", response_model=NoteResponse, status_code=201)
async def create_note(body: NoteCreate):
    now = datetime.now(timezone.utc).isoformat()
    note_data = {
        "id": str(uuid.uuid4()),
        "planId": body.planId,
        "title": body.title,
        "content": body.content,
        "createdAt": now,
        "updatedAt": now,
    }
    result = database.create_note(note_data)
    return result


@router.put("/notes/{note_id}", response_model=NoteResponse)
async def update_note(note_id: str, body: NoteUpdate):
    updates = {}
    if body.title is not None:
        updates["title"] = body.title
    if body.content is not None:
        updates["content"] = body.content
    result = database.update_note(note_id, updates)
    if result is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return result


@router.delete("/notes/{note_id}", status_code=204)
async def delete_note(note_id: str):
    deleted = database.delete_note(note_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Note not found")
