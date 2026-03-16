import React, { useState, useRef, useCallback } from 'react'
import { useChatStore } from '../../store/chatStore'
import type { AttachedMaterial } from '../../store/chatStore'

interface ChatInputProps {
  onSend: (text: string) => void
  disabled?: boolean
  placeholder?: string
  onCancel?: () => void
}

export const ChatInput: React.FC<ChatInputProps> = ({
  onSend, disabled = false, placeholder = '向 AI 提问...', onCancel,
}) => {
  const [value, setValue] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const { attachedMaterials, detachMaterial, attachMaterial } = useChatStore()

  const handleSend = useCallback(() => {
    const text = value.trim()
    if (!text || disabled) return
    onSend(text)
    setValue('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }, [value, disabled, onSend])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value)
    const el = e.target
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 200) + 'px'
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    try {
      const raw = e.dataTransfer.getData('application/material')
      if (raw) {
        const mat: AttachedMaterial = JSON.parse(raw)
        attachMaterial(mat)
      }
    } catch { /* ignore */ }
  }

  const handleDragOver = (e: React.DragEvent) => {
    if (e.dataTransfer.types.includes('application/material')) {
      e.preventDefault()
      setDragOver(true)
    }
  }

  const handleDragLeave = () => setDragOver(false)

  const canSend = value.trim().length > 0 && !disabled

  return (
    <div className="px-8 pb-8 pt-4 bg-transparent flex-shrink-0 w-full flex justify-center">
      <div className="w-full max-w-3xl">
        <div
          className={`relative flex flex-col rounded-3xl border focus-within:border-[#D97757]/50 focus-within:ring-4 focus-within:ring-[#D97757]/10 bg-[#F9F9F9] px-5 py-2.5 transition-all duration-50 shadow-sm ${dragOver ? 'border-[#D97757] ring-4 ring-[#D97757]/20 bg-[#FFF8F5]' : 'border-[#E5E5E5]'
            }`}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
        >

          {/* 附加材料徽章 */}
          {attachedMaterials.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-2">
              {attachedMaterials.map(m => (
                <span
                  key={m.id}
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-[#F2DFD3] text-[#D97757] text-xs font-medium max-w-[180px]"
                >
                  <span className="truncate">{m.name}</span>
                  <button
                    onClick={() => detachMaterial(m.id)}
                    className="flex-shrink-0 hover:text-red-500 transition-colors ml-0.5"
                    aria-label={`移除 ${m.name}`}
                  >
                    ✕
                  </button>
                </span>
              ))}
            </div>
          )}

          {/* 拖拽提示 */}
          {dragOver && (
            <div className="flex items-center gap-2 mb-2 text-xs text-[#D97757]">
              <span>📎</span>
              <span>松开以附加材料到此消息</span>
            </div>
          )}

          <div className="flex items-end gap-2">
            <textarea
              ref={textareaRef}
              value={value}
              onChange={handleInput}
              onKeyDown={handleKeyDown}
              placeholder={attachedMaterials.length > 0 ? '基于附加材料提问...' : placeholder}
              rows={1}
              className="flex-1 resize-none bg-transparent text-base text-[#202124] placeholder:text-[#9AA0A6] outline-none min-h-[44px] max-h-[200px] py-2"
              aria-label="输入消息"
            />
            {onCancel ? (
              <button
                onClick={onCancel}
                aria-label="停止生成"
                className="flex-shrink-0 mb-1 px-4 py-2 rounded-xl text-sm font-medium bg-[#F1F3F4] text-[#5F6368] hover:bg-[#DADCE0] transition-all duration-50"
              >
                ⏹ 停止
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={!canSend}
                aria-label="发送消息"
                className={`flex-shrink-0 mb-1 px-4 py-2 rounded-xl text-sm font-medium transition-all duration-50 ${canSend
                  ? 'bg-[#D97757] text-white hover:bg-[#C06144] active:scale-95 shadow-sm'
                  : 'bg-[#F1F3F4] text-[#9AA0A6] cursor-not-allowed'
                  }`}
              >
                发送
              </button>
            )}
          </div>
        </div>
        <div className="flex justify-center w-full mt-3">
          <p className="text-[11px] text-[#9AA0A6]">AI 可能会犯错。请核查重要信息。Enter 发送 · Shift+Enter 换行 · 拖拽材料到此处附加</p>
        </div>
      </div>
    </div>
  )
}
