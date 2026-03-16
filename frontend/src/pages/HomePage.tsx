import React, { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { FeaturedPlans } from '../components/home/FeaturedPlans'
import { PlanCard } from '../components/home/PlanCard'
import { NewPlanModal } from '../components/home/NewPlanModal'
import { TopNav } from '../components/layout/TopNav'
import { usePlanStore } from '../store/planStore'
import { useKeyboard } from '../hooks/useKeyboard'
import type { LearningPlan, LearnerProfile } from '../types'
import type { CreateMode } from '../components/home/NewPlanModal'

type ViewMode = 'grid' | 'list'
type FilterTab = 'all' | 'featured'

const HomePage: React.FC = () => {
  const navigate = useNavigate()
  const { plans, loading: isLoading, addPlan, updatePlan, deletePlan, loadPlans } = usePlanStore()
  const [viewMode, setViewMode] = useState<ViewMode>('grid')
  const [filterTab, setFilterTab] = useState<FilterTab>('all')
  const [modalOpen, setModalOpen] = useState(false)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')

  // 从后端加载规划列表
  useEffect(() => {
    loadPlans()
  }, [])

  // 10.3: 新建规划（扩展：传递 cycleDays + learnerProfile）
  const handleCreate = async (
    title: string,
    _mode: CreateMode,
    _input: string,
    cycleDays: number,
    profile?: Partial<LearnerProfile>
  ) => {
    const res = await fetch('/api/plans', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: title || '新建学习规划',
        cycleDays,
        learnerProfile: profile || undefined,
      }),
    })
    if (!res.ok) {
      throw new Error(`创建失败: ${res.status}`)
    }
    const plan: LearningPlan = await res.json()
    addPlan(plan)
    navigate(`/workspace/${plan.id}`)
  }

  // 10.4: 删除规划
  const handleDelete = async (id: string) => {
    deletePlan(id)
    try { await fetch(`/api/plans/${id}`, { method: 'DELETE' }) } catch { /* 静默 */ }
  }

  // 10.4: 重命名
  const handleRename = (id: string) => {
    const plan = plans.find(p => p.id === id)
    if (!plan) return
    setRenamingId(id)
    setRenameValue(plan.title)
  }

  const commitRename = async () => {
    if (!renamingId || !renameValue.trim()) { setRenamingId(null); return }
    updatePlan(renamingId, { title: renameValue.trim() })
    try {
      await fetch(`/api/plans/${renamingId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: renameValue.trim() }),
      })
    } catch { /* 静默 */ }
    setRenamingId(null)
  }

  // 11.1: Ctrl+N 新建规划，Escape 关闭弹窗
  useKeyboard({
    onNewPlan: useCallback(() => setModalOpen(true), []),
    onEscape: useCallback(() => { setModalOpen(false); setRenamingId(null) }, []),
  })

  const sortedPlans = [...plans].sort(
    (a, b) => new Date(b.lastAccessedAt).getTime() - new Date(a.lastAccessedAt).getTime()
  )

  return (
    <div className="min-h-screen bg-[#F5F3EE] dark:bg-dark-bg">
      {/* 复用 TopNav，首页不传 planTitle */}
      <div className="px-4 py-2">
        <TopNav onNewPlan={() => setModalOpen(true)} />
      </div>

      <main className="max-w-6xl mx-auto px-8 py-8">
        {/* 10.2: 精选规划横向滚动 */}
        <div className="mb-8">
          <FeaturedPlans />
        </div>

        {/* 筛选栏 + 视图切换 */}
        <div className="flex items-center justify-between mb-5">
          <div className="flex gap-1">
            {(['all', 'featured'] as FilterTab[]).map(tab => (
              <button
                key={tab}
                onClick={() => setFilterTab(tab)}
                className={`px-4 py-1.5 text-sm rounded-full transition-all duration-50 ${filterTab === tab
                    ? 'bg-[#F0EDE8] text-[#D97757] font-medium'
                    : 'text-[#8C8C87] hover:text-[#1A1A18] hover:bg-[#F0EDE8]/50'
                  }`}
              >
                {tab === 'all' ? '全部' : '精选笔记本'}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2">
            {/* 10.6: 网格/列表视图切换 */}
            <button
              onClick={() => setViewMode('grid')}
              aria-label="网格视图"
              aria-pressed={viewMode === 'grid'}
              className={`px-2 py-1 rounded text-sm transition-colors duration-50 ${viewMode === 'grid' ? 'text-[#D97757]' : 'text-[#8C8C87] hover:text-[#1A1A18]'}`}
            >
              ⊞ 网格
            </button>
            <button
              onClick={() => setViewMode('list')}
              aria-label="列表视图"
              aria-pressed={viewMode === 'list'}
              className={`px-2 py-1 rounded text-sm transition-colors duration-50 ${viewMode === 'list' ? 'text-[#D97757]' : 'text-[#8C8C87] hover:text-[#1A1A18]'}`}
            >
              ≡ 列表
            </button>
            <button
              onClick={() => setModalOpen(true)}
              className="ml-2 text-[#D97757] border border-[#D97757]/30 rounded-xl px-4 py-2 text-sm font-medium hover:bg-[#FDF5F2] active:scale-95 transition-all duration-50"
            >
              + 新建
            </button>
          </div>
        </div>

        {/* 10.5: 空状态 / 规划列表 */}
        {isLoading ? (
          <div className="grid grid-cols-4 gap-4">
            {[1, 2, 3, 4].map(i => (
              <div key={i} className="h-[180px] rounded-xl bg-[#F1F3F4] animate-pulse" />
            ))}
          </div>
        ) : sortedPlans.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <span className="text-6xl mb-4" aria-hidden="true">📖</span>
            <p className="text-[#8C8C87] mb-6 text-base">还没有学习规划，创建第一个吧</p>
            <button
              onClick={() => setModalOpen(true)}
              className="bg-[#D97757] text-white rounded-xl px-6 py-2.5 text-sm font-medium hover:bg-[#C06144] transition-colors duration-50"
            >
              + 新建学习规划
            </button>
          </div>
        ) : (
          <section>
            <h2 className="text-sm font-semibold text-[#8C8C87] uppercase tracking-wider dark:text-dark-text mb-3">
              最近打开
            </h2>
            <div className={viewMode === 'grid' ? 'grid grid-cols-4 gap-4' : 'flex flex-col gap-2'}>
              {/* 新建卡片 */}
              <button
                onClick={() => setModalOpen(true)}
                className="h-[180px] rounded-2xl border-2 border-dashed border-[#E5E5E5] hover:border-[#D97757] hover:bg-[#FDF5F2] transition-all duration-50 flex flex-col items-center justify-center gap-2 text-[#B0B5BA] hover:text-[#D97757]"
                aria-label="新建学习规划"
              >
                <span className="text-3xl" aria-hidden="true">+</span>
                <span className="text-sm font-medium">新建学习规划</span>
              </button>

              {sortedPlans.map(plan => (
                renamingId === plan.id ? (
                  // 内联重命名
                  <div key={plan.id} className="rounded-xl border-2 border-[#D97757] p-3 flex flex-col justify-center bg-white">
                    <input
                      autoFocus
                      value={renameValue}
                      onChange={e => setRenameValue(e.target.value)}
                      onBlur={commitRename}
                      onKeyDown={e => { if (e.key === 'Enter') commitRename(); if (e.key === 'Escape') setRenamingId(null) }}
                      className="text-sm font-semibold text-[#202124] border-b border-[#D97757] outline-none bg-transparent"
                      aria-label="重命名规划"
                    />
                    <p className="text-xs text-[#5F6368] mt-1">按 Enter 确认，Esc 取消</p>
                  </div>
                ) : (
                  <PlanCard
                    key={plan.id}
                    plan={plan}
                    onRename={handleRename}
                    onDelete={handleDelete}
                  />
                )
              ))}
            </div>
          </section>
        )}
      </main>

      {/* 10.3: 新建规划弹窗 */}
      <NewPlanModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onCreate={handleCreate}
      />
    </div>
  )
}

export default HomePage
