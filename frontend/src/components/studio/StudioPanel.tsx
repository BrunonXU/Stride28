import React, { useState, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { ContentViewer } from './ContentViewer'
import { NoteEditor } from './NoteEditor'
import { DevPanel } from './DevPanel'
import { Timeline } from './Timeline'
import { DayDetail } from './DayDetail'
import { LearnerProfileModal } from './LearnerProfileModal'
import ProgressRing from './ProgressRing'
import { useStudioStore } from '../../store/studioStore'
import { useSourceStore } from '../../store/sourceStore'
import { extractJSON } from '../../utils/jsonRepair'
import type { GeneratedContent, Note, LearnerProfile } from '../../types'

/** 现代白卡片风格工具定义 */
const TOOLS = [
  { type: 'study-guide', icon: '📖', label: '学习指南', bg: 'bg-white hover:bg-[#FFF7ED]', border: 'border-[#E8EAED] hover:border-[#F2DFD3]' },
  { type: 'flashcards', icon: '🃏', label: '闪卡', bg: 'bg-white hover:bg-[#FFF7ED]', border: 'border-[#E8EAED] hover:border-[#F2DFD3]' },
  { type: 'quiz', icon: '🧪', label: '测验', bg: 'bg-white hover:bg-[#FFF7ED]', border: 'border-[#E8EAED] hover:border-[#F2DFD3]' },
  { type: 'learning-plan', icon: '📅', label: '学习计划', bg: 'bg-white hover:bg-[#FFF7ED]', border: 'border-[#E8EAED] hover:border-[#F2DFD3]' },
  { type: 'progress-report', icon: '📊', label: '进度报告', bg: 'bg-white hover:bg-[#FFF7ED]', border: 'border-[#E8EAED] hover:border-[#F2DFD3]' },
  { type: 'mind-map', icon: '🧠', label: '思维导图', bg: 'bg-white hover:bg-[#FFF7ED]', border: 'border-[#E8EAED] hover:border-[#F2DFD3]' },
] as const

const TYPE_ICONS: Record<string, string> = {
  'learning-plan': '📅', 'study-guide': '📖', 'flashcards': '🃏',
  'quiz': '🧪', 'progress-report': '📊', 'mind-map': '🧠', 'day-summary': '✅',
}

interface StudioPanelProps {
  planId?: string
  isCollapsed?: boolean
  onToggleCollapse?: () => void
}

export const StudioPanel: React.FC<StudioPanelProps> = ({ planId = '', isCollapsed = false, onToggleCollapse }) => {
  const {
    generatedContents, notes, addGeneratedContent, addNote, updateNote, deleteNote,
    devMode, setDevMode, learnerProfile, saveLearnerProfile,
    selectedDay, activePlanId, allDays,
  } = useStudioStore()
  const { materials } = useSourceStore()
  const [loadingTools, setLoadingTools] = useState<Set<string>>(new Set())
  const [viewingContent, setViewingContent] = useState<GeneratedContent | null>(null)
  const [editingNote, setEditingNote] = useState<Note | null>(null)
  const [showNewNote, setShowNewNote] = useState(false)
  const [menuId, setMenuId] = useState<string | null>(null)
  const [hoveredItem, setHoveredItem] = useState<{ id: string, title: string, rect: DOMRect } | null>(null)
  const [showProfileModal, setShowProfileModal] = useState(false)
  const [pendingToolType, setPendingToolType] = useState<{ type: string; label: string } | null>(null)
  const prevMatCount = useRef(materials.length)

  // Types that require learner profile before first generation
  const PROFILE_REQUIRED_TYPES = new Set(['study-guide', 'learning-plan'])

  // 工具卡片点击（支持并发）
  const handleToolClick = async (type: string, label: string) => {
    if (loadingTools.has(type)) return

    // Check if learner profile is needed for this type
    if (PROFILE_REQUIRED_TYPES.has(type) && !learnerProfile) {
      setPendingToolType({ type, label })
      setShowProfileModal(true)
      return
    }

    await doGenerate(type, label)
  }

  const doGenerate = async (type: string, label: string) => {
    if (loadingTools.has(type)) return
    setLoadingTools(prev => new Set(prev).add(type))
    try {
      const { allDays, activePlanId, learnerProfile: profile } = useStudioStore.getState()
      const currentDay = allDays.find(d => !d.completed) ?? null

      const res = await fetch(`/api/studio/${type}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          planId: planId || activePlanId,
          allDays,
          currentDayNumber: currentDay?.dayNumber ?? null,
          learnerProfile: profile || undefined,
        }),
      })
      if (res.ok) {
        const data = await res.json()

        // learning-plan special handling: parse JSON and update learning plan
        if (type === 'learning-plan') {
          try {
            const parsed = extractJSON(data.content)
            if (parsed?.days && Array.isArray(parsed.days)) {
              const { setLearningPlan } = useStudioStore.getState()
              const { allDays: existingDays } = useStudioStore.getState()
              // 构建已完成状态映射（dayNumber → completed）
              const completedMap = new Map<number, boolean>()
              existingDays.forEach(d => { if (d.completed) completedMap.set(d.dayNumber, true) })

              const days = parsed.days.map((d: any) => ({
                dayNumber: d.dayNumber,
                title: d.title,
                completed: completedMap.get(d.dayNumber) || false,
                tasks: (d.tasks || []).map((t: any, i: number) => ({
                  id: t.id || `task-${d.dayNumber}-${i}`,
                  type: t.type || 'reading',
                  title: t.title,
                  completed: false,
                })),
              }))
              setLearningPlan(days)
              // Persist to backend
              const pid = planId || activePlanId
              if (pid) {
                fetch(`/api/plans/${pid}/progress`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify(days),
                }).catch(() => { })
              }
            }
          } catch { /* JSON parse failed, treat as Markdown */ }
        }

        addGeneratedContent({
          id: `${type}-${Date.now()}`,
          type: type as GeneratedContent['type'],
          title: data.title || label,
          content: data.content,
          createdAt: data.createdAt || new Date().toISOString(),
        })
      }
    } catch { /* 静默 */ }
    finally { setLoadingTools(prev => { const next = new Set(prev); next.delete(type); return next }) }
  }

  // 首次添加材料自动生成学习指南
  useEffect(() => {
    const prev = prevMatCount.current
    prevMatCount.current = materials.length
    if (prev === 0 && materials.length === 1) {
      if (!generatedContents.some(c => c.type === 'study-guide')) {
        handleToolClick('study-guide', '学习指南')
      }
    }
  }, [materials.length])

  const handleProfileSave = async (profile: LearnerProfile) => {
    const pid = planId || useStudioStore.getState().activePlanId
    await saveLearnerProfile(pid, profile)
    setShowProfileModal(false)
    if (pendingToolType) {
      const { type, label } = pendingToolType
      setPendingToolType(null)
      doGenerate(type, label)
    }
  }

  const handleProfileSkip = () => {
    setShowProfileModal(false)
    if (pendingToolType) {
      const { type, label } = pendingToolType
      setPendingToolType(null)
      doGenerate(type, label)
    }
  }

  const handleSaveNote = (data: { id?: string; title: string; content: string }) => {
    if (data.id) {
      updateNote(data.id, { title: data.title, content: data.content, updatedAt: new Date().toISOString() })
    } else {
      addNote({ id: 'note-' + Date.now(), title: data.title, content: data.content, updatedAt: new Date().toISOString() })
    }
    setEditingNote(null); setShowNewNote(false)
  }

  const handleDeleteContent = (id: string) => {
    useStudioStore.setState((s) => ({
      generatedContents: s.generatedContents.filter(c => c.id !== id)
    }))
    fetch(`/api/generated-contents/${id}`, { method: 'DELETE' }).catch(() => { })
    setMenuId(null)
  }

  const handleDeleteNote = (id: string) => {
    deleteNote(id)
    setMenuId(null)
  }

  const handleExport = (c: GeneratedContent) => {
    const blob = new Blob([c.content], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    Object.assign(document.createElement('a'), { href: url, download: c.title + '.md' }).click()
    URL.revokeObjectURL(url)
    setMenuId(null)
  }

  const fmt = (iso: string) => {
    const d = new Date(iso)
    const now = new Date()
    const diff = now.getTime() - d.getTime()
    if (diff < 60000) return '刚刚'
    if (diff < 3600000) return Math.floor(diff / 60000) + ' 分钟前'
    if (diff < 86400000) return Math.floor(diff / 3600000) + ' 小时前'
    return Math.floor(diff / 86400000) + ' 天前'
  }

  // 合并内容列表：AI 生成 + 笔记，按时间倒序
  const allItems = [
    ...generatedContents.map(c => ({ ...c, kind: 'generated' as const })),
    ...notes.map(n => ({ ...n, kind: 'note' as const, type: 'note' as const, content: n.content, createdAt: n.updatedAt })),
  ].sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())

  return (
    <div className="relative flex flex-col h-full overflow-hidden bg-white dark:bg-dark-bg border-l border-[#E5E5E5]">
      {/* 标题栏 */}
      <div className={`flex items-center h-[68px] px-8 flex-shrink-0 transition-all border-b border-[#E8EAED] bg-white z-10 ${isCollapsed ? 'justify-center px-0 flex-col gap-0 h-[68px]' : 'justify-between'}`}>
        {!isCollapsed && (
          <span className="text-base font-semibold text-[#202124] dark:text-dark-text mt-2 flex items-center gap-2">
            Studio
            <button
              onClick={() => { setPendingToolType(null); setShowProfileModal(true) }}
              className={`w-7 h-7 flex items-center justify-center rounded-lg transition-colors ${learnerProfile ? 'bg-[#F2DFD3] text-[#D97757] hover:bg-[#EACFC0]' : 'text-gray-400 hover:text-gray-600 hover:bg-black/5'}`}
              aria-label="学习者画像"
              title={learnerProfile ? '编辑学习者画像' : '设置学习者画像'}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill={learnerProfile ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                <circle cx="12" cy="7" r="4"></circle>
              </svg>
            </button>
          </span>
        )}
        <div className={`flex items-center gap-2 ${isCollapsed ? 'flex-col' : ''}`}>
          {!isCollapsed && (
            <button onClick={() => setDevMode(!devMode)}
              className={`text-[11px] px-2.5 py-1 rounded-md transition-all mr-2 font-medium ${devMode ? 'bg-[#F2DFD3] text-[#D97757] border border-[#D97757]/30' : 'text-gray-400 hover:text-gray-600 border border-transparent hover:bg-black/5'}`}
              aria-label="开发者模式">DEV</button>
          )}
          <button
            aria-label={isCollapsed ? "展开侧边栏" : "收起侧边栏"}
            onClick={onToggleCollapse}
            className="w-10 h-10 flex items-center justify-center rounded-xl text-[#5F6368] hover:bg-[#F1F3F4] transition-colors duration-50"
          >
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><line x1="15" y1="3" x2="15" y2="21"></line></svg>
          </button>
        </div>
      </div>

      {isCollapsed ? (
        <div className="flex-1 overflow-y-auto scrollbar-thin py-4">
          <ul className="flex flex-col items-center gap-4 w-full relative">
            {allItems.map(item => (
              <li key={item.id} onClick={() => item.kind === 'generated' ? setViewingContent(item as GeneratedContent) : setEditingNote(item as unknown as Note)}
                onMouseEnter={(e) => setHoveredItem({ id: item.id, title: item.title, rect: e.currentTarget.getBoundingClientRect() })}
                onMouseLeave={() => setHoveredItem(null)}
                className="w-12 h-12 flex items-center justify-center rounded-full hover:bg-[#F1F3F4] cursor-pointer group relative">
                <span className="text-2xl">{item.kind === 'note' ? '📝' : (TYPE_ICONS[item.type] || '📄')}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : devMode ? (
        /* DEV 模式：调试面板 */
        <div className="flex-1 overflow-y-auto">
          <DevPanel />
        </div>
      ) : (
        /* 正常模式：工具卡片 + 内容列表 + 笔记 */
        <>
          {/* 灰底大背景区域 */}
          <div className="flex-1 overflow-y-auto bg-[#F0F2F5] pb-24">
            
            {/* ProgressRing + Timeline 合并为一行卡片 */}
            <div className="px-6 pt-6 pb-2">
              <div className="bg-white rounded-2xl shadow-sm border border-[#E8EAED] flex items-center gap-4 px-5 py-4">
                {allDays.length > 0 ? (
                  <>
                    <ProgressRing
                      completed={allDays.filter(d => d.completed).length}
                      total={allDays.length}
                      size={52}
                    />
                    <div className="flex-1 min-w-0 overflow-hidden">
                      <Timeline planId={planId || activePlanId || ''} inline />
                    </div>
                  </>
                ) : (
                  <div className="w-full">
                    <Timeline planId={planId || activePlanId || ''} />
                  </div>
                )}
              </div>
            </div>
            {selectedDay != null && (
              <DayDetail planId={planId || activePlanId || ''} dayNumber={selectedDay} />
            )}

            {/* 工具卡片网格 */}
            <div className="px-6 py-2">
              {learnerProfile && (
                <div className="mb-3 flex items-center px-1">
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    <span className="text-sm font-semibold text-[#1A1A18] truncate">
                      {learnerProfile.goal ? learnerProfile.goal : '学习者画像'}
                    </span>
                    <span className="text-[12px] text-[#9AA0A6] truncate">
                      {learnerProfile.level ? `· ${learnerProfile.level}` : ''}
                      {learnerProfile.duration ? ` · ${learnerProfile.duration}` : ''}
                    </span>
                  </div>
                </div>
              )}
              <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
                {TOOLS.map(t => (
                  <button key={t.type} onClick={() => handleToolClick(t.type, t.label)}
                    disabled={loadingTools.has(t.type)}
                    className={`relative flex flex-col justify-between h-[90px] text-left p-3.5 rounded-2xl ${t.bg} transition-all duration-50 ease-out hover:-translate-y-[2px] cursor-pointer group shadow-sm hover:shadow border ${t.border}`}>
                    <div className="flex w-full justify-between items-start">
                      <div className="w-8 h-8 rounded-full bg-[#F4F5F7] group-hover:bg-white transition-colors flex items-center justify-center -ml-0.5 -mt-0.5 shadow-sm border border-[#E8EAED]">
                        <span className="text-[15px] leading-none">{t.icon}</span>
                      </div>
                      <div className="w-6 h-6 rounded-full flex items-center justify-center text-[#D97757] opacity-0 group-hover:opacity-100 transition-opacity">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M12 20h9"></path><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path></svg>
                      </div>
                    </div>
                    <span className="text-[13px] font-semibold text-[#202124] group-hover:text-[#D97757] transition-colors">{t.label}</span>
                    {loadingTools.has(t.type) && (
                      <div className="absolute inset-0 bg-white/60 rounded-2xl flex items-center justify-center">
                        <div className="w-5 h-5 border-2 border-[#D97757] border-t-transparent rounded-full animate-spin" />
                      </div>
                    )}
                  </button>
                ))}
              </div>
            </div>

            {/* 内容列表 */}
            <div className="px-6 pb-6 pt-4">
              <p className="text-xs font-semibold text-[#9AA0A6] uppercase tracking-wide mb-3 pl-1">产出文件</p>
              {allItems.length === 0 ? (
                <div className="bg-white rounded-2xl shadow-sm border border-[#E8EAED] p-8 flex flex-col items-center justify-center text-center">
                  <span className="text-3xl mb-2 opacity-50">📁</span>
                  <p className="text-[13px] text-[#9AA0A6]">使用上方工具生成您的专属学习内容</p>
                </div>
              ) : (
                <ul className="flex flex-col gap-2">
                  {allItems.map(item => (
                    <li key={item.id}
                      className="flex items-center gap-3 px-4 py-3 bg-white rounded-xl border border-[#E8EAED] shadow-sm hover:shadow hover:border-[#F2DFD3] hover:-translate-y-[1px] cursor-pointer group relative transition-all duration-50"
                      onClick={() => item.kind === 'generated' ? setViewingContent(item as GeneratedContent) : setEditingNote(item as unknown as Note)}>
                      <span className="w-10 h-10 rounded-full bg-[#F4F5F7] group-hover:bg-[#FFF7ED] group-hover:text-[#D97757] border border-[#E8EAED] group-hover:border-[#F2DFD3] transition-colors flex items-center justify-center text-[16px] flex-shrink-0">
                        {item.kind === 'note' ? '📝' : (TYPE_ICONS[item.type] || '📄')}
                      </span>
                      <div className="flex-1 min-w-0 pr-6">
                        <p className="text-[14px] font-semibold text-[#1A1A18] dark:text-dark-text truncate leading-tight mb-1 group-hover:text-[#D97757] transition-colors">{item.title}</p>
                        <p className="text-[11px] text-[#9AA0A6] mt-0.5 flex gap-1.5 items-center">
                          <span className="px-1.5 py-0.5 rounded bg-[#F8F9FA] text-[#5F6368] font-medium leading-none">
                            {item.kind === 'note' ? '笔记' : item.type === 'learning-plan' ? '学习计划' : item.type === 'study-guide' ? '学习指南' : item.type === 'flashcards' ? '闪卡' : item.type === 'quiz' ? '测验' : item.type === 'mind-map' ? '思维导图' : item.type === 'day-summary' ? '今日总结' : item.type === 'progress-report' ? '进度报告' : '报告'}
                          </span>
                          {item.kind === 'generated' && (item as GeneratedContent).version && (item as GeneratedContent).version! > 1 && (
                            <span className="text-[#D97757] font-semibold">v{(item as GeneratedContent).version}</span>
                          )}
                          <span className="text-[#B0B5BA]">{fmt(item.createdAt)}</span>
                        </p>
                      </div>
                      <button onClick={(e) => { e.stopPropagation(); setMenuId(menuId === item.id ? null : item.id) }}
                        className="absolute right-3 opacity-0 group-hover:opacity-100 w-8 h-8 flex items-center justify-center rounded-full hover:bg-[#F0F2F5] text-[#9AA0A6] hover:text-[#5F6368] transition-all"
                        aria-label="更多操作">⋮</button>
                      {menuId === item.id && (
                        <div className="absolute right-3 top-10 z-20 bg-white dark:bg-dark-surface border border-[#E8EAED] rounded-xl shadow-[0_8px_30px_rgb(0,0,0,0.12)] py-1.5 min-w-[120px]"
                          onClick={e => e.stopPropagation()}>
                          {item.kind === 'generated' && (
                            <button onClick={() => handleExport(item as GeneratedContent)}
                              className="w-full text-left px-4 py-2 text-[13px] font-medium text-[#5F6368] hover:bg-[#F0F2F5] hover:text-[#1A1A18] transition-colors">导出 Markdown</button>
                          )}
                          <button onClick={() => item.kind === 'generated' ? handleDeleteContent(item.id) : handleDeleteNote(item.id)}
                            className="w-full text-left px-4 py-2 text-[13px] font-medium text-red-500 hover:bg-red-50 transition-colors">删除</button>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          {/* 底部悬浮：添加笔记按钮 */}
          <div className="absolute bottom-6 left-0 right-0 px-6 flex justify-center pointer-events-none">
            <button onClick={() => setShowNewNote(true)}
              className="flex items-center justify-center gap-2 h-11 px-8 rounded-full bg-[#D97757] text-white text-[15px] font-bold hover:bg-[#C06144] hover:shadow-lg hover:-translate-y-0.5 active:scale-95 transition-all duration-50 shadow-[0_4px_14px_0_rgba(217,119,87,0.39)] pointer-events-auto">
              + 添加笔记
            </button>
          </div>
        </>
      )}

      {/* 弹窗 */}
      {viewingContent && <ContentViewer content={viewingContent} onClose={() => setViewingContent(null)} />}
      {(editingNote || showNewNote) && (
        <NoteEditor note={editingNote || undefined} onSave={handleSaveNote}
          onClose={() => { setEditingNote(null); setShowNewNote(false) }} planId={planId} />
      )}
      {showProfileModal && (
        <LearnerProfileModal
          initial={learnerProfile}
          onSave={handleProfileSave}
          onSkip={handleProfileSkip}
        />
      )}

      {/* Tooltip Portal */}
      {hoveredItem && isCollapsed && createPortal(
        <div style={{ top: hoveredItem.rect.top + (hoveredItem.rect.height / 2), left: hoveredItem.rect.left - 8, transform: 'translate(-100%, -50%)' }}
          className="fixed z-[9999] px-3 py-1.5 bg-[#1E1E1E] text-white text-[13px] whitespace-nowrap rounded-md shadow-lg pointer-events-none fade-in duration-50">
          {hoveredItem.title}
        </div>,
        document.body
      )}
    </div>
  )
}
