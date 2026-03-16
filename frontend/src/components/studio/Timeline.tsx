import React, { useRef, useEffect, useCallback, useState } from 'react'
import { useStudioStore } from '../../store/studioStore'
import type { DayProgress } from '../../types'

// ─── 类型定义 ───

interface TimelineProps {
  planId: string
  /** inline 模式：去掉外层 border/padding，由父级控制布局 */
  inline?: boolean
}

interface DayNodeProps {
  day: DayProgress
  isSelected: boolean
  isCurrent: boolean
  isRegeneratingSkeleton: boolean
  animationDelay: number
  onClick: () => void
}

// ─── 动画样式 ───

const TIMELINE_STYLES = `
@keyframes timeline-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
@keyframes timeline-fade-in {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes timeline-current-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(217, 119, 87, 0.35); }
  50% { box-shadow: 0 0 0 5px rgba(217, 119, 87, 0); }
}
`

// ─── DayNode ───

const DayNode: React.FC<DayNodeProps> = React.memo(({
  day, isSelected, isCurrent, isRegeneratingSkeleton, animationDelay, onClick,
}) => {
  if (isRegeneratingSkeleton) {
    return (
      <div
        className="flex items-center justify-center flex-shrink-0"
        style={{ width: 48 }}
        data-testid={`day-node-skeleton-${day.dayNumber}`}
      >
        <div
          className="w-6 h-6 rounded-full bg-gray-200"
          style={{ animation: 'timeline-pulse 1.5s ease-in-out infinite' }}
        />
      </div>
    )
  }

  return (
    <button
      type="button"
      className="flex items-center justify-center flex-shrink-0 group focus:outline-none"
      style={{
        width: 48,
        animation: animationDelay > 0
          ? `timeline-fade-in 300ms ease-out ${animationDelay}ms both`
          : undefined,
      }}
      onClick={onClick}
      data-testid={`day-node-${day.dayNumber}`}
      data-day={day.dayNumber}
      aria-label={`Day ${day.dayNumber}: ${day.title}${day.completed ? ' (已完成)' : ''}${isSelected ? ' (已选中)' : ''}`}
      aria-current={isSelected ? 'true' : undefined}
    >
      {day.completed ? (
        /* 已完成：terracotta 实心圆 + 白色 ✓ */
        <div
          className={`w-6 h-6 rounded-full bg-[#D97757] flex items-center justify-center transition-all ${
            isSelected ? 'ring-2 ring-[#D97757]/40 ring-offset-1' : ''
          }`}
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        </div>
      ) : (
        /* 未完成：圆形 + 数字 */
        <div
          className={`w-7 h-7 rounded-full border-2 flex items-center justify-center transition-all ${
            isSelected
              ? 'border-[#D97757] bg-[#FDF6F3] ring-2 ring-[#D97757]/20'
              : 'border-gray-300 bg-white group-hover:border-gray-400'
          }`}
          style={isCurrent ? { animation: 'timeline-current-pulse 2s ease-in-out infinite' } : undefined}
        >
          <span className={`text-[11px] font-medium ${isSelected ? 'text-[#D97757]' : 'text-gray-400'}`}>
            {day.dayNumber}
          </span>
        </div>
      )}
    </button>
  )
})

DayNode.displayName = 'DayNode'

// ─── 连接线 ───

interface ConnectorProps {
  leftCompleted: boolean
  rightCompleted: boolean
  isSkeleton: boolean
}

const Connector: React.FC<ConnectorProps> = React.memo(({ leftCompleted, rightCompleted, isSkeleton }) => {
  const colorClass = isSkeleton
    ? 'bg-gray-200'
    : leftCompleted && rightCompleted
      ? 'bg-[#D97757]/50'
      : 'bg-gray-200'

  return (
    <div
      className={`h-px flex-shrink-0 ${colorClass}`}
      style={{
        width: 16,
        animation: isSkeleton ? 'timeline-pulse 1.5s ease-in-out infinite' : undefined,
      }}
      data-testid="connector"
    />
  )
})

Connector.displayName = 'Connector'

// ─── Loading Skeleton ───

const LoadingSkeleton: React.FC = () => (
  <div className="flex items-center gap-0 px-3 py-3" data-testid="timeline-loading">
    {Array.from({ length: 7 }).map((_, i) => (
      <React.Fragment key={i}>
        {i > 0 && (
          <div
            className="h-px bg-gray-200 flex-shrink-0"
            style={{ width: 16, animation: 'timeline-pulse 1.5s ease-in-out infinite', animationDelay: `${i * 80}ms` }}
          />
        )}
        <div className="flex items-center justify-center flex-shrink-0" style={{ width: 48 }}>
          <div
            className="w-6 h-6 rounded-full bg-gray-200"
            style={{ animation: 'timeline-pulse 1.5s ease-in-out infinite', animationDelay: `${i * 80}ms` }}
          />
        </div>
      </React.Fragment>
    ))}
  </div>
)

// ─── Empty / Celebration ───

const EmptyState: React.FC = () => (
  <div className="flex items-center justify-center px-6 py-6 text-center" data-testid="timeline-empty">
    <div className="flex flex-col items-center gap-1.5">
      <span className="text-xl">📅</span>
      <p className="text-sm text-gray-500">点击「学习计划」生成每日计划</p>
    </div>
  </div>
)

