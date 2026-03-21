/**
 * InlineSearchResults — 聊天气泡内的搜索结果卡片组
 *
 * Perplexity 风格：可折叠卡片列表，hover 显示内容预览浮窗（createPortal 到 body，
 * 与侧边栏 SearchResultItem 一致的交互和布局）。
 * 点击卡片 → 跳转外链；hover 延迟显示浮窗，可滑入浮窗查看详情。
 */
import React, { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import type { InlineSearchResult, SearchResult, PlatformType } from '../../types'
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
  arxiv: '📄 arXiv',
  tavily: '🌐 Tavily',
  other: '🔗 其他',
}

function formatNumber(n: number): string {
  if (n >= 10000) return (n / 10000).toFixed(1) + 'w'
  return String(n)
}

const AVATAR_EMOJIS = ['🧑‍💻', '👩‍🔬', '🧑‍🎓', '👨‍🏫', '👩‍💼', '🧑‍🔧', '👨‍🎨', '👩‍🚀', '🧑‍⚕️', '👨‍🍳']
function getAvatarEmoji(index: number): string {
  return AVATAR_EMOJIS[index % AVATAR_EMOJIS.length]
}

/** 从 markdown 内容中提取第一段纯文本 */
function extractFirstParagraph(md: string): string {
  const lines = md.split('\n').filter(l => l.trim())
  const textLines: string[] = []
  for (const line of lines) {
    if (/^#{1,6}\s/.test(line.trim())) {
      if (textLines.length > 0) break
      continue
    }
    textLines.push(line.replace(/\*\*(.*?)\*\*/g, '$1'))
    if (textLines.length >= 4) break
  }
  return textLines.join('\n') || md.slice(0, 200)
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

  // hover 浮窗状态
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null)
  const [popupPos, setPopupPos] = useState<{ top: number; left: number } | null>(null)
  const [imgIdx, setImgIdx] = useState(0)
  const cardRefs = useRef<Map<number, HTMLDivElement>>(new Map())
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current) }, [])

  if (!results.length) return null

  const showPopup = (idx: number) => {
    const el = cardRefs.current.get(idx)
    if (!el) return
    const rect = el.getBoundingClientRect()
    const popupWidth = 340
    const spaceRight = window.innerWidth - rect.right
    const left = spaceRight > popupWidth + 16 ? rect.right + 8 : rect.left - popupWidth - 8
    const top = Math.max(8, Math.min(rect.top, window.innerHeight - 460))
    setPopupPos({ top, left })
    setImgIdx(0)
    setHoveredIdx(idx)
  }

  const hidePopup = () => {
    if (timerRef.current) clearTimeout(timerRef.current)
    setHoveredIdx(null)
    setPopupPos(null)
  }

  const handleCardMouseEnter = (idx: number) => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => showPopup(idx), 300)
  }

  const handleCardMouseLeave = () => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(hidePopup, 150)
  }

  const handlePopupMouseEnter = () => {
    if (timerRef.current) clearTimeout(timerRef.current)
  }

  const handlePopupMouseLeave = () => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(hidePopup, 150)
  }

  /** 点击卡片 → 跳转外链 */
  const handleCardClick = (r: InlineSearchResult) => {
    window.open(r.url, '_blank')
  }

  /** “查看完整报告” → 通知 SourcePanel 打开 PreviewPopup */
  const handleViewDetail = (r: InlineSearchResult) => {
    const sr: SearchResult = {
      id: `inline-${Date.now()}`,
      title: r.title,
      url: r.url,
      platform: r.platform,
      description: r.description,
      qualityScore: r.score,
      contentSummary: r.contentSummary || '',
      contentText: r.contentText || '',
      engagementMetrics: r.engagementMetrics || {},
      imageUrls: r.imageUrls || [],
      topComments: r.commentsPreview || [],
      recommendationReason: r.recommendationReason,
      keyPoints: r.keyPoints,
      commentSummary: r.commentSummary,
    }
    hidePopup()
    useSourceStore.getState().setPendingPreview(sr)
  }

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
              recommendationReason: result.recommendationReason,
              keyPoints: result.keyPoints,
              commentSummary: result.commentSummary,
              commentsPreview: result.commentsPreview,
              imageUrls: result.imageUrls,
            },
          }],
        }),
      })
      if (res.ok) {
        setAddedIds(prev => new Set(prev).add(index))
        const platformType = result.platform as PlatformType
        useSourceStore.getState().addMaterial({
          id: materialId,
          type: platformType,
          name: materialName,
          url: result.url,
          status: 'ready',
          addedAt: new Date().toISOString(),
          extraData: {
            description: result.description,
            qualityScore: result.score,
            contentSummary: result.contentSummary || '',
            engagementMetrics: result.engagementMetrics || {},
            contentText: result.contentText || '',
            recommendationReason: result.recommendationReason,
            keyPoints: result.keyPoints,
            commentSummary: result.commentSummary,
            commentsPreview: result.commentsPreview,
            imageUrls: result.imageUrls,
          },
        })
      }
    } catch { /* silent */ }
    finally {
      setAddingIds(prev => { const next = new Set(prev); next.delete(index); return next })
    }
  }

  const hoveredResult = hoveredIdx !== null ? results[hoveredIdx] : null
  const metrics = hoveredResult?.engagementMetrics ?? {}
  const coreMetrics: { icon: string; label: string; value: number }[] = []
  if (hoveredResult) {
    if (metrics.answer_count != null) coreMetrics.push({ icon: '📝', label: '回答', value: metrics.answer_count })
    if (metrics.likes != null) coreMetrics.push({ icon: '👍', label: '点赞', value: metrics.likes })
    if (metrics.collected != null) coreMetrics.push({ icon: '⭐', label: '收藏', value: metrics.collected })
    if (metrics.comments_count != null || metrics.comments != null)
      coreMetrics.push({ icon: '💬', label: '评论', value: metrics.comments_count ?? metrics.comments ?? 0 })
  }
  const images = hoveredResult?.imageUrls ?? []

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
        <div className="flex flex-col gap-1.5">
          {results.map((r, i) => (
            <div
              key={i}
              ref={(el) => { if (el) cardRefs.current.set(i, el); else cardRefs.current.delete(i) }}
              className="flex items-center gap-2 px-2.5 py-2 rounded-lg bg-[#F8F9FA] hover:bg-[#F1F3F4] cursor-pointer group"
              onMouseEnter={() => handleCardMouseEnter(i)}
              onMouseLeave={handleCardMouseLeave}
              onClick={() => handleCardClick(r)}
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
          onMouseEnter={handlePopupMouseEnter}
          onMouseLeave={handlePopupMouseLeave}
          style={{ top: popupPos.top, left: popupPos.left }}
          className="fixed z-[9999] w-[340px] max-h-[460px] overflow-y-auto rounded-xl border border-[#E0E0E0] bg-white shadow-2xl animate-in fade-in zoom-in-95 duration-50"
        >
          {/* 图片轮播 */}
          {images.length > 0 && (
            <div className="relative w-full bg-[#F8F9FA] rounded-t-xl overflow-hidden border-b border-[#F0F2F5]">
              <a href={images[imgIdx]} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}>
                <img
                  src={images[imgIdx]}
                  alt={`图片 ${imgIdx + 1}`}
                  className="w-full max-h-[180px] object-cover cursor-pointer"
                  loading="lazy"
                />
              </a>
              {images.length > 1 && (
                <>
                  <button
                    onClick={e => { e.stopPropagation(); setImgIdx(i => (i - 1 + images.length) % images.length) }}
                    className="absolute left-1.5 top-1/2 -translate-y-1/2 w-7 h-7 rounded-full bg-black/40 text-white flex items-center justify-center hover:bg-black/60 transition-colors text-sm"
                    aria-label="上一张"
                  >‹</button>
                  <button
                    onClick={e => { e.stopPropagation(); setImgIdx(i => (i + 1) % images.length) }}
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 w-7 h-7 rounded-full bg-black/40 text-white flex items-center justify-center hover:bg-black/60 transition-colors text-sm"
                    aria-label="下一张"
                  >›</button>
                  <span className="absolute bottom-1.5 right-2 text-[10px] text-white bg-black/50 px-1.5 py-0.5 rounded-full">
                    {imgIdx + 1}/{images.length}
                  </span>
                </>
              )}
            </div>
          )}

          <div className="p-4 space-y-3.5">
            {/* 互动指标 badges */}
            {coreMetrics.length > 0 && (
              <div className="flex items-center gap-1.5 flex-wrap pb-1">
                {coreMetrics.map(m => (
                  <span key={m.label} className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded bg-[#F8F9FA] text-[#5F6368] font-medium border border-[#F0F2F5]">
                    <span>{m.icon}</span>
                    <span>{formatNumber(m.value)}</span>
                  </span>
                ))}
              </div>
            )}

            {/* 完整描述 */}
            {hoveredResult.description && (
              <>
                <p className="text-[13px] text-[#3C4043] leading-[1.6]">
                  {hoveredResult.description}
                </p>
                <div className="border-t border-[#EEEEEE]" />
              </>
            )}

            {/* 内容摘要卡片 */}
            {hoveredResult.contentSummary && (
              <div className="bg-[#F8F9FA] rounded-xl px-3.5 py-3 border border-[#F0F2F5]">
                <p className="text-[13px] text-[#3C4043] leading-[1.7] line-clamp-4">
                  {extractFirstParagraph(hoveredResult.contentSummary)}
                </p>
              </div>
            )}

            {/* 推荐理由 */}
            {hoveredResult.recommendationReason && (
              <p className="text-xs text-[#D97757]">💡 {hoveredResult.recommendationReason}</p>
            )}

            {/* 核心观点 */}
            {hoveredResult.keyPoints && hoveredResult.keyPoints.length > 0 && (
              <div className="bg-[#F8F9FA] rounded-xl px-3.5 py-3 border border-[#F0F2F5]">
                <p className="text-[12px] font-semibold text-[#1A1A18] mb-1.5">核心观点</p>
                <ul className="text-[12px] text-[#5F6368] list-disc pl-3.5 space-y-1">
                  {hoveredResult.keyPoints.map((kp, j) => <li key={j}>{kp}</li>)}
                </ul>
              </div>
            )}

            {/* 热门评论 */}
            {hoveredResult.commentsPreview && hoveredResult.commentsPreview.length > 0 && (
              <div className="bg-[#F8F9FA] rounded-xl px-3.5 py-3 border border-[#F0F2F5]">
                <p className="text-[12px] font-semibold text-[#1A1A18] mb-2 flex items-center gap-1.5">
                  <span>🔥</span> 热门评论
                </p>
                <div className="space-y-2.5">
                  {hoveredResult.commentsPreview.slice(0, 2).map((c, i) => (
                    <div key={i} className="flex items-start gap-2">
                      <div className="w-5 h-5 rounded-full bg-[#F0F2F5] flex items-center justify-center text-[10px] flex-shrink-0 mt-0.5">
                        {getAvatarEmoji(i)}
                      </div>
                      <p className="text-[12px] text-[#5F6368] leading-[1.6] line-clamp-2 pt-0.5">
                        {c}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 评论摘要 */}
            {hoveredResult.commentSummary && (
              <p className="text-xs text-[#5F6368]">💬 {hoveredResult.commentSummary}</p>
            )}

            {/* 查看完整报告 */}
            <div className="pt-1">
              <button
                onClick={(e) => { e.stopPropagation(); handleViewDetail(hoveredResult) }}
                className="w-full text-center text-[13px] text-[#D97757] hover:text-[#C06144] font-medium py-2 rounded-xl bg-[#FFF7ED] hover:bg-[#FFEDD4] transition-colors"
              >
                查看完整报告 →
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  )
}
