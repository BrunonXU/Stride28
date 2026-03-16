import React, { useEffect, useState } from 'react'
import { useToastStore } from '../../store/toastStore'

/** 类型 → 图标 + 颜色映射 */
const TOAST_STYLES = {
  success: {
    icon: '✓',
    bg: 'bg-green-600',
    iconBg: 'bg-green-500',
  },
  error: {
    icon: '✕',
    bg: 'bg-red-600',
    iconBg: 'bg-red-500',
  },
  info: {
    icon: 'ℹ',
    bg: 'bg-gray-700',
    iconBg: 'bg-gray-600',
  },
} as const

/**
 * 全局 Toast 提示组件
 * - 屏幕底部居中，带 fade + slide-up 动画
 * - 从 toastStore 读取状态，点击可提前关闭
 * - 挂载在应用根级别（main.tsx）
 */
export const Toast: React.FC = () => {
  const message = useToastStore((s) => s.message)
  const type = useToastStore((s) => s.type)
  const hide = useToastStore((s) => s.hide)

  // 控制动画：visible 决定是否渲染，animating 控制进出过渡
  const [visible, setVisible] = useState(false)
  const [animating, setAnimating] = useState(false)

  useEffect(() => {
    if (message) {
      // 进入：先挂载 DOM，下一帧触发动画
      setVisible(true)
      requestAnimationFrame(() => {
        requestAnimationFrame(() => setAnimating(true))
      })
    } else {
      // 退出：先播放退出动画，动画结束后卸载 DOM
      setAnimating(false)
    }
  }, [message])

  // 退出动画结束后卸载
  const handleTransitionEnd = () => {
    if (!animating) setVisible(false)
  }

  if (!visible) return null

  const style = TOAST_STYLES[type]

  return (
    <div
      role="alert"
      aria-live="assertive"
      onClick={hide}
      onTransitionEnd={handleTransitionEnd}
      className={`
        fixed bottom-6 left-1/2 z-[9999]
        flex items-center gap-2.5
        px-4 py-2.5 rounded-xl shadow-lg
        text-white text-sm font-medium
        cursor-pointer select-none
        transition-all duration-300 ease-out
        ${style.bg}
        ${animating
          ? 'opacity-100 translate-y-0 -translate-x-1/2'
          : 'opacity-0 translate-y-3 -translate-x-1/2'
        }
      `}
    >
      {/* 图标圆圈 */}
      <span
        className={`
          flex items-center justify-center
          w-5 h-5 rounded-full text-xs
          ${style.iconBg}
        `}
      >
        {style.icon}
      </span>
      {message}
    </div>
  )
}
