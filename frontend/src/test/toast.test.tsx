/**
 * Toast 组件单元测试
 * 验证渲染、类型样式、点击关闭、动画状态
 */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { useToastStore } from '../store/toastStore'
import { Toast } from '../components/ui/Toast'

describe('Toast 组件', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    useToastStore.getState().hide()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('message 为 null 时不渲染任何内容', () => {
    const { container } = render(<Toast />)
    expect(container.querySelector('[role="alert"]')).toBeNull()
  })

  it('show() 后渲染 toast 内容', () => {
    render(<Toast />)
    act(() => {
      useToastStore.getState().show('操作成功', 'success')
    })
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText('操作成功')).toBeInTheDocument()
  })

  it('success 类型显示 ✓ 图标', () => {
    render(<Toast />)
    act(() => {
      useToastStore.getState().show('保存成功', 'success')
    })
    expect(screen.getByText('✓')).toBeInTheDocument()
  })

  it('error 类型显示 ✕ 图标', () => {
    render(<Toast />)
    act(() => {
      useToastStore.getState().show('保存失败', 'error')
    })
    expect(screen.getByText('✕')).toBeInTheDocument()
  })

  it('info 类型显示 ℹ 图标', () => {
    render(<Toast />)
    act(() => {
      useToastStore.getState().show('提示信息')
    })
    expect(screen.getByText('ℹ')).toBeInTheDocument()
  })

  it('点击 toast 调用 hide() 关闭', () => {
    render(<Toast />)
    act(() => {
      useToastStore.getState().show('点击关闭')
    })
    fireEvent.click(screen.getByRole('alert'))
    // hide() 将 message 设为 null，组件进入退出动画
    expect(useToastStore.getState().message).toBeNull()
  })

  it('具有正确的 accessibility 属性', () => {
    render(<Toast />)
    act(() => {
      useToastStore.getState().show('无障碍测试')
    })
    const alert = screen.getByRole('alert')
    expect(alert).toHaveAttribute('aria-live', 'assertive')
  })

  it('3 秒后 store 自动清除 message', () => {
    render(<Toast />)
    act(() => {
      useToastStore.getState().show('自动消失')
    })
    expect(screen.getByText('自动消失')).toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(3000)
    })
    // store message 已清除
    expect(useToastStore.getState().message).toBeNull()
  })
})
