/**
 * MaterialList — 材料列表（带搜索 + 平台分组筛选）
 *
 * 功能：
 * - 顶部搜索框：实时过滤材料名称，纯前端 filter
 * - 平台 chips：按 material.type 分组筛选，只显示有材料的平台
 * - 「全部」模式下按平台自动分组，带可折叠小标题
 * - 选中具体平台时只显示该平台材料，不分组
 * - 拖拽排序保留
 */
import React, { useCallback, useMemo, useState } from 'react'
import { MaterialItem } from './MaterialItem'
import { PlatformIcon } from '../ui/PlatformIcon'
import type { Material, PlatformType } from '../../types'
import { useSourceStore } from '../../store/sourceStore'

// 平台中文名映射
const PLATFORM_LABELS: Record<PlatformType, string> = {
  xiaohongshu: '小红书',
  zhihu: '知乎',
  github: 'GitHub',
  bilibili: 'B站',
  youtube: 'YouTube',
  google: 'Google',
  wechat: '微信',
  stackoverflow: 'SO',
  other: '本地文件',
}

// 平台显示顺序
const PLATFORM_ORDER: PlatformType[] = [
  'other', 'xiaohongshu', 'zhihu', 'github', 'bilibili',
  'youtube', 'google', 'wechat', 'stackoverflow',
]

// 将非标准 type（如 'pdf'）归一化到 PlatformType
function normalizePlatform(type: string): PlatformType {
  if (PLATFORM_ORDER.includes(type as PlatformType)) return type as PlatformType
  return 'other'
}

interface MaterialListProps {
  materials: Material[]
  planId: string
  selectedId?: string
  onSelect: (id: string) => void
  onRemove: (id: string) => void
}

