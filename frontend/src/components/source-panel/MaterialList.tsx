import React, { useCallback } from 'react'
import { MaterialItem } from './MaterialItem'
import type { Material } from '../../types'
import { useSourceStore } from '../../store/sourceStore'

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
  const dragItem = React.useRef<number | null>(null)
  const dragOverItem = React.useRef<number | null>(null)
  const [draggedId, setDraggedId] = React.useState<string | null>(null)

  // 11.2: ↑/↓ 键盘导航
  const handleListKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (!['ArrowUp', 'ArrowDown'].includes(e.key)) return
    e.preventDefault()
    const idx = materials.findIndex(m => m.id === selectedId)
    if (e.key === 'ArrowDown') {
      const next = materials[idx + 1] ?? materials[0]
      if (next) onSelect(next.id)
    } else {
      const prev = materials[idx - 1] ?? materials[materials.length - 1]
      if (prev) onSelect(prev.id)
    }
  }, [materials, selectedId, onSelect])
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

  return (
    <div>
      {/* 已添加材料 */}
      <p className="text-xs font-medium text-text-secondary uppercase tracking-wide mt-4 mb-2">
        已添加材料
      </p>
      <ul role="listbox" aria-label="学习材料列表" className="flex flex-col gap-1 relative" onKeyDown={handleListKeyDown}>
        {materials.map((m, index) => (
          <div key={m.id} className={`transition-all duration-300 ease-[cubic-bezier(0.25,1,0.5,1)] ${draggedId === m.id ? 'scale-[0.98] shadow-md opacity-90 z-20' : 'scale-100 z-0'}`}>
            <MaterialItem
              material={m}
              isSelected={selectedId === m.id}
              onClick={() => onSelect(m.id)}
              onRemove={() => onRemove(m.id)}
              onRename={(newName) => useSourceStore.getState().updateMaterial(m.id, { name: newName })}
              draggable
              onDragStart={(e) => {
                dragItem.current = index
                setDraggedId(m.id)
                e.dataTransfer.effectAllowed = 'move'
                // 设置材料数据供聊天区域接收
                e.dataTransfer.setData('application/material', JSON.stringify({
                  id: m.id,
                  name: m.name,
                  platform: m.type,
                }))
              }}
              onDragEnter={() => {
                dragOverItem.current = index
              }}
              onDragOver={(e) => e.preventDefault()}
              onDragEnd={() => {
                if (dragItem.current !== null && dragOverItem.current !== null && dragItem.current !== dragOverItem.current) {
                  const _mats = [...materials]
                  const dragged = _mats.splice(dragItem.current, 1)[0]
                  _mats.splice(dragOverItem.current, 0, dragged)
                  useSourceStore.getState().reorderMaterials(planId, _mats)
                }
                dragItem.current = null
                dragOverItem.current = null
                setDraggedId(null)
              }}
            />
          </div>
        ))}
      </ul>
    </div>
  )
}
