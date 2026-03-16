import { create } from 'zustand'
import type { DayProgress, GeneratedContent, Note, LearnerProfile } from '../types'

interface StudioStore {
  allDays: DayProgress[]
  currentDay: DayProgress | null
  generatedContents: GeneratedContent[]
  notes: Note[]
  activePlanId: string
  devMode: boolean
  loading: boolean
  learnerProfile: LearnerProfile | null
  profileLoaded: boolean

  // Timeline 状态
  timelineStatus: 'idle' | 'loading' | 'empty' | 'regenerating'
  selectedDay: number | null
  // 回滚快照（REQ 9）
  _snapshot: {
    allDays: DayProgress[]
    duration: number
  } | null

  loadStudioData: (planId: string) => Promise<void>
  setLearningPlan: (days: DayProgress[]) => void
  toggleTask: (dayNumber: number, taskIndex: number) => void
  completeDay: (dayNumber: number) => void
  addGeneratedContent: (c: GeneratedContent) => void
  addNote: (n: Note) => void
  updateNote: (id: string, patch: Partial<Note>) => void
  deleteNote: (id: string) => void
  setDevMode: (v: boolean) => void
  setLearnerProfile: (p: LearnerProfile) => void
  saveLearnerProfile: (planId: string, p: LearnerProfile) => Promise<void>

  // Timeline actions
  setSelectedDay: (day: number | null) => void
  setTimelineStatus: (status: 'idle' | 'loading' | 'empty' | 'regenerating') => void
  completeDayOptimistic: (planId: string, dayNumber: number) => Promise<void>
  regeneratePlan: (planId: string, newCycleDays: number) => Promise<void>
}

function findCurrentDay(days: DayProgress[]): DayProgress | null {
  return days.find((d) => !d.completed) ?? null
}

/** 将平铺的内容列表按 type 合并，同类型保留最新为当前版本，旧的存入 versions */
function mergeContentsByType(items: GeneratedContent[]): GeneratedContent[] {
  const grouped = new Map<string, GeneratedContent[]>()
  for (const item of items) {
    const list = grouped.get(item.type) || []
    list.push(item)
    grouped.set(item.type, list)
  }
  const result: GeneratedContent[] = []
  for (const [, list] of grouped) {
    // 按时间倒序（最新在前）
    list.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
    const [latest, ...older] = list
    const versions = older.map((item, i) => ({
      content: item.content,
      createdAt: item.createdAt,
      version: older.length - i,
    }))
    result.push({
      ...latest,
      version: list.length,
      versions,
    })
  }
  // 按最新 createdAt 排序
  result.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
  return result
}

