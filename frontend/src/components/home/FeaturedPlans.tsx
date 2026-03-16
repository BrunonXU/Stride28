import React from 'react'
import { useNavigate } from 'react-router-dom'
import { usePlanStore } from '../../store/planStore'

// 渐变封面色
const COVER_GRADIENTS = [
  'from-orange-400 to-indigo-600',
  'from-orange-400 to-red-500',
  'from-emerald-400 to-teal-600',
  'from-purple-400 to-pink-500',
  'from-cyan-400 to-blue-600',
  'from-rose-400 to-orange-500',
]

export const FeaturedPlans: React.FC = () => {
  const navigate = useNavigate()
  const { plans } = usePlanStore()

  // 按最近访问排序，取前 6 个
  const featured = [...plans]
    .sort((a, b) => new Date(b.lastAccessedAt).getTime() - new Date(a.lastAccessedAt).getTime())
    .slice(0, 6)

  if (featured.length === 0) return null

  return (
    <section>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-base font-semibold text-[#202124] dark:text-dark-text">精选学习规划</h2>
      </div>
      <div className="flex gap-4 overflow-x-auto pb-2 scrollbar-thin">
        {featured.map((plan, i) => (
          <div
            key={plan.id}
            className="flex-shrink-0 w-[240px] rounded-3xl overflow-hidden border border-black/5 shadow-soft hover:shadow-md hover:-translate-y-1 transition-all duration-50 cursor-pointer group bg-white dark:bg-dark-card dark:border-dark-border"
            onClick={() => navigate(`/workspace/${plan.id}`)}
          >
            {/* 渐变封面 */}
            <div className={`h-[120px] bg-gradient-to-br ${COVER_GRADIENTS[i % COVER_GRADIENTS.length]} flex items-end p-3`}>
              <span className="text-white text-sm font-semibold leading-tight drop-shadow">
                {plan.title}
              </span>
            </div>
            {/* 信息区 */}
            <div className="bg-white dark:bg-dark-card px-5 py-4 flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-[#5F6368] dark:text-dark-muted mb-0.5">
                  {plan.sourceCount} 个来源
                </p>
                <p className="text-sm text-[#9AA0A6] dark:text-dark-muted">
                  {new Date(plan.lastAccessedAt).toLocaleDateString('zh-CN')}
                </p>
              </div>
              {plan.totalDays > 0 && (
                <span className="text-xs text-[#9AA0A6] dark:text-dark-muted">
                  {plan.completedDays}/{plan.totalDays} 天
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
