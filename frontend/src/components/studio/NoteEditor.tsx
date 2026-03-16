/**
 * NoteEditor — Markdown 笔记编辑器
 * 支持新建/编辑，"AI 整理"按钮调用 /api/chat/sync 整理笔记内容
 */
import React, { useState, useEffect } from 'react'
import { Spinner } from '../ui/Spinner'
import type { Note } from '../../types'

interface NoteEditorProps {
  note?: Note | null       // null = 新建
  planId: string
  onSave: (data: { id?: string; title: string; content: string }) => void
  onClose: () => void
}

export const NoteEditor: React.FC<NoteEditorProps> = ({ note, planId, onSave, onClose }) => {
  const [title, setTitle] = useState(note?.title ?? '')
  const [content, setContent] = useState(note?.content ?? '')
  const [isSaving, setIsSaving] = useState(false)
  const [isAiOrganizing, setIsAiOrganizing] = useState(false)

  useEffect(() => {
    setTitle(note?.title ?? '')
    setContent(note?.content ?? '')
  }, [note])

  const handleSave = async () => {
    if (!title.trim()) return
    setIsSaving(true)
    onSave({ id: note?.id, title: title.trim(), content })
    setIsSaving(false)
    onClose()
  }

  // AI 整理：调用 /api/chat/sync，让 Tutor 整理笔记
  const handleAiOrganize = async () => {
    if (!content.trim() || isAiOrganizing) return
    setIsAiOrganizing(true)
    try {
      const res = await fetch('/api/chat/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          planId,
          message: `请帮我整理以下笔记，使其结构更清晰、内容更完整，用 Markdown 格式输出：\n\n${content}`,
          history: [],
        }),
      })
      if (res.ok) {
        const data = await res.json()
        if (data.content) setContent(data.content)
      }
    } catch { /* 静默失败 */ }
    finally {
      setIsAiOrganizing(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-white dark:bg-dark-surface rounded-2xl shadow-2xl w-[680px] min-h-[500px] max-h-[80vh] flex flex-col overflow-hidden">
        {/* 标题栏 */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-[#DADCE0] dark:border-dark-border">
          <input
            value={title}
            onChange={e => setTitle(e.target.value)}
            placeholder="笔记标题..."
            className="flex-1 text-base font-semibold bg-transparent outline-none text-[#202124] dark:text-dark-text placeholder:text-[#9AA0A6]"
            aria-label="笔记标题"
          />
          <button
            onClick={onClose}
            aria-label="关闭编辑器"
            className="ml-3 text-[#5F6368] hover:text-[#202124] transition-colors duration-50 text-xl leading-none"
          >
            ×
          </button>
        </div>

        {/* 编辑区 */}
        <textarea
          value={content}
          onChange={e => setContent(e.target.value)}
          placeholder="用 Markdown 写下你的笔记..."
          className="flex-1 px-5 py-4 text-sm leading-relaxed text-[#202124] dark:text-dark-text bg-transparent outline-none resize-none font-mono placeholder:text-[#9AA0A6] dark:placeholder:text-[#5F6368]"
          aria-label="笔记内容"
        />

        {/* 底部操作栏 */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-[#DADCE0] dark:border-dark-border">
          <button
            onClick={handleAiOrganize}
            disabled={isAiOrganizing || !content.trim()}
            className="flex items-center gap-1.5 text-sm text-[#D97757] hover:underline disabled:opacity-40 disabled:no-underline transition-all duration-50"
            aria-label="AI 整理笔记"
          >
            {isAiOrganizing ? <Spinner size="sm" /> : <span>✨</span>}
            AI 整理
          </button>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="h-8 px-4 rounded-lg text-sm text-[#5F6368] hover:bg-[#F1F3F4] transition-colors duration-50"
            >
              取消
            </button>
            <button
              onClick={handleSave}
              disabled={isSaving || !title.trim()}
              className="h-8 px-4 rounded-lg text-sm bg-[#D97757] text-white hover:bg-[#C06144] disabled:opacity-40 transition-colors duration-50 flex items-center gap-1.5"
            >
              {isSaving && <Spinner size="sm" />}
              保存
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
