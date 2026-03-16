/**
 * DayDetail — Timeline 下方展开的天详情面板
 * 展示选中天的任务列表，支持 checkbox toggle + 后端持久化，
 * 「完成今天」按钮含 3 种 disabled 状态，完成后触发 day-summary 生成。
 *
 * 替代 TodayTasksBar 的任务交互逻辑，区别在于：
 * - 可展示任意选中天（不限 currentDay）
 * - 使用 completeDayOptimistic 乐观更新 + 失败回滚
 * - 更完善的 disabled 状态提示
 */
import React, { useCallback, useState } from 'react'
import { useStudioStore } from '../../store/studioStore'
import { useToastStore } from '../../store/toastStore'

interface DayDetailProps {
  planId: string
  dayNumber: number
}

// 任务类型 → emoji 映射
const TASK_TYPE_ICON: Record<string, string> = {
  reading: '📖',
  video: '🎬',
  exercise: '✏️',
  flashcard: '🃏',
}

export const DayDetail: React.FC<DayDetailProps> = ({ planId, dayNumber }) => {
  const {
    allDays,
    toggleTask,
    completeDayOptimistic,
    addGeneratedContent,
    activePlanId,
  } = useStudioStore()
  const toast = useToastStore()
  const [completing, setCompleting] = useState(false)

  const day = allDays.find(d => d.dayNumber === dayNumber)

  // 持久化 task toggle 到后端（与 TodayTasksBar 逻辑一致）
  const handleToggleTask = useCallback((taskIndex: number) => {
    toggleTask(dayNumber, taskIndex)

    // 读取 toggle 后的最新状态持久化
    const { allDays: latestDays, activePlanId: pid } = useStudioStore.getState()
    const updatedDay = latestDays.find(d => d.dayNumber === dayNumber)
    const resolvedPlanId = planId || pid
    if (resolvedPlanId && updatedDay) {
      fetch(`/api/plans/${resolvedPlanId}/progress/${dayNumber}/tasks`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tasks: updatedDay.tasks }),
      }).catch(() => {
        toast.show('任务状态保存失败', 'error')
      })
    }
  }, [dayNumber, planId, toggleTask, toast])

  // 完成当天：乐观更新 + day-summary 生成
  const handleCompleteDay = useCallback(async () => {
    if (completing) return
    setCompleting(true)
    const resolvedPlanId = planId || activePlanId

    try {
      await completeDayOptimistic(resolvedPlanId, dayNumber)
    } catch {
      // completeDayOptimistic 内部已回滚，这里只需 toast
      toast.show('保存失败，请重试', 'error')
      setCompleting(false)
      return
    }

    // 完成成功，触发 day-summary 生成
    try {
      const { allDays: latestDays } = useStudioStore.getState()
      const res = await fetch('/api/studio/day-summary', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          planId: resolvedPlanId,
          allDays: latestDays,
          currentDayNumber: dayNumber,
        }),
      })
      if (res.ok) {
        const data = await res.json()
        addGeneratedContent({
          id: `day-summary-${Date.now()}`,
          type: 'day-summary',
          title: data.title || '今日总结',
          content: data.content,
          createdAt: data.createdAt || new Date().toISOString(),
        })
      }
    } catch {
      // day-summary 生成失败不影响完成状态，静默处理
    } finally {
      setCompleting(false)
    }
  }, [completing, planId, activePlanId, dayNumber, completeDayOptimistic, addGeneratedContent, toast])

  // ─── 空状态 ───
  if (!day) return null

  const tasks = day.tasks
  const allTasksDone = tasks.length > 0 && tasks.every(t => t.completed)
  const completedCount = tasks.filter(t => t.completed).length

  // 按钮状态判断
  const getButtonState = () => {
    if (day.completed) return { type: 'done' as const, label: '✅ 已完成', disabled: true }
    if (tasks.length === 0) return { type: 'empty' as const, label: '暂无任务', disabled: true }
    if (!allTasksDone) return { type: 'pending' as const, label: '还有未完成的任务', disabled: true }
    return { type: 'ready' as const, label: '完成今天 ✅', disabled: false }
  }

  const buttonState = getButtonState()

  return (
    <div
      className="px-6 py-4 border-b border-gray-200 bg-gradient-to-b from-blue-50/30 to-white"
      style={{ animation: 'daydetail-fade-in 200ms ease-out' }}
      data-testid="day-detail"
    >
      <style>{`
        @keyframes daydetail-fade-in {
          from { opacity: 0; transform: translateY(-8px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>

      {/* 标题行 */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-800">
          📅 Day {day.dayNumber}: {day.title}
        </h3>
        {tasks.length > 0 && (
          <span className="text-xs text-gray-400">
            {completedCount}/{tasks.length}
          </span>
        )}
      </div>

      {/* 任务列表 */}
      {tasks.length > 0 ? (
        <ul className="space-y-2 mb-4" role="list" aria-label={`Day ${dayNumber} 任务列表`}>
          {tasks.map((task, index) => (
            <li key={task.id} className="flex items-center gap-2.5 group">
              <input
                type="checkbox"
                checked={task.completed}
                onChange={() => handleToggleTask(index)}
                disabled={day.completed}
                className="w-4 h-4 rounded border-gray-300 text-blue-500 focus:ring-blue-400 focus:ring-offset-0 cursor-pointer disabled:cursor-default disabled:opacity-60"
                aria-label={`${task.title}${task.completed ? '（已完成）' : ''}`}
                data-testid={`task-checkbox-${index}`}
              />
              <span className="text-sm select-none" title={task.type}>
                {TASK_TYPE_ICON[task.type] || '📌'}
              </span>
              <span
                className={`text-sm transition-colors ${
                  task.completed
                    ? 'line-through text-gray-400'
                    : 'text-gray-700 group-hover:text-gray-900'
                }`}
              >
                {task.title}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-gray-400 mb-4">暂无任务内容</p>
      )}

      {/* 完成按钮 */}
      <button
        type="button"
        onClick={handleCompleteDay}
        disabled={buttonState.disabled || completing}
        className={`w-full py-2 text-sm font-medium rounded-lg transition-all ${
          buttonState.type === 'done'
            ? 'bg-green-50 text-green-600 border border-green-200 cursor-default'
            : buttonState.type === 'ready'
              ? 'bg-green-500 text-white hover:bg-green-600 active:bg-green-700 shadow-sm'
              : 'bg-gray-100 text-gray-400 cursor-not-allowed'
        }`}
        data-testid="complete-day-btn"
        aria-label={buttonState.label}
      >
        {completing ? '保存中...' : buttonState.label}
      </button>
    </div>
  )
}
