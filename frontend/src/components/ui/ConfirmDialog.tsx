import React, { useEffect, useRef, useCallback } from 'react'
import { createPortal } from 'react-dom'

export interface ConfirmDialogProps {
  open: boolean
  title?: string
  message: string
  confirmText?: string
  cancelText?: string
  /** danger = 红色确认按钮，用于破坏性操作 */
  variant?: 'default' | 'danger'
  onConfirm: () => void
  onCancel: () => void
}

/**
 * 通用确认对话框
 * - React Portal 渲染到 document.body
 * - Escape 关闭、点击遮罩关闭
 * - 打开时自动聚焦取消按钮（更安全的默认行为）
 * - 打开时禁止 body 滚动
 * - fade-in 动画，z-index 低于 Toast（9990 vs 9999）
 */
export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  open,
  title = '确认',
  message,
  confirmText = '确认',
  cancelText = '取消',
  variant = 'default',
  onConfirm,
  onCancel,
}) => {
  const cancelRef = useRef<HTMLButtonElement>(null)

  // Escape 键关闭
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel()
    },
    [onCancel],
  )

  useEffect(() => {
    if (!open) return
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [open, handleKeyDown])

  // 打开时聚焦取消按钮 + 禁止 body 滚动
  useEffect(() => {
    if (!open) return
    cancelRef.current?.focus()
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [open])

  if (!open) return null

  const confirmBtnClass =
    variant === 'danger'
      ? 'bg-red-600 hover:bg-red-700 focus:ring-red-500'
      : 'bg-blue-600 hover:bg-blue-700 focus:ring-blue-500'

  return createPortal(
    <div
      className="fixed inset-0 z-[9990] flex items-center justify-center animate-fade-in"
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
    >
      {/* 遮罩 */}
      <div
        className="absolute inset-0 bg-black/50"
        onClick={onCancel}
        data-testid="confirm-backdrop"
      />

      {/* 对话框卡片 */}
      <div className="relative bg-white rounded-xl shadow-xl max-w-sm w-full mx-4 p-6 animate-scale-in">
        <h2
          id="confirm-dialog-title"
          className="text-lg font-semibold text-gray-900 mb-2"
        >
          {title}
        </h2>
        <p className="text-sm text-gray-600 leading-relaxed mb-6">{message}</p>

        <div className="flex justify-end gap-3">
          <button
            ref={cancelRef}
            onClick={onCancel}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-gray-400"
          >
            {cancelText}
          </button>
          <button
            onClick={onConfirm}
            className={`px-4 py-2 text-sm font-medium text-white rounded-lg transition-colors focus:outline-none focus:ring-2 ${confirmBtnClass}`}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
