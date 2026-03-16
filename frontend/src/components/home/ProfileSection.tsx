import React, { useCallback } from 'react'
import type { LearnerProfile } from '../../types'

export interface ProfileSectionProps {
  expanded: boolean
  onToggle: () => void
  profile: Partial<LearnerProfile>
  onChange: (profile: Partial<LearnerProfile>) => void
}

// 与 LearnerProfileModal 保持一致的选项
const LEVEL_OPTIONS = ['零基础', '入门级', '有一定基础', '中级', '高级']
const HOURS_OPTIONS = ['30分钟以内', '1小时', '2小时', '3小时以上']

/**
 * 可折叠学习者画像区域
 * - 不含 duration 字段（由 CyclePicker 控制）
 * - 展开/折叠动画：grid-template-rows 0fr → 1fr
 * - 父组件（NewPlanModal）控制 expanded 状态和 profile 数据
 */
export const ProfileSection: React.FC<ProfileSectionProps> = ({
  expanded,
  onToggle,
  profile,
  onChange,
}) => {
  // 更新单个字段的便捷方法
  const updateField = useCallback(
    (field: keyof LearnerProfile, value: string) => {
      onChange({ ...profile, [field]: value })
    },
    [profile, onChange],
  )

  return (
    <div className="rounded-xl border border-gray-200">
      {/* 折叠头部 */}
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium
          text-text-primary hover:bg-gray-50 rounded-xl transition-colors"
      >
        <span>📋 学习者画像（选填）</span>
        <svg
          className={`w-4 h-4 text-gray-400 transition-transform duration-50 ${
            expanded ? 'rotate-90' : ''
          }`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
      </button>

      {/* 可折叠内容区 — grid-template-rows 动画 */}
      <div
        className="grid transition-[grid-template-rows] duration-300 ease-in-out"
        style={{ gridTemplateRows: expanded ? '1fr' : '0fr' }}
      >
        <div className="overflow-hidden">
          <div className="px-4 pb-4 pt-1 space-y-4">
            {/* 学习目的 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                🎯 学习目的
              </label>
              <textarea
                value={profile.goal ?? ''}
                onChange={e => updateField('goal', e.target.value)}
                placeholder="例如：准备考研、转行学编程、提升工作技能..."
                className="w-full px-3 py-2.5 border border-gray-300 rounded-xl text-sm resize-none
                  focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                rows={2}
              />
            </div>

            {/* 当前水平 — pill 选择 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                📊 当前水平
              </label>
              <div className="flex flex-wrap gap-2">
                {LEVEL_OPTIONS.map(opt => (
                  <button
                    key={opt}
                    type="button"
                    onClick={() => updateField('level', opt)}
                    className={`px-3 py-1.5 rounded-full text-sm border transition-all ${
                      profile.level === opt
                        ? 'bg-orange-50 border-blue-400 text-orange-700'
                        : 'border-gray-300 text-gray-600 hover:border-gray-400'
                    }`}
                  >
                    {opt}
                  </button>
                ))}
              </div>
            </div>

            {/* 每日可用时间 — pill 选择 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                ⏰ 每日可用时间
              </label>
              <div className="flex flex-wrap gap-2">
                {HOURS_OPTIONS.map(opt => (
                  <button
                    key={opt}
                    type="button"
                    onClick={() => updateField('dailyHours', opt)}
                    className={`px-3 py-1.5 rounded-full text-sm border transition-all ${
                      profile.dailyHours === opt
                        ? 'bg-orange-50 border-orange-400 text-orange-700'
                        : 'border-gray-300 text-gray-600 hover:border-gray-400'
                    }`}
                  >
                    {opt}
                  </button>
                ))}
              </div>
            </div>

            {/* 个人背景 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                💼 个人背景（选填）
              </label>
              <textarea
                value={profile.background ?? ''}
                onChange={e => updateField('background', e.target.value)}
                placeholder="例如：大三计算机专业、在职产品经理、自学爱好者..."
                className="w-full px-3 py-2.5 border border-gray-300 rounded-xl text-sm resize-none
                  focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                rows={2}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
