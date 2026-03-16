/**
 * ConfirmDialog 单元测试
 * 验证渲染、交互（按钮/Escape/遮罩点击）、variant 样式、默认值
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ConfirmDialog } from '../components/ui/ConfirmDialog'

const defaultProps = {
  open: true,
  message: '确定要执行此操作吗？',
  onConfirm: vi.fn(),
  onCancel: vi.fn(),
}

describe('ConfirmDialog', () => {
  it('open=false 时不渲染任何内容', () => {
    const { container } = render(
      <ConfirmDialog {...defaultProps} open={false} />,
    )
    expect(container.innerHTML).toBe('')
  })

  it('渲染默认 title、message 和按钮文案', () => {
    render(<ConfirmDialog {...defaultProps} />)
    // title 在 heading 中
    expect(screen.getByRole('heading', { name: '确认' })).toBeInTheDocument()
    expect(screen.getByText('确定要执行此操作吗？')).toBeInTheDocument()
    // 确认按钮和取消按钮
    expect(screen.getByRole('button', { name: '确认' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '取消' })).toBeInTheDocument()
  })

  it('支持自定义 title / confirmText / cancelText', () => {
    render(
      <ConfirmDialog
        {...defaultProps}
        title="删除确认"
        confirmText="删除"
        cancelText="算了"
      />,
    )
    expect(screen.getByText('删除确认')).toBeInTheDocument()
    expect(screen.getByText('删除')).toBeInTheDocument()
    expect(screen.getByText('算了')).toBeInTheDocument()
  })

  it('点击确认按钮触发 onConfirm', () => {
    const onConfirm = vi.fn()
    render(<ConfirmDialog {...defaultProps} onConfirm={onConfirm} />)
    fireEvent.click(screen.getByRole('button', { name: '确认' }))
    expect(onConfirm).toHaveBeenCalledOnce()
  })

  it('点击取消按钮触发 onCancel', () => {
    const onCancel = vi.fn()
    render(<ConfirmDialog {...defaultProps} onCancel={onCancel} />)
    fireEvent.click(screen.getByText('取消'))
    expect(onCancel).toHaveBeenCalledOnce()
  })

  it('点击遮罩触发 onCancel', () => {
    const onCancel = vi.fn()
    render(<ConfirmDialog {...defaultProps} onCancel={onCancel} />)
    fireEvent.click(screen.getByTestId('confirm-backdrop'))
    expect(onCancel).toHaveBeenCalledOnce()
  })

  it('Escape 键触发 onCancel', () => {
    const onCancel = vi.fn()
    render(<ConfirmDialog {...defaultProps} onCancel={onCancel} />)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onCancel).toHaveBeenCalledOnce()
  })

  it('danger variant 确认按钮包含红色样式', () => {
    render(
      <ConfirmDialog {...defaultProps} variant="danger" confirmText="删除" />,
    )
    const btn = screen.getByText('删除')
    expect(btn.className).toContain('bg-red-600')
  })

  it('default variant 确认按钮包含蓝色样式', () => {
    render(<ConfirmDialog {...defaultProps} />)
    const btn = screen.getByRole('button', { name: '确认' })
    expect(btn.className).toContain('bg-blue-600')
  })

  it('打开时 body overflow 设为 hidden', () => {
    const { unmount } = render(<ConfirmDialog {...defaultProps} />)
    expect(document.body.style.overflow).toBe('hidden')
    unmount()
  })

  it('设置了正确的 aria 属性', () => {
    render(<ConfirmDialog {...defaultProps} />)
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog).toHaveAttribute('aria-labelledby', 'confirm-dialog-title')
  })
})
