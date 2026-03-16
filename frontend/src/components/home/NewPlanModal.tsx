import React, { useState, useCallback } from 'react'
import { Modal } from '../ui/Modal'
import { Button } from '../ui/Button'
import { CyclePicker } from './CyclePicker'
import { ProfileSection } from './ProfileSection'
import type { LearnerProfile } from '../../types'

export type CreateMode = 'pdf' | 'link' | 'topic' | null

interface NewPlanModalProps {
  open: boolean
  onClose: () => void
  onCreate: (
    title: string,
    mode: CreateMode,
    input: string,
    cycleDays: number,
    profile?: Partial<LearnerProfile>
  ) => Promise<void>
}

export const NewPlanModal: React.FC<NewPlanModalProps> = ({ open, onClose, onCreate }) => {
  const [title, setTitle] = useState('')
  const [mode, setMode] = useState<CreateMode>(null)
  const [input, setInput] = useState('')
  const [cycleDays, setCycleDays] = useState(14)
  const [profileExpanded, setProfileExpanded] = useState(false)
  const [profile, setProfile] = useState<Partial<LearnerProfile>>({})
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const resetForm = useCallback(() => {
    setTitle('')
    setMode(null)
    setInput('')
    setCycleDays(14)
    setProfileExpanded(false)
    setProfile({})
    setError(null)
    setSubmitting(false)
  }, [])

  const handleCreate = async () => {
    if (!mode) return
    setSubmitting(true)
    setError(null)
    try {
      await onCreate(
        title || '新建学习规划',
        mode,
        input,
        cycleDays,
        profileExpanded ? { ...profile, duration: cycleDays } : undefined
      )
      // 成功：重置表单 + 关闭
      resetForm()
      onClose()
    } catch {
      // 失败：保留表单数据，显示内联错误（REQ 8 AC5）
      setError('创建失败，请重试')
    } finally {
      setSubmitting(false)
    }
  }

  const modes: { key: CreateMode; icon: string; label: string; desc: string }[] = [
    { key: 'pdf', icon: '📄', label: '上传 PDF', desc: '拖拽或点击选择文件' },
    { key: 'link', icon: '🔗', label: '粘贴链接', desc: 'GitHub / 网页链接' },
    { key: 'topic', icon: '💬', label: '直接开始', desc: '描述学习主题' },
  ]

  return (
    <Modal open={open} onClose={onClose} title="新建学习规划" width="max-w-lg">
      {/* 规划名称 */}
      <div className="mb-4">
        <label className="text-sm text-text-secondary mb-1 block">规划名称（可选）</label>
        <input
          value={title}
          onChange={e => setTitle(e.target.value)}
          placeholder="例：Transformer 架构学习"
          className="w-full h-10 rounded-lg border border-border px-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
        />
      </div>

      {/* 创建方式 */}
      <p className="text-sm text-text-secondary mb-2">选择开始方式：</p>
      <div className="grid grid-cols-3 gap-2 mb-4">
        {modes.map(m => (
          <button
            key={m.key}
            onClick={() => setMode(m.key)}
            className={`flex flex-col items-center gap-1 p-3 rounded-xl border transition-all duration-50 ${
              mode === m.key
                ? 'border-primary bg-primary-light'
                : 'border-border hover:border-primary/50 hover:bg-surface-tertiary'
            }`}
          >
            <span className="text-2xl">{m.icon}</span>
            <span className="text-sm font-medium text-text-primary">{m.label}</span>
            <span className="text-xs text-text-secondary text-center">{m.desc}</span>
          </button>
        ))}
      </div>

      {/* 输入区 */}
      {mode === 'topic' && (
        <textarea
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="我想学习 Transformer 架构，从注意力机制开始..."
          rows={3}
          className="w-full rounded-lg border border-border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary resize-none mb-4"
        />
      )}
      {mode === 'link' && (
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="https://github.com/..."
          className="w-full h-10 rounded-lg border border-border px-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary mb-4"
        />
      )}

      {/* 学习周期选择器（REQ 1 AC1） */}
      <div className="mb-4">
        <CyclePicker value={cycleDays} onChange={setCycleDays} />
      </div>

      {/* 学习者画像（REQ 2 AC1-5） */}
      <div className="mb-4">
        <ProfileSection
          expanded={profileExpanded}
          onToggle={() => setProfileExpanded(prev => !prev)}
          profile={profile}
          onChange={setProfile}
        />
      </div>

      {/* 内联错误提示（REQ 8 AC5） */}
      {error && (
        <div className="mb-3 px-3 py-2 rounded-lg bg-red-50 border border-red-200 text-sm text-red-600">
          {error}
        </div>
      )}

      {/* 操作按钮 */}
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose} disabled={submitting}>取消</Button>
        <Button
          variant="primary"
          disabled={!mode}
          loading={submitting}
          onClick={handleCreate}
        >
          创建规划 →
        </Button>
      </div>
    </Modal>
  )
}
