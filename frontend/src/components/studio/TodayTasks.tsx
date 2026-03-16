import React from 'react'
import type { DayProgress } from '../../types'

interface TodayTasksProps {
  currentDay: DayProgress | null
  onTaskToggle: (taskIndex: number) => void
  onCompleteDay: (dayNumber: number) => void
}

export const TodayTasks: React.FC<TodayTasksProps> = ({
  currentDay, onTaskToggle, onCompleteDay,
}) => {
  const allDone = currentDay?.tasks.every(t => t.completed) ?? false

  return (
    <div className="bg-white rounded-xl border border-[#DADCE0] shadow-sm p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-semibold text-[#202124] flex items-center gap-1.5">
          🎯 今日任务
        </span>
        {currentDay && (
          <span className="text-xs text-[#5F6368] bg-[#F1F3F4] px-2 py-0.5 rounded-full">
            Day {currentDay.dayNumber}
          </span>
        )}
      </div>

      {!currentDay ? (
        <p className="text-sm text-[#5F6368] py-1">生成学习计划后，今日任务将自动出现</p>
      ) : allDone ? (
        <p className="text-sm text-green-600 font-medium py-1">🎉 今日任务全部完成！</p>
      ) : (
        <>
          <ul className="flex flex-col gap-1.5 mb-3">
            {currentDay.tasks.map((task, i) => (
              <li key={task.id} className="flex items-center gap-3 min-h-[36px]">
                <input
                  type="checkbox"
                  checked={task.completed}
                  onChange={() => onTaskToggle(i)}
                  className="accent-[#D97757] w-4 h-4 flex-shrink-0"
                  aria-label={`标记完成：${task.title}`}
                />
                <span className={`text-sm flex-1 ${task.completed ? 'line-through text-[#9AA0A6]' : 'text-[#202124]'}`}>
                  {task.type === 'video' ? '看: ' : task.type === 'reading' ? '读: ' : ''}
                  {task.title}
                  {task.qualityScore && (
                    <span className="text-[#F97316] ml-1.5 font-medium">
                      ⭐{(task.qualityScore * 10).toFixed(1)}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
          <button
            onClick={() => onCompleteDay(currentDay.dayNumber)}
            disabled={!allDone}
            className={`text-sm transition-colors duration-50 ${
              allDone ? 'text-[#D97757] hover:underline cursor-pointer' : 'text-[#9AA0A6] cursor-not-allowed'
            }`}
          >
            完成 Day {currentDay.dayNumber} →
          </button>
        </>
      )}
    </div>
  )
}
