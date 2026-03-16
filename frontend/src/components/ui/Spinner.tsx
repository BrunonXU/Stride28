import React from 'react'

interface SpinnerProps {
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

export const Spinner: React.FC<SpinnerProps> = ({ size = 'md', className = '' }) => {
  const sizes = { sm: 'h-4 w-4', md: 'h-6 w-6', lg: 'h-8 w-8' }

  return (
    <svg
      className={`animate-spin text-primary ${sizes[size]} ${className}`}
      fill="none"
      viewBox="0 0 24 24"
      aria-label="加载中"
    >
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  )
}

// 脉冲点加载动画（对话等待时使用）
export const TypingIndicator: React.FC = () => (
  <div className="flex gap-1 items-center py-1" aria-label="AI 正在输入">
    {[0, 150, 300].map((delay) => (
      <span
        key={delay}
        className="w-2 h-2 bg-text-secondary rounded-full animate-bounce"
        style={{ animationDelay: `${delay}ms` }}
      />
    ))}
  </div>
)
