/**
 * SearchProgress — 搜索进度指示器（共享组件）
 *
 * 用于聊天区和侧边栏搜索面板，展示多阶段搜索进度。
 * 5 阶段漏斗：搜索 → 初筛 → 提取 → 评估 → 完成
 */
import React from 'react'

export type SearchProgressStage = 'searching' | 'filtering' | 'extracting' | 'evaluating' | 'done' | 'error' | 'idle'

interface SearchProgressProps {
  stage: SearchProgressStage
  message?: string
  /** 紧凑模式（用于聊天气泡内） */
  compact?: boolean
}

const STAGES: { key: SearchProgressStage; label: string; icon: string }[] = [
  { key: 'searching', label: '搜索', icon: '🔍' },
  { key: 'filtering', label: '初筛', icon: '📊' },
  { key: 'extracting', label: '提取', icon: '📄' },
  { key: 'evaluating', label: '评估', icon: '🤖' },
]

function getStageIndex(stage: SearchProgressStage): number {
  const idx = STAGES.findIndex(s => s.key === stage)
  return idx >= 0 ? idx : -1
}

export const SearchProgress: React.FC<SearchProgressProps> = ({ stage, message, compact }) => {
  if (stage === 'idle' || stage === 'done') return null

  const currentIdx = getStageIndex(stage)

  if (compact) {
    return (
      <div className="flex items-center gap-3 px-4 py-3 rounded-2xl bg-[#FFF7ED] border border-[#F2DFD3]">
        {/* 阶段点 */}
        <div className="flex items-center gap-1.5">
          {STAGES.map((s, i) => (
            <div key={s.key} className="flex items-center gap-1.5">
              <div
                className={`w-2 h-2 rounded-full transition-all duration-300 ${
                  i < currentIdx ? 'bg-[#D97757]'
                  : i === currentIdx ? 'bg-[#D97757] animate-pulse ring-2 ring-[#D97757]/30'
                  : 'bg-[#E0E0E0]'
                }`}
              />
              {i < STAGES.length - 1 && (
                <div className={`w-3 h-px ${i < currentIdx ? 'bg-[#D97757]' : 'bg-[#E0E0E0]'}`} />
              )}
            </div>
          ))}
        </div>
        {/* 状态文字 */}
        <span className="text-sm text-[#D97757] truncate">{message || STAGES[currentIdx]?.label || '搜索中...'}</span>
      </div>
    )
  }

  // 完整模式（侧边栏）
  return (
    <div className="flex flex-col gap-2 py-2">
      {/* 阶段步骤条 */}
      <div className="flex items-center gap-1">
        {STAGES.map((s, i) => (
          <React.Fragment key={s.key}>
            <div className="flex flex-col items-center gap-1 flex-1">
              <div
                className={`w-7 h-7 rounded-full flex items-center justify-center text-xs transition-all duration-300 ${
                  i < currentIdx
                    ? 'bg-[#D97757] text-white'
                    : i === currentIdx
                    ? 'bg-[#FFF7ED] border-2 border-[#D97757] text-[#D97757] animate-pulse'
                    : 'bg-[#F1F3F4] text-[#9AA0A6] border border-[#E0E0E0]'
                }`}
              >
                {i < currentIdx ? '✓' : s.icon}
              </div>
              <span className={`text-[10px] leading-tight ${
                i <= currentIdx ? 'text-[#D97757] font-medium' : 'text-[#9AA0A6]'
              }`}>
                {s.label}
              </span>
            </div>
            {i < STAGES.length - 1 && (
              <div className={`h-px flex-1 mt-[-14px] ${i < currentIdx ? 'bg-[#D97757]' : 'bg-[#E0E0E0]'}`} />
            )}
          </React.Fragment>
        ))}
      </div>
      {/* 状态消息 */}
      {message && (
        <div className="text-xs text-[#5F6368] text-center">{message}</div>
      )}
    </div>
  )
}
