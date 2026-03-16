/**
 * CyclePicker 单元测试
 * 验证渲染、策略文案切换、onChange 回调、可访问性
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { CyclePicker } from '../components/home/CyclePicker'

const defaultProps = {
  value: 14,
  onChange: vi.fn(),
}

describe('CyclePicker', () => {
  it('渲染默认值 14 和对应的中心数字', () => {
    render(<CyclePicker {...defaultProps} />)
    expect(screen.getByText('14')).toBeInTheDocument()
    expect(screen.getByText('天')).toBeInTheDocument()
  })

  it('渲染 slider 并设置正确的 min/max/value', () => {
    render(<CyclePicker {...defaultProps} />)
    const slider = screen.getByRole('slider')
    expect(slider).toHaveAttribute('min', '3')
    expect(slider).toHaveAttribute('max', '28')
    expect(slider).toHaveValue('14')
  })

  it('slider 有正确的 aria-label', () => {
    render(<CyclePicker {...defaultProps} />)
    const slider = screen.getByRole('slider')
    expect(slider).toHaveAttribute('aria-label', '学习周期天数')
    expect(slider).toHaveAttribute('aria-valuemin', '3')
    expect(slider).toHaveAttribute('aria-valuemax', '28')
    expect(slider).toHaveAttribute('aria-valuenow', '14')
  })

  it('拖动 slider 触发 onChange 回调', () => {
    const onChange = vi.fn()
    render(<CyclePicker value={14} onChange={onChange} />)
    const slider = screen.getByRole('slider')
    fireEvent.change(slider, { target: { value: '21' } })
    expect(onChange).toHaveBeenCalledWith(21)
  })

  it('短周期（3-7 天）显示密集冲刺模式', () => {
    render(<CyclePicker value={5} onChange={vi.fn()} />)
    expect(screen.getByText('5')).toBeInTheDocument()
    expect(screen.getByText(/密集冲刺模式/)).toBeInTheDocument()
    expect(screen.getByText(/短期集中突破核心内容/)).toBeInTheDocument()
  })

  it('中周期（8-14 天）显示稳步推进模式', () => {
    render(<CyclePicker value={10} onChange={vi.fn()} />)
    expect(screen.getByText('10')).toBeInTheDocument()
    expect(screen.getByText(/稳步推进模式/)).toBeInTheDocument()
    expect(screen.getByText(/适合系统性学习/)).toBeInTheDocument()
  })

  it('长周期（15-28 天）显示深度学习模式', () => {
    render(<CyclePicker value={21} onChange={vi.fn()} />)
    expect(screen.getByText('21')).toBeInTheDocument()
    expect(screen.getByText(/深度学习模式/)).toBeInTheDocument()
    expect(screen.getByText(/包含复习日和实践日/)).toBeInTheDocument()
  })

  it('边界值 3 天显示密集冲刺模式', () => {
    render(<CyclePicker value={3} onChange={vi.fn()} />)
    // value=3 与 min 标签重复，用 getAllByText 验证存在
    expect(screen.getAllByText('3').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/密集冲刺模式/)).toBeInTheDocument()
  })

  it('边界值 7 天仍为密集冲刺模式', () => {
    render(<CyclePicker value={7} onChange={vi.fn()} />)
    expect(screen.getByText(/密集冲刺模式/)).toBeInTheDocument()
  })

  it('边界值 8 天切换为稳步推进模式', () => {
    render(<CyclePicker value={8} onChange={vi.fn()} />)
    expect(screen.getByText(/稳步推进模式/)).toBeInTheDocument()
  })

  it('边界值 15 天切换为深度学习模式', () => {
    render(<CyclePicker value={15} onChange={vi.fn()} />)
    expect(screen.getByText(/深度学习模式/)).toBeInTheDocument()
  })

  it('边界值 28 天显示深度学习模式', () => {
    render(<CyclePicker value={28} onChange={vi.fn()} />)
    // value=28 与 max 标签重复，用 getAllByText 验证存在
    expect(screen.getAllByText('28').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/深度学习模式/)).toBeInTheDocument()
  })

  it('显示 min/max 标签', () => {
    render(<CyclePicker {...defaultProps} />)
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('28')).toBeInTheDocument()
  })
})
