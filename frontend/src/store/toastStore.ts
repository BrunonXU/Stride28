import { create } from 'zustand'

type ToastType = 'success' | 'error' | 'info'

interface ToastState {
  message: string | null
  type: ToastType
  show: (message: string, type?: ToastType) => void
  hide: () => void
}

/** 自动消失定时器 ID，模块级变量避免闭包问题 */
let timerId: ReturnType<typeof setTimeout> | null = null

export const useToastStore = create<ToastState>()((set) => ({
  message: null,
  type: 'info',

  show: (message, type = 'info') => {
    // 连续调用时重置定时器，确保每次都从头计时 3 秒
    if (timerId) clearTimeout(timerId)
    set({ message, type })
    timerId = setTimeout(() => {
      set({ message: null })
      timerId = null
    }, 3000)
  },

  hide: () => {
    if (timerId) {
      clearTimeout(timerId)
      timerId = null
    }
    set({ message: null })
  },
}))
