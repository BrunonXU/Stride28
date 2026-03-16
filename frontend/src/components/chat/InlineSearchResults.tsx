/**
 * InlineSearchResults — 聊天气泡内的搜索结果卡片组
 *
 * Perplexity 风格：可折叠卡片列表，hover 显示内容预览浮窗（createPortal 到 body，
 * 与侧边栏 SearchResultItem 一致的交互和布局）。
 */
import React, { useState, useRef, useCallback } from 'react'
import { createPortal } from 'react-dom'
import type { InlineSearchResult, PlatformType } from '../../types'
import { useSourceStore } from '../../store/sourceStore'

const PLATFORM_LABELS: Record<string, string> = {
  bilibili: '📺 B站',
  zhihu: '📖 知乎',
  xiaohongshu: '📕 小红书',
  youtube: '▶️ YouTube',
  google: '🔍 Google',
  github: '🐙 GitHub',
  wechat: '💬 微信',
  stackoverflow: '📚 StackOverflow',
  other: '🔗 其他',
}

function formatNumber(n: number): string {
  if (n >= 10000) return (n / 10000).toFixed(1) + 'w'
  return String(n)
}

interface InlineSearchResultsProps {
  results: InlineSearchResult[]
  planId: string
  defaultExpanded?: boolean
}

export const InlineSearchResults: React.FC<InlineSearchResultsProps> = ({
  results,
  planId,
  defaultExpanded = true,
}) => {
  const [expanded, setExpanded] = useState(defaultExpanded)
  const [addingIds, setAddingIds] = useState<Set<number>>(new Set())
  const [addedIds, setAddedIds] = useState<Set<number>>(new Set())
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null)
  const hoverRef = useRef<HTMLDivElement>(null)
  const [popupPos, setPopupPos] = useState<{ top: number; left: number } | null>(null)

  if (!results.length) return null

  const handleAddMaterial = async (result: InlineSearchResult, index: number) => {
    if (addingIds.has(index) || addedIds.has(index)) return
    setAddingIds(prev => new Set(prev).add(index))
    try {
      const materialId = `search-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
      const materialName = result.title.slice(0, 40)

      const res = await fetch('/api/materials/from-search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          items: [{
            id: materialId,
            planId,
            platform: result.platform,
            name: materialName,
            url: result.url,
            extraData: {
              description: result.description,
              qualityScore: result.score,
              contentSummary: result.contentSummary || '',
              engagementMetrics: result.engagementMetrics || {},
              contentText: result.contentText || '',
            },
          }],
        }),
      })
      if (res.ok) {
        setAddedIds(prev => new Set(prev).add(index))
        // 同步更新前端 sourceStore，让材料列表立即显示
        const platformType = result.platform as PlatformType
        useSourceStore.getState().addMaterial({
          id: materialId,
          type: platformType,
          name: materialName,
          url: result.url,
          status: 'ready',
          addedAt: new Date().toISOString(),
        })
      }
    } catch { /* 静默 */ }
    finally {
      setAddingIds(prev => { const next = new Set(prev); next.delete(index); return next })
    }
  }

  const handleMouseEnter = useCallback((e: React.MouseEvent, idx: number) => {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    setPopupPos({ top: rect.top, left: rect.right + 8 })
    setHoveredIdx(idx)
  }, [])

  const handleMouseLeave = useCallback(() => {
    setHoveredIdx(null)
    setPopupPos(null)
  }, [])

  const hoveredResult = hoveredIdx !== null ? results[hoveredIdx] : null

  return (
    <div className="mt-2 mb-1">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 text-xs text-[#5F6368] hover:text-[#202124] mb-1"
      >
        <span className={`transition-transform duration-50 ${expanded ? 'rotate-90' : ''}`}>▶</span>
        <span>搜索结果 ({results.length})</span>
      </button>

      {expanded && (
        <div className="flex flex-col gap-1.5" ref={hoverRef}>
          {results.map((r, i) => (
            <div
              key={i}
              className="flex items-center gap-2 px-2.5 py-2 rounded-lg bg-[#F8F9FA] hover:bg-[#F1F3F4] cursor-pointer group"
              onMouseEnter={(e) => handleMouseEnter(e, i)}
              onMouseLeave={handleMouseLeave}
              onClick={() => window.open(r.url, '_blank')}
            >
              <div className="flex-1 min-w-0">
                <p className="text-sm text-[#202124] truncate leading-tight">{r.title}</p>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-[11px] text-[#5F6368]">
                    {PLATFORM_LABELS[r.platform] || r.platform}
                  </span>
                  {r.engagementMetrics && Object.keys(r.engagementMetrics).length > 0 && (
                    <span className="text-[11px] text-[#9AA0A6]">
                      {Object.entries(r.engagementMetrics).slice(0, 2).map(([k, v]) =>
                        `${k === 'likes' ? '👍' : k === 'views' ? '👁' : k === 'comments' ? '💬' : k} ${formatNumber(v as number)}`
                      ).join(' ')}
                    </span>
                  )}
                  {r.score > 0 && (
                    <span className="text-[11px] text-[#D97757] font-medium">{r.score.toFixed(1)}</span>
                  )}
                </div>
              </div>
              <button
                onClick={(e) => { e.stopPropagation(); handleAddMaterial(r, i) }}
                disabled={addingIds.has(i) || addedIds.has(i)}
                className={`flex-shrink-0 text-xs px-2 py-1 rounded-md opacity-0 group-hover:opacity-100 ${
                  addedIds.has(i)
                    ? 'bg-green-100 text-green-600'
                    : 'bg-[#F2DFD3] text-[#D97757] hover:bg-[#EACFC0]'
                } disabled:opacity-60`}
              >
                {addedIds.has(i) ? '✓ 已添加' : addingIds.has(i) ? '...' : '+ 添加'}
              </button>
            </div>
          ))}
        </div>
      )}

      {hoveredResult && popupPos && createPortal(
        <div
          className="fixed z-[9999] w-72 max-h-80 bg-white rounded-xl shadow-xl border border-gray-200 p-3 overflow-y-auto pointer-events-none"
          style={{ top: popupPos.top, left: popupPos.left }}
        >
          <p className="text-sm font-medium text-[#202124] mb-1.5">{hoveredResult.title}</p>
          {hoveredResult.recommendationReason && (
            <p className="text-xs text-[#D97757] mb-1.5">💡 {hoveredResult.recommendationReason}</p>
          )}
          {hoveredResult.contentSummary && (
            <p className="text-xs text-[#5F6368] mb-1.5">{hoveredResult.contentSummary}</p>
          )}
          {hoveredResult.keyPoints && hoveredResult.keyPoints.length > 0 && (
            <div className="mb-1.5">
              <p className="text-[11px] text-[#9AA0A6] mb-0.5">核心观点</p>
              <ul className="text-xs text-[#5F6368] list-disc pl-3.5 space-y-0.5">
                {hoveredResult.keyPoints.map((kp, j) => <li key={j}>{kp}</li>)}
              </ul>
            </div>
          )}
          {hoveredResult.commentSummary && (
            <p className="text-xs text-[#5F6368]">💬 {hoveredResult.commentSummary}</p>
          )}
        </div>,
        document.body
      )}
    </div>
  )
}