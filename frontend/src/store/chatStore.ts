import { create } from 'zustand'
import type { ChatMessage, Material, InlineSearchResult } from '../types'

/** 聊天输入框中附加的材料引用 */
export interface AttachedMaterial {
  id: string
  name: string
  platform: Material['type']
}

interface ChatStore {
  messages: ChatMessage[]
  suggestedQuestions: string[]
  isStreaming: boolean
  streamingContent: string
  loading: boolean
  /** 当前输入框附加的材料列表 */
  attachedMaterials: AttachedMaterial[]
  /** 当前流式对话中的搜索结果（search_needed 分支） */
  searchResults: InlineSearchResult[] | null
  /** 当前状态消息（"正在搜索..."等） */
  statusMessage: string | null
  /** 当前状态所属节点（classify/search/tutor/synthesis） */
  statusNode: string | null
  /** 搜索子阶段（searching/filtering/extracting/evaluating），仅 search 节点有效 */
  searchStage: string | null

  loadMessages: (planId: string) => Promise<void>
  addMessage: (msg: ChatMessage) => void
  setMessages: (msgs: ChatMessage[]) => void
  appendChunk: (chunk: string) => void
  finalizeStream: (sources?: ChatMessage['sources']) => void
  setStreaming: (v: boolean) => void
  setSuggestedQuestions: (qs: string[]) => void
  clearMessages: (planId?: string) => void
  getHistory: () => ChatMessage[]
  /** 附加材料到输入框 */
  attachMaterial: (m: AttachedMaterial) => void
  /** 移除附加的材料 */
  detachMaterial: (id: string) => void
  /** 清空附加材料 */
  clearAttached: () => void
  /** 设置搜索结果 */
  setSearchResults: (results: InlineSearchResult[] | null) => void
  /** 设置状态消息 */
  setStatusMessage: (msg: string | null, node?: string | null, stage?: string | null) => void
}

export const useChatStore = create<ChatStore>()((set, get) => ({
  messages: [],
  suggestedQuestions: [],
  isStreaming: false,
  streamingContent: '',
  loading: false,
  attachedMaterials: [],
  searchResults: null,
  statusMessage: null,
  statusNode: null,
  searchStage: null,

  loadMessages: async (planId: string) => {
    set({ loading: true })
    try {
      const res = await fetch(`/api/plans/${planId}/messages`)
      if (!res.ok) throw new Error('加载失败')
      const data = await res.json()
      set({ messages: data, loading: false })
    } catch {
      set({ loading: false })
    }
  },

  addMessage: (msg) =>
    set((s) => ({ messages: [...s.messages, msg] })),

  setMessages: (msgs) => set({ messages: msgs }),

  appendChunk: (chunk) =>
    set((s) => ({ streamingContent: s.streamingContent + chunk })),

  finalizeStream: (sources) =>
    set((s) => {
      if (!s.streamingContent.trim()) {
        return { streamingContent: '', isStreaming: false, statusMessage: null, statusNode: null, searchStage: null }
      }
      const assistantMsg: ChatMessage = {
        id: `msg-${Date.now()}`,
        role: 'assistant',
        content: s.streamingContent,
        createdAt: new Date().toISOString(),
        sources,
        searchResults: s.searchResults ?? undefined,
      }
      return {
        messages: [...s.messages, assistantMsg],
        streamingContent: '',
        isStreaming: false,
        statusMessage: null,
        statusNode: null,
        searchStage: null,
      }
    }),

  setStreaming: (v) => set({ isStreaming: v }),
  setSuggestedQuestions: (qs) => set({ suggestedQuestions: qs }),
  clearMessages: (planId) => {
    // 乐观更新：立即清空前端状态
    set({ messages: [], streamingContent: '', suggestedQuestions: [] })
    // 通知后端清空消息（触发强制摘要 + 删除 DB 记录）
    if (planId) {
      fetch(`/api/plans/${planId}/messages`, { method: 'DELETE' }).catch((e) =>
        console.warn('[chatStore] 清空消息 API 调用失败:', e)
      )
    }
  },

  getHistory: () => {
    const { messages } = get()
    return messages.slice(-12)
  },

  attachMaterial: (m) =>
    set((s) => {
      if (s.attachedMaterials.some(a => a.id === m.id)) return s
      return { attachedMaterials: [...s.attachedMaterials, m] }
    }),

  detachMaterial: (id) =>
    set((s) => ({ attachedMaterials: s.attachedMaterials.filter(a => a.id !== id) })),

  clearAttached: () => set({ attachedMaterials: [] }),

  setSearchResults: (results) => set({ searchResults: results }),
  setStatusMessage: (msg, node, stage) => set({ statusMessage: msg, statusNode: node ?? null, searchStage: stage ?? null }),
}))
