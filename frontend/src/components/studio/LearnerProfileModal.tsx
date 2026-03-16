import React, { useState } from 'react'
import { createPortal } from 'react-dom'
import { ConfirmDialog } from '../ui/ConfirmDialog'
import { useStudioStore } from '../../store/studioStore'
import { useToastStore } from '../../store/toastStore'
import type { LearnerProfile } from '../../types'

interface Props {
  initial?: LearnerProfile | null
  onSave: (profile: LearnerProfile) => void
  onSkip: () => void
}

const LEVEL_OPTIONS = ['零基础', '入门级', '有一定基础', '中级', '高级']
const HOURS_OPTIONS = ['30分钟以内', '1小时', '2小时', '3小时以上']

export const LearnerProfileModal: React.FC<Props> = ({ initial, onSave, onSkip }) => {
  const [goal, setGoal] = useState(initial?.goal || '')
  const [duration, setDuration] = useState<number>(
    typeof initial?.duration === 'number' ? initial.duration : 14
  )
  const [level, setLevel] = useState(initial?.level || '')
  const [background, setBackground] = useState(initial?.background || '')
  const [dailyHours, setDailyHours] = useState(initial?.dailyHours || '')

  // 周期变更确认
  const [showConfirm, setShowConfirm] = useState(false)
  const [confirmMessage, setConfirmMessage] = useState('')

  const { allDays, activePlanId, regeneratePlan, timelineStatus } = useStudioStore()
  const toast = useToastStore()

  const isRegenerating = timelineStatus === 'regenerating'
  const originalDuration = typeof initial?.duration === 'number' ? initial.duration : 14
  const durationChanged = duration !== originalDuration

  const handleSave = () => {
    // 周期变更 + 已有学习计划 → 弹确认
    if (durationChanged && allDays.length > 0) {
      const completedCount = allDays.filter(d => d.completed).length

      if (duration <= completedCount) {
        setConfirmMessage(
          `新周期（${duration}天）≤ 已完成天数（${completedCount}天），多余的已完成天数将被截断。确认修改？`
        )
      } else {
        setConfirmMessage(
          '修改学习周期将重新生成未完成的学习计划，已完成的天数会保留。确认修改？'
        )
      }
      setShowConfirm(true)
      return
    }

    doSave()
  }

  const doSave = async () => {
    const profileData: LearnerProfile = { goal, duration, level, background, dailyHours }
    const needRegenerate = durationChanged && allDays.length > 0

    onSave(profileData)

    if (needRegenerate) {
      const pid = activePlanId
      if (pid) {
        try {
          await regeneratePlan(pid, duration)
          toast.show('学习计划已重新生成', 'success')
        } catch {
          toast.show('重新生成失败，已恢复原计划', 'error')
        }
      }
    }
  }

  const canSave = goal.trim() || level.trim()

  return createPortal(
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40" onClick={onSkip}>
      <div className="bg-white dark:bg-dark-surface rounded-2xl shadow-2xl w-[520px] max-h-[85vh] overflow-y-auto"
        onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="px-6 pt-6 pb-2">
          <h2 className="text-lg font-semibold text-[#202124]">📋 学习者画像</h2>
          <p className="text-sm text-gray-500 mt-1">
            填写你的学习背景，AI 将为你生成个性化内容
          </p>
        </div>

        <div className="px-6 py-4 space-y-5">
          {/* 学习目的 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">🎯 学习目的</label>
            <textarea value={goal} onChange={e => setGoal(e.target.value)}
              placeholder="例如：准备考研、转行学编程、提升工作技能..."
              className="w-full px-3 py-2.5 border border-gray-300 rounded-xl text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              rows={2} />
          </div>

          {/* 当前水平 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">📊 当前水平</label>
            <div className="flex flex-wrap gap-2">
              {LEVEL_OPTIONS.map(opt => (
                <button key={opt} onClick={() => setLevel(opt)}
                  className={`px-3 py-1.5 rounded-full text-sm border transition-all ${
                    level === opt
                      ? 'bg-orange-50 border-blue-400 text-orange-700'
                      : 'border-gray-300 text-gray-600 hover:border-gray-400'
                  }`}>{opt}</button>
              ))}
            </div>
          </div>

          {/* 学习周期 — stepper */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">📅 学习周期</label>
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => setDuration(v => Math.max(3, v - 1))}
                disabled={duration <= 3 || isRegenerating}
                className="w-8 h-8 rounded-lg border border-gray-300 flex items-center justify-center text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                aria-label="减少天数"
              >
                −
              </button>
              <span className="text-2xl font-bold text-gray-900 w-10 text-center tabular-nums">
                {duration}
              </span>
              <button
                type="button"
                onClick={() => setDuration(v => Math.min(28, v + 1))}
                disabled={duration >= 28 || isRegenerating}
                className="w-8 h-8 rounded-lg border border-gray-300 flex items-center justify-center text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                aria-label="增加天数"
              >
                +
              </button>
              <span className="text-sm text-gray-500">天</span>
              {durationChanged && allDays.length > 0 && (
                <span className="text-xs text-amber-600 ml-1">⚠ 将重新生成计划</span>
              )}
            </div>
          </div>

          {/* 每日可用时间 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">⏰ 每日可用时间</label>
            <div className="flex flex-wrap gap-2">
              {HOURS_OPTIONS.map(opt => (
                <button key={opt} onClick={() => setDailyHours(opt)}
                  className={`px-3 py-1.5 rounded-full text-sm border transition-all ${
                    dailyHours === opt
                      ? 'bg-orange-50 border-orange-400 text-orange-700'
                      : 'border-gray-300 text-gray-600 hover:border-gray-400'
                  }`}>{opt}</button>
              ))}
            </div>
          </div>

          {/* 个人背景 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">💼 个人背景（选填）</label>
            <textarea value={background} onChange={e => setBackground(e.target.value)}
              placeholder="例如：大三计算机专业、在职产品经理、自学爱好者..."
              className="w-full px-3 py-2.5 border border-gray-300 rounded-xl text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              rows={2} />
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 flex justify-end gap-3 border-t border-gray-100">
          <button onClick={onSkip}
            className="px-4 py-2 text-sm text-gray-500 hover:text-gray-700 transition-colors">
            跳过
          </button>
          <button onClick={handleSave} disabled={!canSave || isRegenerating}
            className={`px-5 py-2 rounded-full text-sm font-medium transition-all ${
              canSave && !isRegenerating
                ? 'bg-blue-600 text-white hover:bg-blue-700'
                : 'bg-gray-200 text-gray-400 cursor-not-allowed'
            }`}>
            {isRegenerating ? '生成中...' : '保存并继续'}
          </button>
        </div>
      </div>

      {/* 周期变更确认对话框 */}
      <ConfirmDialog
        open={showConfirm}
        title="修改学习周期"
        message={confirmMessage}
        confirmText="确认修改"
        variant="danger"
        onConfirm={() => { setShowConfirm(false); doSave() }}
        onCancel={() => setShowConfirm(false)}
      />
    </div>,
    document.body
  )
}
