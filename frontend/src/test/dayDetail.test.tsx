/**
 * DayDetail 组件单元测试
 * 覆盖：任务渲染、checkbox toggle、按钮 3 种 disabled 状态、完成流程、已完成天展示
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { DayDetail } from '../components/studio/DayDetail'
import { useStudioStore } from '../store/studioStore'
import { useToastStore } from '../store/toastStore'
import type { DayProgress } from '../types'

// ─── 测试数据工厂 ───

function makeDay(overrides: Partial<DayProgress> = {}): DayProgress {
  return {
    dayNumber: 5,
    title: 'Transformer 注意力机制',
    completed: false,
    tasks: [
      { id: 't-1', type: 'reading', title: '阅读：Multi-Head Attention 原理', completed: false },
      { id: 't-2', type: 'video', title: '视频：3Blue1Brown 注意力可视化', completed: false },
      { id: 't-3', type: 'exercise', title: '练习：实现 Scaled Dot-Product', completed: false },
    ],
    ...overrides,
  }
}

function setStoreState(patch: Record<string, unknown>) {
  useStudioStore.setState(patch)
}

// ─── Mock fetch ───

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
  globalThis.fetch = fetchMock

  useStudioStore.setState({
    allDays: [makeDay()],
    currentDay: makeDay(),
    activePlanId: 'plan-123',
    selectedDay: 5,
    timelineStatus: 'idle',
  })

  useToastStore.setState({ message: null, type: 'info' })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('DayDetail', () => {
  // ─── 基本渲染 ───

  describe('基本渲染', () => {
    it('显示天标题和任务数量', () => {
      render(<DayDetail planId="plan-123" dayNumber={5} />)
      expect(screen.getByText(/Day 5: Transformer 注意力机制/)).toBeInTheDocument()
      expect(screen.getByText('0/3')).toBeInTheDocument()
    })

    it('渲染所有任务的 checkbox', () => {
      render(<DayDetail planId="plan-123" dayNumber={5} />)
      expect(screen.getByTestId('task-checkbox-0')).toBeInTheDocument()
      expect(screen.getByTestId('task-checkbox-1')).toBeInTheDocument()
      expect(screen.getByTestId('task-checkbox-2')).toBeInTheDocument()
    })

    it('显示任务类型 emoji', () => {
      render(<DayDetail planId="plan-123" dayNumber={5} />)
      // reading → 📖, video → 🎬, exercise → ✏️
      expect(screen.getByText('📖')).toBeInTheDocument()
      expect(screen.getByText('🎬')).toBeInTheDocument()
      expect(screen.getByText('✏️')).toBeInTheDocument()
    })

    it('dayNumber 不存在时返回 null', () => {
      const { container } = render(<DayDetail planId="plan-123" dayNumber={99} />)
      expect(container.innerHTML).toBe('')
    })
  })

  // ─── 按钮状态 ───

  describe('按钮 disabled 状态', () => {
    it('无任务时显示"暂无任务"且 disabled', () => {
      setStoreState({
        allDays: [makeDay({ tasks: [] })],
      })
      render(<DayDetail planId="plan-123" dayNumber={5} />)
      const btn = screen.getByTestId('complete-day-btn')
      expect(btn).toBeDisabled()
      expect(btn.textContent).toBe('暂无任务')
    })

    it('有未完成任务时显示"还有未完成的任务"且 disabled', () => {
      render(<DayDetail planId="plan-123" dayNumber={5} />)
      const btn = screen.getByTestId('complete-day-btn')
      expect(btn).toBeDisabled()
      expect(btn.textContent).toBe('还有未完成的任务')
    })

    it('所有任务完成时按钮可点击，显示"完成今天 ✅"', () => {
      setStoreState({
        allDays: [makeDay({
          tasks: [
            { id: 't-1', type: 'reading', title: '阅读', completed: true },
            { id: 't-2', type: 'video', title: '视频', completed: true },
          ],
        })],
      })
      render(<DayDetail planId="plan-123" dayNumber={5} />)
      const btn = screen.getByTestId('complete-day-btn')
      expect(btn).not.toBeDisabled()
      expect(btn.textContent).toBe('完成今天 ✅')
    })

    it('天已完成时显示"✅ 已完成"badge', () => {
      setStoreState({
        allDays: [makeDay({
          completed: true,
          tasks: [
            { id: 't-1', type: 'reading', title: '阅读', completed: true },
          ],
        })],
      })
      render(<DayDetail planId="plan-123" dayNumber={5} />)
      const btn = screen.getByTestId('complete-day-btn')
      expect(btn).toBeDisabled()
      expect(btn.textContent).toBe('✅ 已完成')
    })
  })

  // ─── Checkbox toggle ───

  describe('checkbox toggle', () => {
    it('点击 checkbox 调用 toggleTask 并持久化到后端', () => {
      render(<DayDetail planId="plan-123" dayNumber={5} />)
      const checkbox = screen.getByTestId('task-checkbox-0')
      fireEvent.click(checkbox)

      // 验证 store 中 task 状态翻转
      const updatedDay = useStudioStore.getState().allDays.find(d => d.dayNumber === 5)
      expect(updatedDay?.tasks[0].completed).toBe(true)

      // 验证后端持久化调用
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/plans/plan-123/progress/5/tasks',
        expect.objectContaining({ method: 'PUT' }),
      )
    })

    it('天已完成时 checkbox 被禁用', () => {
      setStoreState({
        allDays: [makeDay({
          completed: true,
          tasks: [{ id: 't-1', type: 'reading', title: '阅读', completed: true }],
        })],
      })
      render(<DayDetail planId="plan-123" dayNumber={5} />)
      const checkbox = screen.getByTestId('task-checkbox-0')
      expect(checkbox).toBeDisabled()
    })
  })

  // ─── 完成流程 ───

  describe('完成流程', () => {
    it('点击完成按钮调用 completeDayOptimistic + day-summary', async () => {
      // 所有任务已完成
      setStoreState({
        allDays: [makeDay({
          tasks: [
            { id: 't-1', type: 'reading', title: '阅读', completed: true },
          ],
        })],
      })

      fetchMock
        .mockResolvedValueOnce({ ok: true }) // completeDayOptimistic PUT
        .mockResolvedValueOnce({              // day-summary POST
          ok: true,
          json: async () => ({ title: '今日总结', content: '学习了注意力机制', createdAt: '2024-01-01' }),
        })

      render(<DayDetail planId="plan-123" dayNumber={5} />)
      const btn = screen.getByTestId('complete-day-btn')
      fireEvent.click(btn)

      // 等待异步完成
      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalledWith(
          '/api/plans/plan-123/progress/5',
          expect.objectContaining({ method: 'PUT' }),
        )
      })

      // day-summary 请求
      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalledWith(
          '/api/studio/day-summary',
          expect.objectContaining({ method: 'POST' }),
        )
      })
    })

    it('completeDayOptimistic 失败时显示 toast', async () => {
      setStoreState({
        allDays: [makeDay({
          tasks: [
            { id: 't-1', type: 'reading', title: '阅读', completed: true },
          ],
        })],
      })

      // PUT 失败
      fetchMock.mockResolvedValueOnce({ ok: false })

      render(<DayDetail planId="plan-123" dayNumber={5} />)
      fireEvent.click(screen.getByTestId('complete-day-btn'))

      await waitFor(() => {
        const toastState = useToastStore.getState()
        expect(toastState.message).toBe('保存失败，请重试')
        expect(toastState.type).toBe('error')
      })
    })
  })

  // ─── 可访问性 ───

  describe('可访问性', () => {
    it('任务列表有 role=list', () => {
      render(<DayDetail planId="plan-123" dayNumber={5} />)
      expect(screen.getByRole('list')).toBeInTheDocument()
    })

    it('checkbox 有 aria-label', () => {
      render(<DayDetail planId="plan-123" dayNumber={5} />)
      const checkbox = screen.getByTestId('task-checkbox-0')
      expect(checkbox).toHaveAttribute('aria-label', expect.stringContaining('阅读'))
    })

    it('完成按钮有 aria-label', () => {
      render(<DayDetail planId="plan-123" dayNumber={5} />)
      const btn = screen.getByTestId('complete-day-btn')
      expect(btn).toHaveAttribute('aria-label')
    })
  })
})