export const useStudioStore = create<StudioStore>()((set, get) => ({
  allDays: [],
  currentDay: null,
  generatedContents: [],
  notes: [],
  activePlanId: '',
  devMode: false,
  loading: false,
  learnerProfile: null,
  profileLoaded: false,
  timelineStatus: 'idle' as const,
  selectedDay: null,
  _snapshot: null,

  loadStudioData: async (planId: string) => {
    set({ loading: true, activePlanId: planId, timelineStatus: 'loading' })
    try {
      const [progressRes, contentsRes, notesRes, profileRes] = await Promise.all([
        fetch(`/api/plans/${planId}/progress`),
        fetch(`/api/plans/${planId}/generated-contents`),
        fetch(`/api/plans/${planId}/notes`),
        fetch(`/api/learner-profile/${planId}`),
      ])
      const [progress, contents, notesData] = await Promise.all([
        progressRes.ok ? progressRes.json() : [],
        contentsRes.ok ? contentsRes.json() : [],
        notesRes.ok ? notesRes.json() : [],
      ])
      const profileData = profileRes.ok ? await profileRes.json() : null
      const hasProfile = profileData && (profileData.goal || profileData.level || profileData.duration || profileData.background || profileData.dailyHours)
      set({
        allDays: progress,
        currentDay: findCurrentDay(progress),
        generatedContents: mergeContentsByType(contents),
        notes: notesData,
        learnerProfile: hasProfile ? profileData : null,
        profileLoaded: true,
        loading: false,
        timelineStatus: progress.length > 0 ? 'idle' : 'empty',
      })
    } catch {
      set({ loading: false, profileLoaded: true, timelineStatus: 'idle' })
    }
  },

  setLearningPlan: (days) => set({ allDays: days, currentDay: findCurrentDay(days), timelineStatus: days.length > 0 ? 'idle' : 'empty' }),

  toggleTask: (dayNumber, taskIndex) => set((s) => {
    const allDays = s.allDays.map((d) => {
      if (d.dayNumber !== dayNumber) return d
      const tasks = d.tasks.map((t, i) => i === taskIndex ? { ...t, completed: !t.completed } : t)
      return { ...d, tasks }
    })
    return { allDays, currentDay: findCurrentDay(allDays) }
  }),

  completeDay: (dayNumber) => set((s) => {
    const allDays = s.allDays.map((d) => d.dayNumber === dayNumber ? { ...d, completed: true } : d)
    return { allDays, currentDay: findCurrentDay(allDays) }
  }),

  addGeneratedContent: (c) => set((s) => {
    const existing = s.generatedContents.find((g) => g.type === c.type)
    if (existing) {
      // 合并：旧版本存入 versions，新内容替换当前
      const oldVersions = existing.versions || []
      const oldVersion = {
        content: existing.content,
        createdAt: existing.createdAt,
        version: existing.version || 1,
      }
      const newVersion = (existing.version || 1) + 1
      const merged = {
        ...existing,
        content: c.content,
        title: c.title,
        createdAt: c.createdAt,
        version: newVersion,
        versions: [oldVersion, ...oldVersions],
      }
      return {
        generatedContents: s.generatedContents.map((g) => g.type === c.type ? merged : g),
      }
    }
    // 新类型：直接添加
    return { generatedContents: [{ ...c, version: 1, versions: [] }, ...s.generatedContents] }
  }),
  addNote: (n) => {
    set((s) => ({ notes: [n, ...s.notes] }))
    // Persist to backend
    const { activePlanId } = useStudioStore.getState()
    if (activePlanId) {
      fetch('/api/notes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ planId: activePlanId, title: n.title, content: n.content }),
      }).then(res => res.ok ? res.json() : null).then(data => {
        if (data && data.id) {
          // Replace temp ID with backend ID
          set((s) => ({ notes: s.notes.map(note => note.id === n.id ? { ...note, id: data.id } : note) }))
        }
      }).catch(() => {})
    }
  },
  updateNote: (id, patch) => {
    set((s) => ({ notes: s.notes.map((n) => n.id === id ? { ...n, ...patch } : n) }))
    fetch(`/api/notes/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: patch.title, content: patch.content }),
    }).catch(() => {})
  },
  deleteNote: (id) => {
    set((s) => ({ notes: s.notes.filter((n) => n.id !== id) }))
    fetch(`/api/notes/${id}`, { method: 'DELETE' }).catch(() => {})
  },
  setDevMode: (v) => set({ devMode: v }),
  setLearnerProfile: (p) => set({ learnerProfile: p }),
  saveLearnerProfile: async (planId, p) => {
    try {
      const res = await fetch(`/api/learner-profile/${planId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(p),
      })
      if (res.ok) {
        set({ learnerProfile: p })
      }
    } catch { /* silent */ }
  },

  // Timeline actions
  setSelectedDay: (day) => set({ selectedDay: day }),
  setTimelineStatus: (status) => set({ timelineStatus: status }),

  // 乐观更新 completeDay：先更新前端 → PUT 持久化 → 失败回滚
  completeDayOptimistic: async (planId, dayNumber) => {
    const prevDays = get().allDays
    // 乐观更新
    get().completeDay(dayNumber)
    try {
      const res = await fetch(`/api/plans/${planId}/progress/${dayNumber}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ completed: true }),
      })
      if (!res.ok) throw new Error('persist failed')
    } catch {
      // 失败回滚
      set({ allDays: prevDays, currentDay: findCurrentDay(prevDays) })
      throw new Error('ROLLBACK')
    }
  },

  // 周期变更重新生成：保存快照 → regenerating → 后端调用 → 成功更新/失败回滚
  regeneratePlan: async (planId, newCycleDays) => {
    const { allDays, learnerProfile } = get()
    const completedDays = allDays.filter((d) => d.completed)

    // 保存快照用于回滚
    set({
      _snapshot: { allDays, duration: learnerProfile?.duration ?? 14 },
      timelineStatus: 'regenerating',
    })

    try {
      const res = await fetch('/api/studio/regenerate-plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ planId, newCycleDays, completedDays }),
      })
      if (!res.ok) throw new Error('regenerate failed')
      const data = await res.json()

      set({
        allDays: data.days,
        currentDay: findCurrentDay(data.days),
        timelineStatus: 'idle',
        _snapshot: null,
        learnerProfile: get().learnerProfile
          ? { ...get().learnerProfile!, duration: newCycleDays }
          : null,
      })
    } catch {
      // 失败回滚到快照
      const snapshot = get()._snapshot
      if (snapshot) {
        set({
          allDays: snapshot.allDays,
          currentDay: findCurrentDay(snapshot.allDays),
          learnerProfile: get().learnerProfile
            ? { ...get().learnerProfile!, duration: snapshot.duration }
            : null,
          timelineStatus: 'idle',
          _snapshot: null,
        })
      }
      throw new Error('ROLLBACK')
    }
  },
}))
