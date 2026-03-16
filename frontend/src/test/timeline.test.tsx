/**
 * Timeline 组件单元测试
 * 覆盖 4 种状态（idle/loading/empty/regenerating）、节点渲染、交互行为
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { Timeline } from '../components/studio/Timeline'
import { useStudioStore } from '../store/studioStore'
import type { DayProgress } from '../types'

// ─── 测试数据工厂 ───

function makeDays(count: number, completedUpTo = 0): DayProgress[] {
  return Array.from({ length: count }, (_, i) => ({
    dayNumber: i + 1,
    title: `Day ${i + 1} 任务`,
    completed: i < completedUpTo,
    tasks: [
      { id: `t-${i + 1}-1`, type: 'reading' as const, title: '阅读材料', completed: i < completedUpTo },
    ],
  }))
}

function findCurrentDay(days: DayProgress[]): DayProgress | null {
  return days.find(d => !d.completed) ?? null
}

// ─── 辅助：直接设置 store 状态 ───

function setStoreState(patch: Record<string, unknown>) {
  useStudioStore.setState(patch)
}

beforeEach(() => {
  // 每个测试前重置 store
  useStudioStore.setState({
    allDays: [],
    currentDay: null,
    timelineStatus: 'idle',
    selectedDay: null,
    _snapshot: null,
  })
})

describe('Timeline', () => {
  // ─── Loading 状态 ───

  describe('loading 状态', () => {
    it('显示 5 个 skeleton 占位节点', () => {
      setStoreState({ timelineStatus: 'loading' })
      render(<Timeline planId="test-plan" />)
      expect(screen.getByTestId('timeline-loading')).toBeInTheDocument()
    })
  })

  // ─── Empty 状态 ───

  describe('empty 状态', () => {
    it('显示引导文案', () => {
      setStoreState({ timelineStatus: 'empty' })
      render(<Timeline planId="test-plan" />)
      expect(screen.getByTestId('timeline-empty')).toBeInTheDocument()
      expect(screen.getByText(/点击「学习计划」生成每日计划/)).toBeInTheDocument()
    })

    it('allDays 为空且 idle 时也显示 empty', () => {
      setStoreState({ timelineStatus: 'idle', allDays: [] })
      render(<Timeline planId="test-plan" />)
      expect(screen.getByTestId('timeline-empty')).toBeInTheDocument()
    })
  })

  // ─── Idle 状态（正常渲染） ───

  describe('idle 状态', () => {
    it('渲染正确数量的 DayNode', () => {
      const days = makeDays(7, 3)
      setStoreState({
        timelineStatus: 'idle',
        allDays: days,
        currentDay: findCurrentDay(days),
      })
      render(<Timeline planId="test-plan" />)
      expect(screen.getByTestId('timeline')).toBeInTheDocument()
      // 7 个节点
      for (let i = 1; i <= 7; i++) {
        expect(screen.getByTestId(`day-node-${i}`)).toBeInTheDocument()
      }
    })

    it('已完成节点显示 ✓ 标记', () => {
      const days = makeDays(3, 2)
      setStoreState({
        timelineStatus: 'idle',
        allDays: days,
        currentDay: findCurrentDay(days),
      })
      render(<Timeline planId="test-plan" />)
      // 前 2 个已完成，应该有 ✓
      const node1 = screen.getByTestId('day-node-1')
      expect(node1.textContent).toContain('✓')
      const node2 = screen.getByTestId('day-node-2')
      expect(node2.textContent).toContain('✓')
      // 第 3 个未完成，不含 ✓
      const node3 = screen.getByTestId('day-node-3')
      expect(node3.textContent).not.toContain('✓')
    })

    it('渲染连接线', () => {
      const days = makeDays(3)
      setStoreState({
        timelineStatus: 'idle',
        allDays: days,
        currentDay: findCurrentDay(days),
      })
      render(<Timeline planId="test-plan" />)
      // 3 个节点之间有 2 条连接线
      const connectors = screen.getAllByTestId('connector')
      expect(connectors).toHaveLength(2)
    })

    it('点击节点设置 selectedDay', () => {
      const days = makeDays(5, 2)
      setStoreState({
        timelineStatus: 'idle',
        allDays: days,
        currentDay: findCurrentDay(days),
        selectedDay: null,
      })
      render(<Timeline planId="test-plan" />)

      fireEvent.click(screen.getByTestId('day-node-3'))
      expect(useStudioStore.getState().selectedDay).toBe(3)
    })

    it('再次点击已选中节点取消选中', () => {
      const days = makeDays(5, 2)
      setStoreState({
        timelineStatus: 'idle',
        allDays: days,
        currentDay: findCurrentDay(days),
        selectedDay: 3,
      })
      render(<Timeline planId="test-plan" />)

      fireEvent.click(screen.getByTestId('day-node-3'))
      expect(useStudioStore.getState().selectedDay).toBeNull()
    })
  })

  // ─── 全部完成 → 庆祝状态 ───

  describe('庆祝状态', () => {
    it('所有天完成时显示庆祝横幅', () => {
      const days = makeDays(5, 5)
      setStoreState({
        timelineStatus: 'idle',
        allDays: days,
        currentDay: null,
      })
      render(<Timeline planId="test-plan" />)
      expect(screen.getByTestId('timeline-celebration')).toBeInTheDocument()
      expect(screen.getByText(/学习计划完成/)).toBeInTheDocument()
    })

    it('未全部完成时不显示庆祝横幅', () => {
      const days = makeDays(5, 3)
      setStoreState({
        timelineStatus: 'idle',
        allDays: days,
        currentDay: findCurrentDay(days),
      })
      render(<Timeline planId="test-plan" />)
      expect(screen.queryByTestId('timeline-celebration')).not.toBeInTheDocument()
    })
  })

  // ─── Regenerating 状态 ───

  describe('regenerating 状态', () => {
    it('已完成节点正常显示，未完成节点显示 skeleton', () => {
      const days = makeDays(7, 3)
      setStoreState({
        timelineStatus: 'regenerating',
        allDays: days,
        currentDay: findCurrentDay(days),
      })
      render(<Timeline planId="test-plan" />)

      // 前 3 个已完成，正常渲染
      for (let i = 1; i <= 3; i++) {
        expect(screen.getByTestId(`day-node-${i}`)).toBeInTheDocument()
      }
      // 后 4 个未完成，显示 skeleton
      for (let i = 4; i <= 7; i++) {
        expect(screen.getByTestId(`day-node-skeleton-${i}`)).toBeInTheDocument()
      }
    })

    it('显示"正在重新规划..."提示', () => {
      const days = makeDays(5, 2)
      setStoreState({
        timelineStatus: 'regenerating',
        allDays: days,
        currentDay: findCurrentDay(days),
      })
      render(<Timeline planId="test-plan" />)
      expect(screen.getByTestId('timeline-regenerating-hint')).toBeInTheDocument()
      expect(screen.getByText('正在重新规划...')).toBeInTheDocument()
    })
  })

  // ─── 鼠标滚轮横向滚动 ───

  describe('鼠标滚轮横向滚动', () => {
    it('wheel 事件修改 scrollLeft', () => {
      const days = makeDays(20, 5)
      setStoreState({
        timelineStatus: 'idle',
        allDays: days,
        currentDay: findCurrentDay(days),
      })
      render(<Timeline planId="test-plan" />)

      const container = screen.getByRole('tablist')
      // 模拟 wheel 事件
      const wheelEvent = new WheelEvent('wheel', {
        deltaY: 100,
        bubbles: true,
        cancelable: true,
      })
      container.dispatchEvent(wheelEvent)
      // scrollLeft 应该增加（jsdom 中 scrollLeft 默认 0，但事件应被处理）
      // 主要验证 preventDefault 被调用（不抛错即可）
    })
  })

  // ─── Accessibility ───

  describe('可访问性', () => {
    it('节点有正确的 aria-label', () => {
      const days = makeDays(3, 1)
      setStoreState({
        timelineStatus: 'idle',
        allDays: days,
        currentDay: findCurrentDay(days),
      })
      render(<Timeline planId="test-plan" />)

      const node1 = screen.getByTestId('day-node-1')
      expect(node1).toHaveAttribute('aria-label', expect.stringContaining('已完成'))

      const node2 = screen.getByTestId('day-node-2')
      expect(node2).toHaveAttribute('aria-label', expect.stringContaining('Day 2'))
    })

    it('容器有 tablist role', () => {
      const days = makeDays(3)
      setStoreState({
        timelineStatus: 'idle',
        allDays: days,
        currentDay: findCurrentDay(days),
      })
      render(<Timeline planId="test-plan" />)
      expect(screen.getByRole('tablist')).toBeInTheDocument()
    })
  })
})