const CelebrationBanner: React.FC = () => (
  <div className="text-center py-1 text-xs font-medium text-[#D97757]" data-testid="timeline-celebration">
    🎉 学习计划完成
  </div>
)

// ─── 主组件 ───

export const Timeline: React.FC<TimelineProps> = ({ planId: _planId, inline = false }) => {
  const scrollRef = useRef<HTMLDivElement>(null)
  const { allDays, currentDay, timelineStatus, selectedDay, setSelectedDay } = useStudioStore()

  // 追踪滚动位置，控制左右渐隐遮罩
  const [fadeEdge, setFadeEdge] = useState<'none' | 'left' | 'right' | 'both'>('none')

  const updateFadeEdge = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    const { scrollLeft, scrollWidth, clientWidth } = el
    const hasLeft = scrollLeft > 2
    const hasRight = scrollLeft + clientWidth < scrollWidth - 2
    setFadeEdge(hasLeft && hasRight ? 'both' : hasLeft ? 'left' : hasRight ? 'right' : 'none')
  }, [])

  const handleWheel = useCallback((e: WheelEvent) => {
    if (scrollRef.current) {
      e.preventDefault()
      scrollRef.current.scrollLeft += e.deltaY * 1.7
    }
  }, [])

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    el.addEventListener('wheel', handleWheel, { passive: false })
    el.addEventListener('scroll', updateFadeEdge, { passive: true })
    // 初始检测
    updateFadeEdge()
    const ro = new ResizeObserver(updateFadeEdge)
    ro.observe(el)
    return () => {
      el.removeEventListener('wheel', handleWheel)
      el.removeEventListener('scroll', updateFadeEdge)
      ro.disconnect()
    }
  }, [handleWheel, updateFadeEdge])

  useEffect(() => {
    if (timelineStatus !== 'idle' || !currentDay) return
    const timer = setTimeout(() => {
      const el = scrollRef.current
      if (!el) return
      const target = el.querySelector(`[data-day="${currentDay.dayNumber}"]`)
      if (target) {
        target.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' })
      }
      // scrollIntoView 后更新遮罩
      setTimeout(updateFadeEdge, 350)
    }, 100)
    return () => clearTimeout(timer)
  }, [allDays, currentDay, timelineStatus, updateFadeEdge])

  const allCompleted = allDays.length > 0 && allDays.every(d => d.completed)
  const isRegenerating = timelineStatus === 'regenerating'

  const wrapperClass = inline ? '' : 'border-b border-gray-200 bg-white'
  const scrollClass = inline ? 'flex items-center overflow-x-auto py-1 scrollbar-none' : 'flex items-center overflow-x-auto px-3 py-2.5 scrollbar-none'

  // mask-image 渐隐遮罩：左右各 32px 渐变
  const maskImage = fadeEdge === 'both'
    ? 'linear-gradient(to right, transparent, black 32px, black calc(100% - 32px), transparent)'
    : fadeEdge === 'left'
      ? 'linear-gradient(to right, transparent, black 32px)'
      : fadeEdge === 'right'
        ? 'linear-gradient(to left, transparent, black 32px)'
        : undefined

  if (timelineStatus === 'loading') {
    return <div className={wrapperClass}><style>{TIMELINE_STYLES}</style><LoadingSkeleton /></div>
  }

  if (timelineStatus === 'empty' || allDays.length === 0) {
    return inline ? null : <div className={wrapperClass}><EmptyState /></div>
  }

  return (
    <div className={wrapperClass} data-testid="timeline">
      <style>{TIMELINE_STYLES}</style>
      {allCompleted && !inline && <CelebrationBanner />}
      <div
        ref={scrollRef}
        className={scrollClass}
        style={{ scrollBehavior: 'smooth', whiteSpace: 'nowrap' }}
        role="tablist"
        aria-label="学习进度时间线"
      >
        {allDays.map((day, index) => {
          const isSelected = selectedDay === day.dayNumber
          const isCurrent = currentDay?.dayNumber === day.dayNumber
          const isSkeleton = isRegenerating && !day.completed
          return (
            <React.Fragment key={day.dayNumber}>
              {index > 0 && (
                <Connector
                  leftCompleted={allDays[index - 1].completed}
                  rightCompleted={day.completed}
                  isSkeleton={isRegenerating && (!allDays[index - 1].completed || !day.completed)}
                />
              )}
              <DayNode
                day={day}
                isSelected={isSelected}
                isCurrent={isCurrent}
                isRegeneratingSkeleton={isSkeleton}
                animationDelay={0}
                onClick={() => setSelectedDay(isSelected ? null : day.dayNumber)}
              />
            </React.Fragment>
          )
        })}
      </div>
      {isRegenerating && !inline && (
        <div
          className="text-center pb-2 text-xs text-gray-400"
          style={{ animation: 'timeline-pulse 1.5s ease-in-out infinite' }}
          data-testid="timeline-regenerating-hint"
        >
          正在重新规划...
        </div>
      )}
    </div>
  )
}
