import React, { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { WorkspaceLayout } from '../components/layout/WorkspaceLayout'
import { TopNav } from '../components/layout/TopNav'
import { SourcePanel } from '../components/source-panel/SourcePanel'
import { ChatArea } from '../components/chat/ChatArea'
import { StudioPanel } from '../components/studio/StudioPanel'
import { NewPlanModal } from '../components/home/NewPlanModal'
import { useKeyboard } from '../hooks/useKeyboard'
import { useChatStore } from '../store/chatStore'
import { useSourceStore } from '../store/sourceStore'
import { usePlanStore } from '../store/planStore'
import { useStudioStore } from '../store/studioStore'
import { useSearchStore } from '../store/searchStore'
import type { LearningPlan } from '../types'

const WorkspacePage: React.FC = () => {
  const { planId } = useParams<{ planId: string }>()
  const navigate = useNavigate()
  const [isDark, setIsDark] = useState(() => {
    const saved = localStorage.getItem('theme')
    if (saved === 'dark') { document.documentElement.classList.add('dark'); return true }
    return false
  })
  const [isRestoring, setIsRestoring] = useState(true)
  const [newPlanModalOpen, setNewPlanModalOpen] = useState(false)

  const { plans } = usePlanStore()
  const planTitle = plans.find(p => p.id === planId)?.title ?? '学习规划'
  const [isReading, setIsReading] = useState(false)
  const [isLeftCollapsed, setIsLeftCollapsed] = useState(false)
  const [isRightCollapsed, setIsRightCollapsed] = useState(false)

  const toggleDark = () => {
    setIsDark(d => {
      const next = !d
      document.documentElement.classList.toggle('dark', next)
      localStorage.setItem('theme', next ? 'dark' : 'light')
      return next
    })
  }

  // 页面加载时从 API 并行加载所有数据
  useEffect(() => {
    if (!planId) { setIsRestoring(false); return }
    setIsRestoring(true)

    Promise.all([
      useChatStore.getState().loadMessages(planId),
      useSourceStore.getState().loadMaterials(planId),
      useStudioStore.getState().loadStudioData(planId),
      useSearchStore.getState().loadHistory(planId),
    ]).finally(() => setIsRestoring(false))
  }, [planId])

  const handleNewPlan = useCallback(async (title: string) => {
    try {
      const res = await fetch('/api/plans', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title || '新建学习规划' }),
      })
      if (res.ok) {
        const plan: LearningPlan = await res.json()
        usePlanStore.getState().addPlan(plan)
        setNewPlanModalOpen(false)
        navigate(`/workspace/${plan.id}`)
        return
      }
    } catch { /* fallback */ }
    const newPlan: LearningPlan = {
      id: `local-${Date.now()}`,
      title: title || '新建学习规划',
      sourceCount: 0,
      lastAccessedAt: new Date().toISOString(),
      coverColor: '',
      totalDays: 0,
      completedDays: 0,
    }
    usePlanStore.getState().addPlan(newPlan)
    setNewPlanModalOpen(false)
    navigate(`/workspace/${newPlan.id}`)
  }, [navigate])

  // Ctrl+K 聚焦输入框
  useKeyboard({
    onFocusInput: () => {
      const textarea = document.querySelector<HTMLTextAreaElement>('textarea[aria-label="输入消息"]')
      textarea?.focus()
    },
  })

  // 加载骨架屏
  if (isRestoring) {
    return (
      <div className="flex flex-col h-screen bg-[#F8F9FA] dark:bg-dark-bg">
        <div className="h-14 bg-white dark:bg-dark-bg border-b border-[#DADCE0] animate-pulse" />
        <div className="flex flex-1 gap-0">
          <div className="w-[22%] bg-[#F1F3F4] animate-pulse" />
          <div className="flex-1 bg-white animate-pulse" />
          <div className="w-[28%] bg-[#F1F3F4] animate-pulse" />
        </div>
      </div>
    )
  }

  return (
    <>
      <WorkspaceLayout
        isReading={isReading}
        isLeftCollapsed={isLeftCollapsed}
        isRightCollapsed={isRightCollapsed}
        topNav={
          <TopNav
            planTitle={planTitle}
            onTitleChange={(newTitle) => {
              if (planId) usePlanStore.getState().updatePlan(planId, { title: newTitle })
            }}
            onToggleDark={toggleDark}
            isDark={isDark}
            onNewPlan={() => setNewPlanModalOpen(true)}
          />
        }
        left={
          <SourcePanel
            planId={planId}
            onReadingChange={setIsReading}
            isCollapsed={isLeftCollapsed}
            onToggleCollapse={() => setIsLeftCollapsed(!isLeftCollapsed)}
          />
        }
        center={<ChatArea planId={planId} />}
        right={
          <StudioPanel
            planId={planId}
            isCollapsed={isRightCollapsed}
            onToggleCollapse={() => setIsRightCollapsed(!isRightCollapsed)}
          />
        }
      />

      {/* 新建规划弹窗 */}
      <NewPlanModal
        open={newPlanModalOpen}
        onClose={() => setNewPlanModalOpen(false)}
        onCreate={handleNewPlan}
      />
    </>
  )
}

export default WorkspacePage
