/**
 * useKeyboard — 全局键盘快捷键
 *
 * Ctrl/Cmd+K  → 聚焦对话输入框
 * Ctrl/Cmd+N  → 触发新建规划
 * Escape      → 关闭弹窗（由调用方传入 onEscape）
 */
import { useEffect } from 'react'

interface KeyboardOptions {
  onFocusInput?: () => void   // Ctrl/Cmd+K
  onNewPlan?: () => void      // Ctrl/Cmd+N
  onEscape?: () => void       // Escape
}

export function useKeyboard({ onFocusInput, onNewPlan, onEscape }: KeyboardOptions) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const mod = e.ctrlKey || e.metaKey

      if (mod && e.key === 'k') {
        e.preventDefault()
        onFocusInput?.()
      } else if (mod && e.key === 'n') {
        e.preventDefault()
        onNewPlan?.()
      } else if (e.key === 'Escape') {
        onEscape?.()
      }
    }

    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onFocusInput, onNewPlan, onEscape])
}
