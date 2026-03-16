/**
 * SearchHistoryCard
 */
import React, { useState } from 'react'
import { SearchResultItem } from './SearchResultItem'
import { PlatformIcon } from '../ui/PlatformIcon'
import type { SearchHistoryEntry, SearchResult, PlatformType } from '../../types'

const ALL_KNOWN: PlatformType[] = ['bilibili', 'youtube', 'google', 'github', 'xiaohongshu', 'zhihu']

export interface SearchHistoryCardProps {
  entry: SearchHistoryEntry
  isExpanded: boolean
  onToggle: () => void
  onAddToMaterials?: (results: SearchResult[]) => void
  onRemove?: (id: string) => void
  onViewDetail?: (result: SearchResult) => void
  onCheckedChange?: (checkedIds: Set<string>) => void
}

export function formatSearchTime(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  const mm = String(d.getMonth() + 1)
  const dd = String(d.getDate())
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${mm}/${dd} ${hh}:${mi}`
}

function PlatformBadges({ platforms }: { platforms: PlatformType[] }) {
  if (ALL_KNOWN.every(p => platforms.includes(p))) return null
  return (
    <span className="inline-flex items-center gap-0.5 flex-shrink-0">
      {platforms.map(p => (
        <PlatformIcon key={p} platform={p} size={12} />
      ))}
    </span>
  )
}

export const SearchHistoryCard: React.FC<SearchHistoryCardProps> = ({
  entry, isExpanded, onToggle, onAddToMaterials, onRemove, onViewDetail, onCheckedChange,
}) => {
  const [checked, setChecked] = useState<Set<string>>(new Set())

  const toggleCheck = (id: string) => {
    setChecked(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      onCheckedChange?.(next)
      return next
    })
  }

  const prevExpanded = React.useRef(isExpanded)
  React.useEffect(() => {
    if (prevExpanded.current && !isExpanded) {
      setChecked(new Set())
      onCheckedChange?.(new Set())
    }
    prevExpanded.current = isExpanded
  }, [isExpanded, onCheckedChange])

  const confirmRemove = () => {
    if (onRemove && window.confirm(`删除搜索记录 "${entry.query}"？`)) onRemove(entry.id)
  }

  const delBtn = onRemove ? (
    <button onClick={(e) => { e.stopPropagation(); confirmRemove() }}
      className="flex-shrink-0 w-7 h-7 flex items-center justify-center text-[#999] hover:text-red-500 hover:bg-red-50 rounded-md transition-colors opacity-0 group-hover:opacity-100"
      aria-label="删除">
      <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
    </button>
  ) : null

  if (entry.status === 'searching') {
    return (
      <div className="group flex items-center gap-2 px-2.5 py-2 rounded-lg hover:bg-[#F8F9FA] transition-colors">
        <span className="text-sm text-[#202124] truncate flex-1">{entry.query}</span>
        <span className="inline-flex gap-0.5 flex-shrink-0" data-testid="loading-dots">
          <span className="animate-bounce inline-block w-1 h-1 rounded-full bg-[#D97757]" style={{ animationDelay: '0ms' }} />
          <span className="animate-bounce inline-block w-1 h-1 rounded-full bg-[#D97757]" style={{ animationDelay: '150ms' }} />
          <span className="animate-bounce inline-block w-1 h-1 rounded-full bg-[#D97757]" style={{ animationDelay: '300ms' }} />
        </span>
        {delBtn}
      </div>
    )
  }

  if (entry.status === 'error') {
    return (
      <div className="group flex items-center gap-2 px-2.5 py-2 rounded-lg hover:bg-[#F8F9FA] transition-colors cursor-pointer" onClick={onToggle}>
        <span className="text-sm text-[#202124] truncate flex-1">{entry.query}</span>
        <span className="text-[11px] text-red-400 flex-shrink-0">失败</span>
        {delBtn}
      </div>
    )
  }

  const expandCls = isExpanded ? 'rotate-90 text-[#D97757]' : 'text-[#9AA0A6]'
  const allChecked = entry.results.length > 0 && entry.results.every(r => checked.has(r.id))

  return (
    <div className="rounded-lg overflow-hidden">
      <div className="group flex items-center gap-2 px-2.5 py-2 rounded-lg hover:bg-[#F8F9FA] transition-colors cursor-pointer" onClick={onToggle}>
        <span className={"text-[10px] transition-transform duration-50 flex-shrink-0 " + expandCls}>&#9654;</span>
        <span className="text-sm text-[#202124] truncate flex-1">{entry.query}</span>
        <span className="text-[11px] text-[#9AA0A6] flex-shrink-0 inline-flex items-center gap-1">
          <PlatformBadges platforms={entry.platforms} />
          {entry.resultCount}
        </span>
        {delBtn}
      </div>
      {isExpanded && entry.results.length > 0 && (
        <div className="pl-4 pr-2 pb-2 flex flex-col gap-2 pt-1">
          <div className="flex items-center justify-end">
            <button
              onClick={() => {
                const next = allChecked ? new Set<string>() : new Set(entry.results.map(r => r.id))
                setChecked(next)
                onCheckedChange?.(next)
              }}
              className="text-[11px] text-[#D97757] hover:text-[#C06144] font-medium transition-colors"
            >
              {allChecked ? '取消全选' : '全选'}
            </button>
          </div>
          {entry.results.slice(0, 10).map(r => (
            <SearchResultItem
              key={r.id}
              result={r}
              checked={checked.has(r.id)}
              onToggle={() => toggleCheck(r.id)}
              onViewDetail={onViewDetail}
            />
          ))}
          <p className="text-[11px] text-[#B0B5BA]">{formatSearchTime(entry.searchedAt)}</p>
        </div>
      )}
    </div>
  )
}
