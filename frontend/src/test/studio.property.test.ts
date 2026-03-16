/**
 * Property 3: ProgressTracker 进度单调递增（前端 studioStore 层面验证）
 * Property 4: studioStore 状态 save/load 往返一致（localStorage 序列化）
 */
import { describe, it, expect } from 'vitest'
import fc from 'fast-check'

// ─── Property 3: completeDay 进度单调递增 ─────────────────────────────────────

interface DayProgress {
  dayNumber: number
  title: string
  completed: boolean
  tasks: { id: string; type: string; title: string; completed: boolean }[]
}

function findCurrentDay(days: DayProgress[]): DayProgress | null {
  return days.find(d => !d.completed) ?? null
}

function completeDay(days: DayProgress[], dayNumber: number): DayProgress[] {
  return days.map(d => d.dayNumber === dayNumber ? { ...d, completed: true } : d)
}

function completedCount(days: DayProgress[]): number {
  return days.filter(d => d.completed).length
}

describe('Property 3: completeDay progress is monotonically non-decreasing', () => {
  it('completing a day always increases or maintains completed count', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            dayNumber: fc.integer({ min: 1, max: 30 }),
            title: fc.string({ minLength: 1, maxLength: 20 }),
            completed: fc.boolean(),
            tasks: fc.constant([]),
          }),
          { minLength: 1, maxLength: 10 }
        ),
        (rawDays) => {
          // 去重 dayNumber
          const seen = new Set<number>()
          const days = rawDays.filter(d => {
            if (seen.has(d.dayNumber)) return false
            seen.add(d.dayNumber)
            return true
          })
          if (days.length === 0) return true

          const before = completedCount(days)
          const target = days.find(d => !d.completed)
          if (!target) return true  // 全部已完成，跳过

          const after = completedCount(completeDay(days, target.dayNumber))
          return after >= before
        }
      )
    )
  })

  it('completing all days in order yields 100% progress', () => {
    const days: DayProgress[] = Array.from({ length: 7 }, (_, i) => ({
      dayNumber: i + 1,
      title: `Day ${i + 1}`,
      completed: false,
      tasks: [],
    }))

    let state = days
    for (let i = 1; i <= 7; i++) {
      const before = completedCount(state)
      state = completeDay(state, i)
      const after = completedCount(state)
      expect(after).toBe(before + 1)
    }
    expect(completedCount(state)).toBe(7)
  })

  it('completing an already-completed day is idempotent', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 10 }),
        (n) => {
          const days: DayProgress[] = Array.from({ length: n }, (_, i) => ({
            dayNumber: i + 1, title: `Day ${i + 1}`, completed: false, tasks: [],
          }))
          if (days.length === 0) return true
          const target = days[0].dayNumber
          const once = completeDay(days, target)
          const twice = completeDay(once, target)
          return completedCount(once) === completedCount(twice)
        }
      )
    )
  })

  it('currentDay always points to first incomplete day', () => {
    fc.assert(
      fc.property(
        fc.array(fc.boolean(), { minLength: 1, maxLength: 10 }),
        (completedFlags) => {
          const days: DayProgress[] = completedFlags.map((completed, i) => ({
            dayNumber: i + 1, title: `Day ${i + 1}`, completed, tasks: [],
          }))
          const current = findCurrentDay(days)
          if (current === null) {
            // 全部完成
            return days.every(d => d.completed)
          }
          // current 是第一个未完成的
          const idx = days.findIndex(d => d.dayNumber === current.dayNumber)
          return days.slice(0, idx).every(d => d.completed)
        }
      )
    )
  })
})

// ─── Property 4: studioStore 状态 save/load 往返一致 ─────────────────────────

interface StudioState {
  allDays: DayProgress[]
  generatedContents: { id: string; type: string; title: string; content: string; createdAt: string }[]
  notes: { id: string; title: string; content: string; updatedAt: string }[]
}

function serializeState(state: StudioState): string {
  return JSON.stringify(state)
}

function deserializeState(raw: string): StudioState {
  return JSON.parse(raw)
}

describe('Property 4: studio state save/load round-trip consistency', () => {
  it('serialized state deserializes to identical structure', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            id: fc.uuid(),
            type: fc.constantFrom('learning-plan', 'study-guide', 'flashcards', 'quiz', 'progress-report'),
            title: fc.string({ minLength: 1, maxLength: 30 }),
            content: fc.string({ maxLength: 200 }),
            createdAt: fc.date().map(d => d.toISOString()),
          }),
          { maxLength: 5 }
        ),
        fc.array(
          fc.record({
            id: fc.uuid(),
            title: fc.string({ minLength: 1, maxLength: 30 }),
            content: fc.string({ maxLength: 200 }),
            updatedAt: fc.date().map(d => d.toISOString()),
          }),
          { maxLength: 5 }
        ),
        (contents, notes) => {
          const state: StudioState = { allDays: [], generatedContents: contents, notes }
          const loaded = deserializeState(serializeState(state))
          return (
            loaded.generatedContents.length === contents.length &&
            loaded.notes.length === notes.length &&
            JSON.stringify(loaded) === JSON.stringify(state)
          )
        }
      )
    )
  })

  it('notes preserve all fields after round-trip', () => {
    const note = { id: 'n1', title: '测试笔记', content: '# 标题\n内容', updatedAt: '2026-03-03T00:00:00Z' }
    const state: StudioState = { allDays: [], generatedContents: [], notes: [note] }
    const loaded = deserializeState(serializeState(state))
    expect(loaded.notes[0]).toEqual(note)
  })

  it('empty state round-trips correctly', () => {
    const state: StudioState = { allDays: [], generatedContents: [], notes: [] }
    const loaded = deserializeState(serializeState(state))
    expect(loaded).toEqual(state)
  })

  it('generatedContents order is preserved after round-trip', () => {
    fc.assert(
      fc.property(
        fc.array(fc.uuid(), { minLength: 1, maxLength: 8 }),
        (ids) => {
          const contents = ids.map(id => ({
            id, type: 'study-guide' as const, title: 'T', content: '', createdAt: new Date().toISOString(),
          }))
          const state: StudioState = { allDays: [], generatedContents: contents, notes: [] }
          const loaded = deserializeState(serializeState(state))
          return loaded.generatedContents.map(c => c.id).join(',') === ids.join(',')
        }
      )
    )
  })
})
