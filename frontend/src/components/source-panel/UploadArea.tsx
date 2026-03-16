/**
 * UploadArea — 紧凑的添加来源条
 *
 * 设计：单行条，左侧 + 按钮（点击弹文件选择），右侧输入框（粘贴 URL）
 * 整个条支持拖拽文件上传，拖入时高亮
 */
import React, { useState, useRef, useCallback } from 'react'
import { useMaterialUpload } from '../../hooks/useMaterialUpload'

interface UploadAreaProps {
  planId: string
}

export const UploadArea: React.FC<UploadAreaProps> = ({ planId }) => {
  const [dragging, setDragging] = useState(false)
  const [urlInput, setUrlInput] = useState('')
  const [error, setError] = useState('')
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const { uploadFile, uploadUrl } = useMaterialUpload(planId)
  const dragCounter = useRef(0)

  const handleFiles = useCallback(async (files: FileList | null) => {
    if (!files?.length) return
    setError('')
    setUploading(true)
    try {
      const ALLOWED_EXTS = ['.pdf', '.md', '.markdown', '.txt']
      for (const file of Array.from(files)) {
        const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
        if (!ALLOWED_EXTS.includes(ext)) {
          setError('支持 PDF、Markdown、TXT 文件')
          continue
        }
        await uploadFile(file)
      }
    } catch {
      setError('上传失败，请重试')
    } finally {
      setUploading(false)
    }
  }, [uploadFile])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    dragCounter.current = 0
    setDragging(false)
    handleFiles(e.dataTransfer.files)
  }, [handleFiles])

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    dragCounter.current++
    setDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    dragCounter.current--
    if (dragCounter.current <= 0) {
      dragCounter.current = 0
      setDragging(false)
    }
  }, [])

  const handleUrlSubmit = async () => {
    const url = urlInput.trim()
    if (!url) return
    if (!url.startsWith('http')) { setError('请输入有效的 URL'); return }
    setError('')
    setUploading(true)
    try {
      await uploadUrl(url)
      setUrlInput('')
    } catch {
      setError('URL 添加失败，请重试')
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="flex flex-col gap-1.5">
      <div
        onDragOver={e => e.preventDefault()}
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`flex items-center gap-2 h-10 rounded-lg border transition-all duration-50 ${
          dragging
            ? 'border-[#D97757] bg-[#FDF5F0]'
            : 'border-[#E5E5E5] hover:border-[#D97757]/40'
        }`}
      >
        {/* 上传按钮 */}
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className="flex items-center justify-center w-10 h-full text-[#9AA0A6] hover:text-[#D97757] transition-colors flex-shrink-0 border-r border-[#E5E5E5]"
          aria-label="上传文件（PDF / MD / TXT）"
          title="上传文件"
        >
          {uploading ? (
            <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" opacity="0.3"/><path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          )}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.md,.markdown,.txt"
          multiple
          className="hidden"
          onChange={e => handleFiles(e.target.files)}
          aria-label="选择文件"
        />

        {/* URL 输入 */}
        <input
          value={urlInput}
          onChange={e => setUrlInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleUrlSubmit()}
          placeholder={dragging ? '松开以上传文件...' : '粘贴 URL 或拖拽文件到此处'}
          disabled={dragging}
          className="flex-1 h-full bg-transparent text-sm text-[#202124] placeholder:text-[#9AA0A6] outline-none pr-2"
          aria-label="粘贴 URL"
        />

        {/* URL 提交按钮 — 仅在有输入时显示 */}
        {urlInput.trim() && (
          <button
            onClick={handleUrlSubmit}
            disabled={uploading}
            className="flex-shrink-0 h-7 px-3 mr-1.5 bg-[#D97757] text-white text-xs rounded-md hover:bg-[#C06144] disabled:opacity-40 transition-colors"
            aria-label="添加 URL"
          >
            添加
          </button>
        )}
      </div>

      {error && (
        <p className="text-xs text-red-500 px-1">{error}</p>
      )}
    </div>
  )
}
