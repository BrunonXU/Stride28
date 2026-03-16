import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { LearningPlan } from '../../types'

const COVER_COLORS = [
  '#F2DFD3', '#FFF7ED', '#F0FDF4', '#FDF4FF', '#FFF1F2', '#F0F9FF',
]
const COVER_ICONS = ['📚', '🧠', '💡', '🔬', '🎯', '⚡']

interface PlanCardProps {
  plan: LearningPlan
  onRename: (id: string) => void
  onDelete: (id: string) => void
}

export const PlanCard: React.FC<PlanCardProps> = ({ plan, onRename, onDelete }) => {
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const idx = parseInt(plan.id, 36) % COVER_COLORS.length
  const coverColor = COVER_COLORS[idx] ?? COVER_COLORS[0]
  const coverIcon = COVER_ICONS[idx] ?? '📚'

  const formatDate = (iso: string) =>
    new Date(iso).toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })

  return (
    <div
      className="relative rounded-2xl border border-[#E5E5E5] shadow-sm hover:shadow-md hover:-translate-y-1 transition-all duration-50 cursor-pointer overflow-hidden group bg-white"
      onClick={() => navigate(`/workspace/${plan.id}`)}
    >
      {/* 封面色块 */}
      <div
        className="h-[120px] flex items-center justify-center"
        style={{ backgroundColor: coverColor }}
      >
        <span className="text-6xl opacity-60">{coverIcon}</span>
      </div>

      {/* 信息区 */}
      <div className="px-4 py-3">
        <p className="text-[15px] font-semibold text-[#1A1A18] truncate mb-1">{plan.title}</p>
        <div className="flex items-center justify-between">
          <p className="text-xs text-[#8C8C87]">
            {plan.sourceCount} 个来源 · {formatDate(plan.lastAccessedAt)}
          </p>
          {plan.totalDays > 0 && (
            <div className="flex items-center gap-1.5">
              <div className="w-16 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                <div
                  className="h-full bg-green-500 rounded-full transition-all duration-300"
                  style={{ width: `${Math.min(100, (plan.completedDays / plan.totalDays) * 100)}%` }}
                />
              </div>
              <span className="text-xs text-[#8C8C87] tabular-nums whitespace-nowrap">
                {plan.completedDays}/{plan.totalDays} 天
              </span>
            </div>
          )}
        </div>
      </div>

      {/* 三点菜单 */}
      <button
        aria-label="更多操作"
        className="absolute top-2 right-2 w-7 h-7 rounded-full bg-white/90 border border-[#E5E5E5] shadow-sm flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity duration-50 hover:bg-white text-[#8C8C87]"
        onClick={e => { e.stopPropagation(); setMenuOpen(m => !m) }}
      >
        ⋮
      </button>

      {menuOpen && (
        <div
          className="absolute top-10 right-2 bg-white rounded-xl shadow-xl border border-[#E5E5E5] z-10 py-1 min-w-[110px]"
          onClick={e => e.stopPropagation()}
        >
          {[
            { label: '打开', action: () => navigate(`/workspace/${plan.id}`) },
            { label: '重命名', action: () => { onRename(plan.id); setMenuOpen(false) } },
            { label: '删除', action: () => { onDelete(plan.id); setMenuOpen(false) }, danger: true },
          ].map(item => (
            <button
              key={item.label}
              onClick={item.action}
              className={`w-full text-left px-4 py-2 text-sm hover:bg-[#F0EDE8] transition-colors duration-50 ${item.danger ? 'text-red-500' : 'text-[#1A1A18]'}`}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
