/**
 * Property-Based Tests for studioStore
 * Property 2: currentDay 始终指向第一个未完成的 Day
 * Property 3: completeDay 后进度单调递增
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { useStudioStore } from '../store/studioStore'
import type { DayProgress } from '../types'

function makeDays(n: number): DayProgress[] {
  return Array.from({ length: n }, (_, i) => ({
    dayNumber: i + 1,
    title: `Day ${i + 1}`,
    completed: false,
    tasks: [
      { id: `t${i}-0`, title: `Task A`, type: 'reading' as const, completed: false },
      { id: `t${i}-1`, title: `Task B`, type: 'video' as const, completed: false },
    ],
  }))
}

function completedCount(days: DayProgress[]) {
  return days.filter((d) => d.completed).length
}

describe('studioStore — Property 2: currentDay points to first incomplete Day', () => {
  beforeEach(() => {
    useStudioStore.setState({
      allDays: [],
      currentDay: null,
      generatedContents: [],
      notes: [],
    })
  })

  it('after setLearningPlan, currentDay is the first day', () => {
    const days = makeDays(5)
    useStudioStore.getState().setLearningPlan(days)
    const { currentDay } = useStudioStore.getState()
    expect(currentDay?.dayNumber).toBe(1)
  })

  it('after completing day N, currentDay becomes day N+1', () => {
    for (let total = 2; total <= 5; total++) {
      const days = makeDays(total)
      useStudioStore.getState().setLearningPlan(days)
      for (let n = 1; n < total; n++) {
        useStudioStore.getState().completeDay(n)
        const { currentDay } = useStudioStore.getState()
        expect(currentDay?.dayNumber).toBe(n + 1)
      }
    }
  })

  it('after completing all days, currentDay is null', () => {
    const days = makeDays(3)
    useStudioStore.getState().setLearningPlan(days)
    for (let n = 1; n <= 3; n++) {
      useStudioStore.getState().completeDay(n)
    }
    expect(useStudioStore.getState().currentDay).toBeNull()
  })
})

describe('studioStore — Property 3: progress is monotonically increasing', () => {
  beforeEach(() => {
    useStudioStore.setState({ allDays: [], currentDay: null })
  })

  it('completedCount never decreases after each completeDay call', () => {
    const days = makeDays(5)
    useStudioStore.getState().setLearningPlan(days)
    let prev = 0
    for (let n = 1; n <= 5; n++) {
      useStudioStore.getState().completeDay(n)
      const curr = completedCount(useStudioStore.getState().allDays)
      expect(curr).toBeGreaterThanOrEqual(prev)
      prev = curr
    }
  })

  it('completeDay is idempotent — calling twice does not decrease progress', () => {
    const days = makeDays(3)
    useStudioStore.getState().setLearningPlan(days)
    useStudioStore.getState().completeDay(1)
    const after1 = completedCount(useStudioStore.getState().allDays)
    useStudioStore.getState().completeDay(1) // 重复调用
    const after2 = completedCount(useStudioStore.getState().allDays)
    expect(after2).toBe(after1)
  })
})
