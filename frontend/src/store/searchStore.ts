import { create } from 'zustand'
import type { SearchHistoryEntry, SearchResult, SearchStage } from '../types'

/** 正在进行中的搜索状态（存在 store 中，组件卸载不丢失） */
interface ActiveSearch {
  query: string
  platforms: string[]
  stage: SearchStage
  stageMessage: string
  results: SearchResult[]
  error: string
  abortController: AbortController | null
}

interface SearchStore {
  history: SearchHistoryEntry[]
  resultDetailMap: Record<string, SearchResult>
  loading: boolean
  /** 当前进行中的搜索（组件卸载后仍保留） */
  activeSearch: ActiveSearch | null
  /** 正在进行深度分析的 materialId 集合 */
  pendingDeepAnalysis: Set<string>

  loadHistory: (planId: string) => Promise<void>
  addEntry: (planId: string, entry: SearchHistoryEntry) => void
  clearHistory: (planId: string) => Promise<void>
  saveResultDetails: (results: SearchResult[]) => void
  updateResultDetail: (id: string, patch: Partial<SearchResult>) => void
  getResultDetail: (materialId: string) => SearchResult | undefined
  updateEntry: (id: string, patch: Partial<SearchHistoryEntry>, planId?: string) => void
  removeEntry: (id: string, planId: string) => void
  setActiveSearch: (search: ActiveSearch | null) => void
  updateActiveSearch: (patch: Partial<ActiveSearch>) => void
  markDeepAnalysisPending: (id: string) => void
  markDeepAnalysisDone: (id: string) => void
}

export const useSearchStore = create<SearchStore>()((set, get) => ({
  history: [],
  resultDetailMap: {},
  loading: false,
  activeSearch: null,
  pendingDeepAnalysis: new Set(),

  loadHistory: async (planId: string) => {
    set({ loading: true })
    try {
      const res = await fetch(`/api/plans/${planId}/search-history`)
      if (!res.ok) throw new Error('加载失败')
      const data = (await res.json()) as SearchHistoryEntry[]
      // 把僵尸 "searching" 记录标记为 error（上次搜索中途页面关了）
      const zombieIds: string[] = []
      const cleaned = data.map(e => {
        if (e.status === 'searching') {
          zombieIds.push(e.id)
          return { ...e, status: 'error' as const }
        }
        return e
      })
      // 同步更新后端，避免每次刷新都重复降级
      if (zombieIds.length > 0) {
        zombieIds.forEach(id => {
          fetch(`/api/plans/${planId}/search-history/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: 'error' }),
          }).catch(() => {})
        })
      }
      const map: Record<string, SearchResult> = {}
      cleaned.forEach((entry) => {
        entry.results.forEach((r: SearchResult) => { map[r.id] = r })
      })
      set({ history: cleaned, resultDetailMap: map, loading: false })
    } catch {
      set({ loading: false })
    }
  },

  addEntry: (planId, entry) => {
    // 先更新本地状态
    set((s) => {
      const map = { ...s.resultDetailMap }
      entry.results.forEach((r) => { map[r.id] = r })
      return {
        history: [entry, ...s.history].slice(0, 20),
        resultDetailMap: map,
      }
    })
    // 异步保存到后端
    fetch(`/api/plans/${planId}/search-history`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(entry),
    }).catch(() => { /* 静默失败 */ })
  },

  clearHistory: async (planId) => {
    set({ history: [], resultDetailMap: {} })
    try {
      await fetch(`/api/plans/${planId}/search-history`, { method: 'DELETE' })
    } catch { /* 静默失败 */ }
  },

  saveResultDetails: (results) =>
    set((s) => {
      const map = { ...s.resultDetailMap }
      results.forEach((r) => { map[r.id] = r })
      return { resultDetailMap: map }
    }),

  updateResultDetail: (id, patch) =>
    set((s) => {
      const existing = s.resultDetailMap[id]
      if (!existing) return s
      return { resultDetailMap: { ...s.resultDetailMap, [id]: { ...existing, ...patch } } }
    }),

  getResultDetail: (id) => get().resultDetailMap[id],

  updateEntry: (id, patch, planId) =>
    set((s) => {
      const idx = s.history.findIndex((e) => e.id === id)
      if (idx === -1) return s
      const updated = { ...s.history[idx], ...patch }
      const history = [...s.history]
      history[idx] = updated
      // Update resultDetailMap if results changed
      const map = { ...s.resultDetailMap }
      if (patch.results) {
        patch.results.forEach((r) => { map[r.id] = r })
      }
      // 异步同步到后端
      if (planId) {
        fetch(`/api/plans/${planId}/search-history/${id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(patch),
        }).catch(() => { /* 静默失败 */ })
      }
      return { history, resultDetailMap: map }
    }),

  removeEntry: (id, planId) => {
    set((s) => ({
      history: s.history.filter((e) => e.id !== id),
    }))
    fetch(`/api/plans/${planId}/search-history/${id}`, {
      method: 'DELETE',
    }).catch(() => { /* 静默失败 */ })
  },

  setActiveSearch: (search) => set({ activeSearch: search }),

  updateActiveSearch: (patch) =>
    set((s) => {
      if (!s.activeSearch) return s
      return { activeSearch: { ...s.activeSearch, ...patch } }
    }),

  markDeepAnalysisPending: (id) =>
    set((s) => {
      const next = new Set(s.pendingDeepAnalysis)
      next.add(id)
      return { pendingDeepAnalysis: next }
    }),

  markDeepAnalysisDone: (id) =>
    set((s) => {
      const next = new Set(s.pendingDeepAnalysis)
      next.delete(id)
      return { pendingDeepAnalysis: next }
    }),
}))
