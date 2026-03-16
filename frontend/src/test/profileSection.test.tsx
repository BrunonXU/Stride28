/**
 * ProfileSection 单元测试
 * 验证折叠/展开、字段渲染、pill 选择、textarea 输入、回调触发
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ProfileSection } from '../components/home/ProfileSection'
import type { LearnerProfile } from '../types'

const baseProps = {
  expanded: false,
  onToggle: vi.fn(),
  profile: {} as Partial<LearnerProfile>,
  onChange: vi.fn(),
}

describe('ProfileSection', () => {
  // --- 折叠/展开 ---

  it('折叠状态下内容区 grid-template-rows 为 0fr', () => {
    const { container } = render(<ProfileSection {...baseProps} expanded={false} />)
    const grid = container.querySelector('.grid') as HTMLElement
    expect(grid.style.gridTemplateRows).toBe('0fr')
  })

  it('展开状态下内容区 grid-template-rows 为 1fr', () => {
    const { container } = render(<ProfileSection {...baseProps} expanded={true} />)
    const grid = container.querySelector('.grid') as HTMLElement
    expect(grid.style.gridTemplateRows).toBe('1fr')
  })

  it('展开状态下显示所有字段标签', () => {
    render(<ProfileSection {...baseProps} expanded={true} />)
    expect(screen.getByText(/学习目的/)).toBeInTheDocument()
    expect(screen.getByText(/当前水平/)).toBeInTheDocument()
    expect(screen.getByText(/每日可用时间/)).toBeInTheDocument()
    expect(screen.getByText(/个人背景/)).toBeInTheDocument()
  })

  it('header 按钮的 aria-expanded 反映展开状态', () => {
    const { rerender } = render(<ProfileSection {...baseProps} expanded={false} />)
    const btn = screen.getByRole('button', { name: /学习者画像/ })
    expect(btn).toHaveAttribute('aria-expanded', 'false')

    rerender(<ProfileSection {...baseProps} expanded={true} />)
    expect(btn).toHaveAttribute('aria-expanded', 'true')
  })

  // --- Toggle 回调 ---

  it('点击 header 触发 onToggle', () => {
    const onToggle = vi.fn()
    render(<ProfileSection {...baseProps} onToggle={onToggle} />)
    fireEvent.click(screen.getByRole('button', { name: /学习者画像/ }))
    expect(onToggle).toHaveBeenCalledOnce()
  })

  // --- Pill 选择 ---

  it('点击水平 pill 触发 onChange（level）', () => {
    const onChange = vi.fn()
    render(
      <ProfileSection {...baseProps} expanded={true} onChange={onChange} profile={{}} />,
    )
    fireEvent.click(screen.getByText('入门级'))
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ level: '入门级' }))
  })

  it('点击时间 pill 触发 onChange（dailyHours）', () => {
    const onChange = vi.fn()
    render(
      <ProfileSection {...baseProps} expanded={true} onChange={onChange} profile={{}} />,
    )
    fireEvent.click(screen.getByText('2小时'))
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ dailyHours: '2小时' }))
  })

  it('已选中的 level pill 有高亮样式', () => {
    render(
      <ProfileSection
        {...baseProps}
        expanded={true}
        profile={{ level: '中级' }}
      />,
    )
    const pill = screen.getByText('中级')
    expect(pill.className).toContain('bg-orange-50')
    expect(pill.className).toContain('border-blue-400')
  })

  it('已选中的 dailyHours pill 有高亮样式', () => {
    render(
      <ProfileSection
        {...baseProps}
        expanded={true}
        profile={{ dailyHours: '1小时' }}
      />,
    )
    const pill = screen.getByText('1小时')
    expect(pill.className).toContain('bg-orange-50')
    expect(pill.className).toContain('border-orange-400')
  })

  // --- Textarea 输入 ---

  it('goal textarea 输入触发 onChange', () => {
    const onChange = vi.fn()
    render(
      <ProfileSection {...baseProps} expanded={true} onChange={onChange} profile={{}} />,
    )
    const textarea = screen.getByPlaceholderText(/准备考研/)
    fireEvent.change(textarea, { target: { value: '学 Rust' } })
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ goal: '学 Rust' }))
  })

  it('background textarea 输入触发 onChange', () => {
    const onChange = vi.fn()
    render(
      <ProfileSection {...baseProps} expanded={true} onChange={onChange} profile={{}} />,
    )
    const textarea = screen.getByPlaceholderText(/大三计算机/)
    fireEvent.change(textarea, { target: { value: '前端工程师' } })
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ background: '前端工程师' }),
    )
  })

  // --- 不含 duration ---

  it('不渲染 duration / 学习周期字段', () => {
    render(<ProfileSection {...baseProps} expanded={true} />)
    expect(screen.queryByText(/学习周期/)).not.toBeInTheDocument()
  })
})