export const MaterialList: React.FC<MaterialListProps> = ({
  materials, planId, selectedId, onSelect, onRemove,
}) => {
  const [searchText, setSearchText] = useState('')
  const [activePlatform, setActivePlatform] = useState<PlatformType | 'all'>('all')
  const [collapsedGroups, setCollapsedGroups] = useState<Set<PlatformType>>(new Set())

  const dragItem = React.useRef<number | null>(null)
  const dragOverItem = React.useRef<number | null>(null)
  const [draggedId, setDraggedId] = React.useState<string | null>(null)

  // 统计各平台材料数量（基于全量，不受搜索过滤影响）
  const platformCounts = useMemo(() => {
    const counts: Partial<Record<PlatformType, number>> = {}
    for (const m of materials) {
      const p = normalizePlatform(m.type)
      counts[p] = (counts[p] || 0) + 1
    }
    return counts
  }, [materials])

  // 有材料的平台列表（按预设顺序）
  const activePlatforms = useMemo(
    () => PLATFORM_ORDER.filter(p => (platformCounts[p] ?? 0) > 0),
    [platformCounts]
  )

  // 过滤后的材料
  const filtered = useMemo(() => {
    let list = materials
    if (activePlatform !== 'all') {
      list = list.filter(m => normalizePlatform(m.type) === activePlatform)
    }
    if (searchText.trim()) {
      const q = searchText.trim().toLowerCase()
      list = list.filter(m => m.name.toLowerCase().includes(q))
    }
    return list
  }, [materials, activePlatform, searchText])

  // 按平台分组（仅「全部」模式使用）
  const grouped = useMemo(() => {
    if (activePlatform !== 'all') return null
    const groups: { platform: PlatformType; items: Material[] }[] = []
    const map = new Map<PlatformType, Material[]>()
    for (const m of filtered) {
      const p = normalizePlatform(m.type)
      if (!map.has(p)) map.set(p, [])
      map.get(p)!.push(m)
    }
    for (const p of PLATFORM_ORDER) {
      const items = map.get(p)
      if (items && items.length > 0) groups.push({ platform: p, items })
    }
    return groups
  }, [filtered, activePlatform])

  const toggleGroup = (p: PlatformType) => {
    setCollapsedGroups(prev => {
      const next = new Set(prev)
      next.has(p) ? next.delete(p) : next.add(p)
      return next
    })
  }

  // ↑/↓ 键盘导航
  const handleListKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (!['ArrowUp', 'ArrowDown'].includes(e.key)) return
    e.preventDefault()
    const idx = filtered.findIndex(m => m.id === selectedId)
    if (e.key === 'ArrowDown') {
      const next = filtered[idx + 1] ?? filtered[0]
      if (next) onSelect(next.id)
    } else {
      const prev = filtered[idx - 1] ?? filtered[filtered.length - 1]
      if (prev) onSelect(prev.id)
    }
  }, [filtered, selectedId, onSelect])

  // 拖拽处理函数
  const makeDragHandlers = (m: Material, index: number) => ({
    draggable: true as const,
    onDragStart: (e: React.DragEvent<HTMLLIElement>) => {
      dragItem.current = index
      setDraggedId(m.id)
      e.dataTransfer.effectAllowed = 'move'
      e.dataTransfer.setData('application/material', JSON.stringify({
        id: m.id, name: m.name, platform: m.type,
      }))
    },
    onDragEnter: () => { dragOverItem.current = index },
    onDragOver: (e: React.DragEvent<HTMLLIElement>) => e.preventDefault(),
    onDragEnd: () => {
      if (dragItem.current !== null && dragOverItem.current !== null && dragItem.current !== dragOverItem.current) {
        const _mats = [...materials]
        const dragged = _mats.splice(dragItem.current, 1)[0]
        _mats.splice(dragOverItem.current, 0, dragged)
        useSourceStore.getState().reorderMaterials(planId, _mats)
      }
      dragItem.current = null
      dragOverItem.current = null
      setDraggedId(null)
    },
  })

  if (materials.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-center px-2">
        <span className="text-3xl mb-3">📂</span>
        <p className="text-sm text-text-secondary dark:text-dark-text leading-relaxed">
          上传 PDF 或搜索资源，让 AI 基于你的材料回答
        </p>
      </div>
    )
  }

  // 渲染单个材料项
  const renderItem = (m: Material, index: number) => (
    <div key={m.id} className={`transition-all duration-300 ease-[cubic-bezier(0.25,1,0.5,1)] ${draggedId === m.id ? 'scale-[0.98] shadow-md opacity-90 z-20' : 'scale-100 z-0'}`}>
      <MaterialItem
        material={m}
        isSelected={selectedId === m.id}
        onClick={() => onSelect(m.id)}
        onRemove={() => onRemove(m.id)}
        onRename={(newName) => useSourceStore.getState().updateMaterial(m.id, { name: newName })}
        {...makeDragHandlers(m, index)}
      />
    </div>
  )

  return (
    <div>
      {/* 搜索框 */}
      <div className="flex items-center h-10 rounded-2xl bg-[#F0F2F5] transition-all duration-50 focus-within:bg-white focus-within:ring-2 focus-within:ring-[#D97757]/30 focus-within:shadow-sm mt-3 mb-2.5">
        <span className="pl-3 pr-1.5 text-[#9AA0A6] text-xs flex-shrink-0">🔍</span>
        <input
          value={searchText}
          onChange={e => setSearchText(e.target.value)}
          placeholder="搜索材料名称..."
          className="flex-1 h-full bg-transparent text-[13px] text-[#1A1A18] placeholder:text-[#9AA0A6] outline-none"
          aria-label="搜索材料"
        />
        {searchText && (
          <button
            onClick={() => setSearchText('')}
            className="flex-shrink-0 mr-1.5 w-6 h-6 flex items-center justify-center rounded-lg text-[#9AA0A6] hover:text-[#5F6368] transition-colors"
            aria-label="清除搜索"
          >
            ✕
          </button>
        )}
      </div>

      {/* 平台 filter chips */}
      {activePlatforms.length > 1 && (
        <div className="flex flex-wrap gap-2 mb-2.5">
          <button
            onClick={() => setActivePlatform('all')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-[12px] transition-all duration-50 ${
              activePlatform === 'all'
                ? 'bg-[#FFF7ED] text-[#D97757] font-medium border border-[#F2DFD3]'
                : 'bg-[#F8F9FA] text-[#5F6368] border border-transparent hover:bg-[#F0F2F5]'
            }`}
          >
            全部
            <span className="text-[11px] opacity-70">{materials.length}</span>
          </button>
          {activePlatforms.map(p => (
            <button
              key={p}
              onClick={() => setActivePlatform(activePlatform === p ? 'all' : p)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-[12px] transition-all duration-50 ${
                activePlatform === p
                  ? 'bg-[#FFF7ED] text-[#D97757] font-medium border border-[#F2DFD3]'
                  : 'bg-[#F8F9FA] text-[#5F6368] border border-transparent hover:bg-[#F0F2F5]'
              }`}
            >
              <PlatformIcon platform={p} size={14} />
              {PLATFORM_LABELS[p]}
              <span className="text-[11px] opacity-70">{platformCounts[p]}</span>
            </button>
          ))}
        </div>
      )}

      {/* 材料列表 */}
      {filtered.length === 0 ? (
        <p className="text-xs text-[#9AA0A6] text-center py-4">
          {searchText ? '没有匹配的材料' : '该分类下暂无材料'}
        </p>
      ) : grouped ? (
        /* 全部模式：按平台分组 */
        <div className="flex flex-col gap-1.5">
          {grouped.map(({ platform, items }) => (
            <div key={platform}>
              <button
                onClick={() => toggleGroup(platform)}
                className="flex items-center gap-1.5 w-full py-1.5 text-left group"
              >
                <svg
                  width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                  className={`text-[#9AA0A6] transition-transform duration-150 ${collapsedGroups.has(platform) ? '' : 'rotate-90'}`}
                >
                  <polyline points="9 18 15 12 9 6" />
                </svg>
                <PlatformIcon platform={platform} size={13} />
                <span className="text-[11px] font-medium text-[#5F6368]">
                  {PLATFORM_LABELS[platform]}
                </span>
                <span className="text-[10px] text-[#9AA0A6]">· {items.length}</span>
              </button>
              {!collapsedGroups.has(platform) && (
                <ul role="listbox" aria-label={`${PLATFORM_LABELS[platform]}材料`} className="flex flex-col gap-1" onKeyDown={handleListKeyDown}>
                  {items.map(m => renderItem(m, materials.indexOf(m)))}
                </ul>
              )}
            </div>
          ))}
        </div>
      ) : (
        /* 单平台模式：平铺 */
        <ul role="listbox" aria-label="学习材料列表" className="flex flex-col gap-1" onKeyDown={handleListKeyDown}>
          {filtered.map((m) => renderItem(m, materials.indexOf(m)))}
        </ul>
      )}
    </div>
  )
}
