import { create } from 'zustand'
import type { Material, SearchResult, PlatformType } from '../types'

type PlatformStatus = 'idle' | 'searching' | 'done' | 'timeout' | 'error'

interface SourceStore {
  materials: Material[]
  searchResults: SearchResult[]
  platformSearchStatus: Record<PlatformType, PlatformStatus>
  isSearching: boolean
  searchQuery: string
  loading: boolean

  loadMaterials: (planId: string) => Promise<void>
  addMaterial: (m: Material) => void
  setMaterials: (mats: Material[]) => void
  reorderMaterials: (planId: string, mats: Material[]) => Promise<void>
  removeMaterial: (id: string) => void
  updateMaterial: (id: string, updates: Partial<Material>) => void
  updateMaterialStatus: (id: string, status: Material['status']) => void
  setSearchResults: (results: SearchResult[]) => void
  setPlatformStatus: (platform: PlatformType, status: PlatformStatus) => void
  setSearching: (v: boolean) => void
  setSearchQuery: (q: string) => void
  clearSearch: () => void
}

const DEFAULT_PLATFORM_STATUS: Record<PlatformType, PlatformStatus> = {
  bilibili: 'idle',
  youtube: 'idle',
  github: 'idle',
  xiaohongshu: 'idle',
  zhihu: 'idle',
  google: 'idle',
  wechat: 'idle',
  stackoverflow: 'idle',
  other: 'idle',
}

export const useSourceStore = create<SourceStore>()((set) => ({
  materials: [],
  searchResults: [],
  platformSearchStatus: { ...DEFAULT_PLATFORM_STATUS },
  isSearching: false,
  searchQuery: '',
  loading: false,

  loadMaterials: async (planId: string) => {
    set({ loading: true })
    try {
      const res = await fetch(`/api/plans/${planId}/materials`)
      if (!res.ok) throw new Error('加载失败')
      const data = await res.json()
      // 从 extraData 恢复搜索来源材料的详情到 searchStore
      // 兼容 snake_case（聊天搜索来源）和 camelCase（侧边栏搜索来源）两种 key 格式
      const searchDetails: SearchResult[] = []
      for (const m of data) {
        if (m.url && m.extraData && Object.keys(m.extraData).length > 0) {
          const e = m.extraData
          searchDetails.push({
            id: m.id,
            title: m.name,
            url: m.url,
            platform: m.type,
            description: e.description ?? '',
            qualityScore: e.qualityScore ?? e.quality_score ?? 0,
            recommendationReason: e.recommendationReason ?? e.recommendation_reason ?? '',
            contentSummary: e.contentSummary ?? e.content_summary,
            contentText: e.contentText ?? e.content_text,
            commentSummary: e.commentSummary ?? e.comment_summary,
            engagementMetrics: e.engagementMetrics ?? e.engagement_metrics,
            imageUrls: e.imageUrls ?? e.image_urls,
            topComments: e.topComments ?? e.comments_preview,
            keyPoints: e.keyPoints ?? e.key_points,
          })
        }
      }
      if (searchDetails.length > 0) {
        const { useSearchStore } = await import('./searchStore')
        useSearchStore.getState().saveResultDetails(searchDetails)
      }
      set({ materials: data, loading: false })
    } catch {
      set({ loading: false })
    }
  },

  addMaterial: (m) =>
    set((s) => ({ materials: [m, ...s.materials] })),

  setMaterials: (mats) => set({ materials: mats }),

  reorderMaterials: async (planId, mats) => {
    set({ materials: mats })
    try {
      await fetch(`/api/plans/${planId}/materials/reorder`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ orderedIds: mats.map(m => m.id) }),
      })
    } catch (e) {
      console.warn('reorder persist failed', e)
    }
  },

  removeMaterial: (id) =>
    set((s) => ({ materials: s.materials.filter((m) => m.id !== id) })),

  updateMaterial: (id, updates) =>
    set((s) => ({
      materials: s.materials.map((m) => (m.id === id ? { ...m, ...updates } : m)),
    })),

  updateMaterialStatus: (id, status) =>
    set((s) => ({
      materials: s.materials.map((m) => (m.id === id ? { ...m, status } : m)),
    })),

  setSearchResults: (results) => set({ searchResults: results }),

  setPlatformStatus: (platform, status) =>
    set((s) => ({
      platformSearchStatus: { ...s.platformSearchStatus, [platform]: status },
    })),

  setSearching: (v) => set({ isSearching: v }),
  setSearchQuery: (q) => set({ searchQuery: q }),

  clearSearch: () =>
    set({
      searchResults: [],
      platformSearchStatus: { ...DEFAULT_PLATFORM_STATUS },
      isSearching: false,
      searchQuery: '',
    }),
}))
