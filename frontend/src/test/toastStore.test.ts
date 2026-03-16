/**
 * toastStore 单元测试
 * 验证 show/hide/自动消失/连续调用重置定时器
 */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { useToastStore } from '../store/toastStore'

describe('toastStore', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    useToastStore.getState().hide()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('初始状态 message 为 null', () => {
    expect(useToastStore.getState().message).toBeNull()
  })

  it('show() 设置 message 和默认 type=info', () => {
    useToastStore.getState().show('测试消息')
    const state = useToastStore.getState()
    expect(state.message).toBe('测试消息')
    expect(state.type).toBe('info')
  })

  it('show() 支持自定义 type', () => {
    useToastStore.getState().show('错误', 'error')
    expect(useToastStore.getState().type).toBe('error')

    useToastStore.getState().show('成功', 'success')
    expect(useToastStore.getState().type).toBe('success')
  })

  it('3 秒后自动消失', () => {
    useToastStore.getState().show('会消失的消息')
    expect(useToastStore.getState().message).toBe('会消失的消息')

    vi.advanceTimersByTime(2999)
    expect(useToastStore.getState().message).toBe('会消失的消息')

    vi.advanceTimersByTime(1)
    expect(useToastStore.getState().message).toBeNull()
  })

  it('hide() 立即清除 message 并取消定时器', () => {
    useToastStore.getState().show('手动关闭')
    useToastStore.getState().hide()
    expect(useToastStore.getState().message).toBeNull()

    // 3 秒后不会再触发任何变化（定时器已清除）
    vi.advanceTimersByTime(3000)
    expect(useToastStore.getState().message).toBeNull()
  })

  it('连续调用 show() 重置定时器', () => {
    useToastStore.getState().show('第一条')
    vi.advanceTimersByTime(2000) // 过了 2 秒

    useToastStore.getState().show('第二条')
    // 第一条的定时器已被清除，第二条从头计时
    vi.advanceTimersByTime(2000) // 距第二条 show 过了 2 秒
    expect(useToastStore.getState().message).toBe('第二条')

    vi.advanceTimersByTime(1000) // 距第二条 show 过了 3 秒
    expect(useToastStore.getState().message).toBeNull()
  })
})
