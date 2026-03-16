import React, { useState } from 'react'
import { ConfirmModal } from '../ui/Modal'
import { PlatformIcon } from '../ui/PlatformIcon'
import type { Material } from '../../types'

export const MaterialIcon = ({ material, className = "" }: { material: Material, className?: string }) => {
  const name = material.name.toLowerCase()

  // 本地文件保留原有图标
  if (name.endsWith('.pdf')) {
    return (
      <div className={`flex items-center justify-center bg-transparent border-2 border-[#D93025] text-[#D93025] rounded-md font-bold ${className}`}>
        PDF
      </div>
    )
  }
  if (name.endsWith('.md') || name.endsWith('.txt')) {
    return (
      <div className={`flex flex-col items-center justify-center bg-[#D97757] text-white rounded-md font-bold ${className}`}>
        <span className="leading-none mt-0.5">M</span>
        <span className="leading-none text-[8px] md:text-[10px]">↓</span>
      </div>
    )
  }

  // 搜索来源材料 — 使用平台 SVG 图标
  return (
    <span className={`flex items-center justify-center ${className}`}>
      <PlatformIcon platform={material.type} size={18} />
    </span>
  )
}

const STATUS_DOT: Record<Material['status'], React.ReactNode> = {
  ready: <span className="w-2 h-2 rounded-full bg-green-500 flex-shrink-0" title="就绪" />,
  parsing: <span className="w-2 h-2 rounded-full bg-gray-300 animate-pulse flex-shrink-0" title="解析中" />,
  chunking: <span className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse flex-shrink-0" title="分块中" />,
  error: <span className="w-2 h-2 rounded-full bg-red-500 flex-shrink-0" title="错误" />,
}

interface MaterialItemProps {
  material: Material
  isSelected: boolean
  onClick: () => void
  onRemove: () => void
  onRename?: (newName: string) => void
  draggable?: boolean
  onDragStart?: (e: React.DragEvent<HTMLLIElement>) => void
  onDragEnter?: (e: React.DragEvent<HTMLLIElement>) => void
  onDragEnd?: (e: React.DragEvent<HTMLLIElement>) => void
  onDragOver?: (e: React.DragEvent<HTMLLIElement>) => void
}

export const MaterialItem: React.FC<MaterialItemProps> = ({
  material, isSelected, onClick, onRemove, onRename,
  draggable, onDragStart, onDragEnter, onDragEnd, onDragOver
}) => {
  const [hovered, setHovered] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [editingName, setEditingName] = useState(false)
  const [draftName, setDraftName] = useState(material.name)

  const commitRename = () => {
    setEditingName(false)
    if (draftName.trim() && draftName.trim() !== material.name) {
      onRename?.(draftName.trim())
    } else {
      setDraftName(material.name)
    }
  }

  const displayName = material.name.length > 22 ? material.name.slice(0, 22) + '…' : material.name
  const isUnviewed = !material.viewedAt

  return (
    <>
      <li
        role="option"
        aria-selected={isSelected}
        tabIndex={0}
        draggable={draggable}
        onDragStart={onDragStart}
        onDragEnter={onDragEnter}
        onDragEnd={onDragEnd}
        onDragOver={onDragOver}
        className={`flex items-center gap-3 h-12 px-2.5 rounded-xl cursor-default transition-all duration-50 focus-visible:ring-2 focus-visible:ring-[#D97757] outline-none ${isSelected
          ? 'bg-[#F2DFD3] border-l-[3px] border-[#D97757] px-2'
          : 'hover:bg-[#F1F3F4] border-l-[3px] border-transparent px-2'
          }`}
        onClick={onClick}
        onKeyDown={e => {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick() }
          if (e.key === 'Delete') { e.preventDefault(); setConfirmOpen(true) }
        }}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        <div className="relative flex items-center justify-center flex-shrink-0 w-8 h-8">
          {isUnviewed && !isSelected && (
            <div className="absolute -left-1.5 w-1.5 h-1.5 rounded-full bg-[#D97757]" />
          )}
          <MaterialIcon material={material} className="w-6 h-7 text-[8px]" />
        </div>
        {editingName ? (
          <input
            autoFocus
            value={draftName}
            onChange={e => setDraftName(e.target.value)}
            onBlur={commitRename}
            onKeyDown={e => {
              if (e.key === 'Enter') commitRename()
              if (e.key === 'Escape') { setDraftName(material.name); setEditingName(false) }
            }}
            className="flex-1 text-sm bg-transparent border-b border-[#D97757] outline-none px-0.5 text-[#202124]"
            onClick={e => e.stopPropagation()}
            aria-label="重命名材料"
          />
        ) : (
          <span className={`flex-1 text-sm truncate transition-colors ${isUnviewed && !isSelected ? 'text-gray-900 font-medium' : 'text-[#202124] font-normal'}`}>
            {displayName}
          </span>
        )}

        {hovered && !editingName ? (
          <div className="flex items-center flex-shrink-0">
            <button
              aria-label="重命名材料"
              onClick={e => { e.stopPropagation(); setEditingName(true) }}
              className="text-[#9AA0A6] hover:text-[#D97757] text-base transition-colors duration-50 w-6 h-6 flex items-center justify-center mr-1"
            >
              ✎
            </button>
            <button
              aria-label="移除材料"
              onClick={e => { e.stopPropagation(); setConfirmOpen(true) }}
              className="text-[#9AA0A6] hover:text-red-500 text-base transition-colors duration-50 w-5 h-5 flex items-center justify-center"
            >
              ✕
            </button>
          </div>
        ) : (
          <span className="flex-shrink-0">{STATUS_DOT[material.status]}</span>
        )}
      </li>

      <ConfirmModal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={onRemove}
        message={`确认移除「${displayName}」？`}
        confirmLabel="移除"
      />
    </>
  )
}
