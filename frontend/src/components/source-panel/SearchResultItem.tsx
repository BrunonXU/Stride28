import React, { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import type { SearchResult } from '../../types'
import { openExternalUrl } from '../../utils/openExternalUrl'
import { PlatformIcon } from '../ui/PlatformIcon'

function formatNum(n: any): string {
  const num = Number(n)
  if (isNaN(num)) return String(n)
  if (num >= 10000) return (num / 10000).toFixed(1) + '万'
  return String(num)
}

// 随机头像 emoji 池，用于视觉区分不同评论者/回答者
const AVATAR_EMOJIS = ['🧑‍💻', '👩‍🔬', '🧑‍🎓', '👨‍🏫', '👩‍💼', '🧑‍🔧', '👨‍🎨', '👩‍🚀', '🧑‍⚕️', '👨‍🍳']
function getAvatarEmoji(index: number): string {
  return AVATAR_EMOJIS[index % AVATAR_EMOJIS.length]
}

interface SearchResultItemProps {
  result: SearchResult
  checked: boolean
  onToggle: () => void
  onViewDetail?: (result: SearchResult) => void
}

/** 根据平台和资源类型返回中文标签 */
function getTypeLabel(platform: string, type?: string): string {
  if (platform === 'github') return '仓库'
  if (platform === 'bilibili' || platform === 'youtube') return '视频'
  if (platform === 'zhihu') {
    if (type === 'question') return '问答'
    if (type === 'video') return '视频'
    return '专栏'
  }
  if (platform === 'xiaohongshu') return '笔记'
  return ''
}

export const SearchResultItem: React.FC<SearchResultItemProps> = ({ result, checked, onToggle, onViewDetail }) => {
  const desc = result.description.length > 100
    ? result.description.slice(0, 100) + '…'
    : result.description

  const [hovered, setHovered] = useState(false)
  const [popupPos, setPopupPos] = useState<{ top: number; left: number } | null>(null)
  const [imgIdx, setImgIdx] = useState(0)
  const cardRef = useRef<HTMLDivElement>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const hasDetail = !!(result.contentSummary || result.imageUrls?.length || result.topComments?.length || result.engagementMetrics)

  const showPopup = () => {
    if (!hasDetail || !cardRef.current) return
    const rect = cardRef.current.getBoundingClientRect()
    const popupWidth = 340
    const spaceRight = window.innerWidth - rect.right
    const left = spaceRight > popupWidth + 16 ? rect.right + 8 : rect.left - popupWidth - 8
    const top = Math.max(8, Math.min(rect.top, window.innerHeight - 460))
    setPopupPos({ top, left })
    setImgIdx(0)
    setHovered(true)
  }

  const hidePopup = () => {
    if (timerRef.current) clearTimeout(timerRef.current)
    setHovered(false)
    setPopupPos(null)
  }

  const handleMouseEnter = () => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(showPopup, 300)
  }

  const handleMouseLeave = () => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(hidePopup, 150)
  }

  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current) }, [])

  const metrics = result.engagementMetrics ?? {}
  const coreMetrics: { icon: string; label: string; value: number }[] = []
  if (metrics.answer_count != null) coreMetrics.push({ icon: '📝', label: '回答', value: metrics.answer_count })
  if (metrics.likes != null) coreMetrics.push({ icon: '👍', label: '点赞', value: metrics.likes })
  if (metrics.collected != null) coreMetrics.push({ icon: '⭐', label: '收藏', value: metrics.collected })
  if (metrics.comments_count != null || metrics.comments != null)
    coreMetrics.push({ icon: '💬', label: '评论', value: metrics.comments_count ?? metrics.comments ?? 0 })

  const images = result.imageUrls ?? []

  return (
    <>
      <div
        ref={cardRef}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        className={`rounded-lg border p-3 transition-all duration-50 cursor-pointer ${
          checked
            ? 'border-primary bg-primary-light'
            : 'border-border hover:border-primary/50 hover:bg-surface-tertiary'
        }`}
        onClick={onToggle}
      >
        <div className="flex items-start gap-2">
          <input
            type="checkbox"
            checked={checked}
            onChange={onToggle}
            onClick={e => e.stopPropagation()}
            className="mt-0.5 accent-primary flex-shrink-0"
            aria-label={`选择 ${result.title}`}
          />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5 mb-1">
              <PlatformIcon platform={result.platform} size={14} />
              {getTypeLabel(result.platform, result.type) && (
                <span className="text-[11px] px-1.5 py-0.5 rounded bg-[#FFF7ED] text-[#D97757] font-medium flex-shrink-0 leading-none border border-[#F2DFD3]">
                  {getTypeLabel(result.platform, result.type)}
                </span>
              )}
              <button
                onClick={e => { e.stopPropagation(); openExternalUrl(result.url) }}
                className="text-[15px] font-bold text-text-primary hover:text-primary hover:underline truncate text-left leading-snug"
              >
                {result.title}
              </button>
            </div>
            <p className="text-xs text-text-secondary line-clamp-2 mb-1">{desc}</p>
            {coreMetrics.length > 0 && (
              <div className="flex items-center gap-2 text-xs text-text-tertiary">
                {coreMetrics.map(m => (
                  <span key={m.label} className="inline-flex items-center gap-0.5">
                    <span>{m.icon}</span>
                    <span>{formatNum(m.value)}</span>
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Hover 预览浮窗 */}
      {hovered && popupPos && hasDetail && createPortal(
        <div
          onMouseEnter={() => { if (timerRef.current) clearTimeout(timerRef.current) }}
          onMouseLeave={handleMouseLeave}
          style={{ top: popupPos.top, left: popupPos.left }}
          className="fixed z-[9999] w-[340px] max-h-[460px] overflow-y-auto rounded-xl border border-[#E0E0E0] bg-white dark:bg-dark-surface shadow-2xl animate-in fade-in zoom-in-95 duration-50"
        >
          {/* 图片轮播 — 大图，撑满宽度，顶部圆角 */}
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
                    <span>{formatNum(m.value)}</span>
                  </span>
                ))}
              </div>
            )}

            {/* 完整描述 */}
            {result.description && (
              <>
                <p className="text-[13px] text-[#3C4043] dark:text-dark-text leading-[1.6]">
                  {result.description}
                </p>
                <div className="border-t border-[#EEEEEE] dark:border-dark-border" />
              </>
            )}

            {/* 内容摘要 — 取 markdown 第一段纯文本 */}
            {result.contentSummary && (
              <div className="bg-[#F8F9FA] rounded-xl px-3.5 py-3 border border-[#F0F2F5]">
                <p className="text-[13px] text-[#3C4043] leading-[1.7] line-clamp-4">
                  {extractFirstParagraph(result.contentSummary)}
                </p>
              </div>
            )}

            {/* 高赞评论 */}
            {result.topComments && result.topComments.length > 0 && (
              <div className="bg-[#F8F9FA] rounded-xl px-3.5 py-3 border border-[#F0F2F5]">
                <p className="text-[12px] font-semibold text-[#1A1A18] mb-2 flex items-center gap-1.5">
                  <span>🔥</span> 热门评论
                </p>
                <div className="space-y-2.5">
                  {result.topComments.slice(0, 2).map((c, i) => (
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

            {/* 查看完整详情 */}
            {onViewDetail && (
              <div className="pt-1">
                <button
                  onClick={e => { e.stopPropagation(); hidePopup(); onViewDetail(result) }}
                  className="w-full text-center text-[13px] text-[#D97757] hover:text-[#C06144] font-medium py-2 rounded-xl bg-[#FFF7ED] hover:bg-[#FFEID4] transition-colors"
                >
                  查看完整报告 →
                </button>
              </div>
            )}
          </div>
        </div>,
        document.body
      )}
    </>
  )
}

/** 从 markdown 内容中提取第一段纯文本（去掉标题标记和加粗语法） */
function extractFirstParagraph(md: string): string {
  const lines = md.split('\n').filter(l => l.trim())
  const textLines: string[] = []
  for (const line of lines) {
    // 跳过 markdown 标题行
    if (/^#{1,6}\s/.test(line.trim())) {
      if (textLines.length > 0) break // 遇到下一个标题就停
      continue
    }
    // 去掉加粗语法
    textLines.push(line.replace(/\*\*(.*?)\*\*/g, '$1'))
    if (textLines.length >= 4) break
  }
  return textLines.join('\n') || md.slice(0, 200)
}
