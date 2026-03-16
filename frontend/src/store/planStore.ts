import { create } from 'zustand'
import type { LearningPlan } from '../types'

interface PlanStore {
  plans: LearningPlan[]
  currentPlanId: string | null
  loading: boolean
  error: string | null

  loadPlans: () => Promise<void>
  setPlans: (plans: LearningPlan[]) => void
  addPlan: (plan: LearningPlan) => void
  updatePlan: (id: string, patch: Partial<LearningPlan>) => void
  deletePlan: (id: string) => void
  setCurrentPlan: (id: string | null) => void
  getCurrentPlan: () => LearningPlan | null
}

export const usePlanStore = create<PlanStore>()((set, get) => ({
  plans: [],
  currentPlanId: null,
  loading: false,
  error: null,

  loadPlans: async () => {
    set({ loading: true, error: null })
    try {
      const res = await fetch('/api/plans')
      if (!res.ok) throw new Error('加载失败')
      const data = await res.json()
      set({ plans: data, loading: false })
    } catch (e) {
      set({ error: '加载规划列表失败', loading: false })
    }
  },

  setPlans: (plans) => set({ plans }),

  addPlan: (plan) =>
    set((s) => ({ plans: [...s.plans, plan] })),

  updatePlan: (id, patch) =>
    set((s) => ({
      plans: s.plans.map((p) => (p.id === id ? { ...p, ...patch } : p)),
    })),

  deletePlan: (id) =>
    set((s) => ({
      plans: s.plans.filter((p) => p.id !== id),
      currentPlanId: s.currentPlanId === id ? null : s.currentPlanId,
    })),

  setCurrentPlan: (id) => set({ currentPlanId: id }),

  getCurrentPlan: () => {
    const { plans, currentPlanId } = get()
    return plans.find((p) => p.id === currentPlanId) ?? null
  },
}))
