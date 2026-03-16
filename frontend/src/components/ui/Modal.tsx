import React, { useEffect } from 'react'
import { createPortal } from 'react-dom'
interface ModalProps {
  open: boolean
  onClose: () => void
  title?: string
  children: React.ReactNode
  width?: string
}

export const Modal: React.FC<ModalProps> = ({
  open,
  onClose,
  title,
  children,
  width = 'max-w-lg',
}) => {
  // Escape 键关闭
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open, onClose])

  if (!open) return null

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center"
      role="dialog"
      aria-modal="true"
    >
      {/* 遮罩 */}
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      {/* 弹窗内容 */}
      <div className={`relative bg-surface rounded-2xl shadow-2xl w-full ${width} mx-4 animate-in fade-in zoom-in-95 duration-50`}>
        {title && (
          <div className="flex items-center justify-between px-6 py-4 border-b border-border">
            <h2 className="text-lg font-semibold text-text-primary">{title}</h2>
            <button
              onClick={onClose}
              aria-label="关闭弹窗"
              className="text-text-disabled hover:text-text-primary rounded-lg p-1 hover:bg-surface-tertiary transition-colors duration-50"
            >
              ✕
            </button>
          </div>
        )}
        <div className="px-6 py-4">{children}</div>
      </div>
    </div>,
    document.body
  )
}

// 小型确认对话框
interface ConfirmModalProps {
  open: boolean
  onClose: () => void
  onConfirm: () => void
  message: string
  confirmLabel?: string
}

export const ConfirmModal: React.FC<ConfirmModalProps> = ({
  open, onClose, onConfirm, message, confirmLabel = '确认',
}) => (
  <Modal open={open} onClose={onClose} width="max-w-xs">
    <p className="text-base text-text-primary mb-4">{message}</p>
    <div className="flex justify-end gap-2">
      <button
        onClick={onClose}
        className="px-3 py-1.5 text-sm text-text-secondary hover:bg-surface-tertiary rounded-lg transition-colors duration-50"
      >
        取消
      </button>
      <button
        onClick={() => { onConfirm(); onClose() }}
        className="px-3 py-1.5 text-sm bg-red-500 text-white rounded-lg hover:bg-red-600 transition-colors duration-50"
      >
        {confirmLabel}
      </button>
    </div>
  </Modal>
)
