import React, { useMemo, useCallback } from 'react'

export interface CyclePickerProps {
  value: number
  onChange: (days: number) => void
}

/** 策略区间定义 */
interface Strategy {
  emoji: string
  label: string
  desc: string
}

const MIN_DAYS = 3
const MAX_DAYS = 28

/** 根据天数区间返回对应的学习策略 */
function getStrategy(days: number): Strategy {
  if (days <= 7) {
    return { emoji: '⚡', label: '密集冲刺模式', desc: '短期集中突破核心内容' }
  }
  if (days <= 14) {
    return { emoji: '🚀', label: '稳步推进模式', desc: '适合系统性学习，每天安排适量任务' }
  }
  return { emoji: '🏔️', label: '深度学习模式', desc: '包含复习日和实践日，深入掌握' }
}

/**
 * 学习周期选择器
 * - 原生 range input（3-28 天），键盘左右箭头原生支持
 * - 中心数字高亮 + 策略文案动态切换
 * - 自定义 slider 样式：filled track + 圆形 thumb
 */
export const CyclePicker: React.FC<CyclePickerProps> = ({ value, onChange }) => {
  const strategy = useMemo(() => getStrategy(value), [value])

  // slider 填充百分比，用于 CSS 渐变背景
  const fillPercent = ((value - MIN_DAYS) / (MAX_DAYS - MIN_DAYS)) * 100

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      onChange(Number(e.target.value))
    },
    [onChange],
  )

  return (
    <div className="space-y-3">
      {/* 标题 */}
      <p className="text-sm font-medium text-text-primary">📅 学习周期</p>

      {/* 中心数字 */}
      <div className="flex items-baseline justify-center gap-1">
        <span className="text-3xl font-bold text-primary tabular-nums">
          {value}
        </span>
        <span className="text-sm text-text-secondary">天</span>
      </div>

      {/* Slider */}
      <div className="flex items-center gap-3">
        <span className="text-xs text-text-secondary tabular-nums w-5 text-right">
          {MIN_DAYS}
        </span>
        <input
          type="range"
          min={MIN_DAYS}
          max={MAX_DAYS}
          step={1}
          value={value}
          onChange={handleChange}
          aria-label="学习周期天数"
          aria-valuemin={MIN_DAYS}
          aria-valuemax={MAX_DAYS}
          aria-valuenow={value}
          className="cycle-slider flex-1 h-1.5 rounded-full appearance-none cursor-pointer outline-none
            focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
          style={{
            background: `linear-gradient(to right, #1A73E8 0%, #1A73E8 ${fillPercent}%, #DADCE0 ${fillPercent}%, #DADCE0 100%)`,
          }}
        />
        <span className="text-xs text-text-secondary tabular-nums w-5">
          {MAX_DAYS}
        </span>
      </div>

      {/* 策略文案 — 带淡入过渡 */}
      <div
        key={strategy.label}
        className="text-center animate-fade-in"
      >
        <p className="text-sm font-medium text-text-primary">
          {strategy.emoji} {strategy.label}
        </p>
        <p className="text-xs text-text-secondary mt-0.5">
          {strategy.desc}
        </p>
      </div>
    </div>
  )
}
