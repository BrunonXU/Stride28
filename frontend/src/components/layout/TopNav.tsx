import React, { useState, useRef, useEffect } from 'react'

interface TopNavProps {
  planTitle?: string
  onTitleChange?: (title: string) => void
  onToggleDark?: () => void
  isDark?: boolean
  onNewPlan?: () => void
}

export const TopNav: React.FC<TopNavProps> = ({
  planTitle = '',
  onTitleChange,
  onToggleDark,
  isDark = false,
  onNewPlan,
}) => {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(planTitle)
  const [avatarOpen, setAvatarOpen] = useState(false)
  const avatarRef = useRef<HTMLDivElement>(null)

  useEffect(() => { setDraft(planTitle) }, [planTitle])

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (avatarRef.current && !avatarRef.current.contains(e.target as Node)) setAvatarOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const commitEdit = () => {
    setEditing(false)
    if (draft.trim() && draft.trim() !== planTitle && onTitleChange) {
      onTitleChange(draft.trim())
    }
  }

  return (
    <header className="h-12 bg-transparent flex items-center justify-between px-2 z-10 flex-shrink-0">
      {/* 左侧区域：Logo & 标题 */}
      <div className="flex items-center gap-4 min-w-0 flex-shrink-0">
        <button onClick={() => window.location.href = '/'} className="flex items-center gap-2 hover:opacity-80 transition-opacity">
          <img src="/logo.svg" alt="Stride28" className="h-8" />
        </button>

        {planTitle && (
          <div className="flex items-center gap-4 pl-2 h-6">
            {editing ? (
              <input
                autoFocus
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onBlur={commitEdit}
                onKeyDown={(e) => { if (e.key === 'Enter') commitEdit(); if (e.key === 'Escape') { setDraft(planTitle); setEditing(false) } }}
                className="text-2xl font-semibold text-[#202124] dark:text-dark-text bg-transparent border-b border-primary outline-none focus:border-b-2 focus:border-orange-500 min-w-[300px] px-1"
                aria-label="编辑规划名称"
              />
            ) : (
              <button
                onClick={() => { setDraft(planTitle); setEditing(true) }}
                className="text-2xl font-semibold text-[#202124] dark:text-dark-text hover:text-black truncate max-w-xl transition-colors duration-50 px-1 hover:bg-[#E8EAED] rounded-md"
                aria-label="点击编辑规划名称"
              >
                {planTitle}
              </button>
            )}
          </div>
        )}
      </div>

      <div className="flex items-center gap-3 flex-shrink-0 mr-6">
        {/* 新建规划按钮 */}
        {onNewPlan && (
          <button
            onClick={onNewPlan}
            aria-label="新建学习规划"
            className="h-9 px-6 rounded-full bg-[#1A1A18] text-white text-sm font-medium hover:bg-[#2D2D2B] active:scale-95 transition-all duration-50 shadow-sm whitespace-nowrap"
          >
            + 新建学习规划
          </button>
        )}
        {/* 头像菜单区 */}
        <div ref={avatarRef} className="relative">
          <button
            onClick={() => setAvatarOpen(!avatarOpen)}
            aria-label="用户菜单"
            className="w-8 h-8 flex items-center justify-center rounded-full bg-[#D97757] text-white text-xs font-medium hover:shadow-md transition-shadow duration-50"
          >
            U
          </button>
          {avatarOpen && (
            <div className="absolute right-0 top-10 z-50 bg-white dark:bg-dark-surface border border-[#E0E0E0] dark:border-dark-border rounded-xl shadow-lg py-1.5 min-w-[200px]">
              <div className="px-4 py-2 text-xs text-[#9AA0A6] font-medium">用户</div>
              <div className="px-4 py-2 text-sm text-[#3C4043] dark:text-dark-text flex items-center gap-2">
                👤 本地用户
              </div>
              <div className="border-t border-[#E8EAED] dark:border-dark-border my-1" />
              <button
                onClick={() => { onToggleDark?.(); setAvatarOpen(false) }}
                className="w-full text-left px-4 py-2 text-sm text-[#3C4043] dark:text-dark-text hover:bg-[#F1F3F4] dark:hover:bg-dark-bg flex items-center gap-2 transition-colors duration-50"
              >
                {isDark ? '☀️ 浅色模式' : '🌙 深色模式'}
              </button>
              <div className="border-t border-[#E8EAED] dark:border-dark-border my-1" />
              <div className="px-4 py-1.5 text-xs text-[#9AA0A6]">版本 0.1.0</div>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
