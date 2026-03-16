/**
 * PreviewPopup — 外部资源预览详情页
 *
 * 设计原则：
 * - 黑白灰为主，像 markdown 渲染一样简洁易读
 * - 内容整理用 ReactMarkdown 渲染（支持加粗、标题层级）
 * - 原文内容按回答拆分成独立折叠卡片
 * - 去掉冗余区块，只保留：内容整理 + 原文
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import { PlatformIcon } from '../ui/PlatformIcon'
import type { SearchResult } from '../../types'
import { openExternalUrl } from '../../utils/openExternalUrl'

interface PreviewPopupProps {
  result: SearchResult
  onClose: () => void
  onRefresh: () => void
}

export const PreviewPopup: React.FC<PreviewPopupProps> = ({
  result: initialResult,
  onClose,
  onRefresh,
}) => {
  const [result, setResult] = useState<SearchResult>(initialResult)
  const [refreshing, setRefreshing] = useState(false)
  const [imageIndex, setImageIndex] = useState(0)

  useEffect(() => { setResult(initialResult) }, [initialResult])
  useEffect(() => { setImageIndex(0) }, [initialResult])

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  const handleRefresh = useCallback(async () => {
    setRefreshing(true)
    try {
      const res = await fetch('/api/resource/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: result.url, platform: result.platform }),
      })
      if (!res.ok) throw new Error(`刷新失败 (${res.status})`)
      const data = await res.json()
      setResult((prev) => ({
        ...prev,
        contentSummary: data.contentSummary ?? prev.contentSummary,
        imageUrls: data.imageUrls ?? prev.imageUrls,
        engagementMetrics: data.engagementMetrics ?? prev.engagementMetrics,
        qualityScore: data.qualityScore ?? prev.qualityScore,
        topComments: data.topComments ?? prev.topComments,
      }))
      onRefresh()
    } catch (err: any) {
      console.error('刷新失败:', err)
    } finally {
      setRefreshing(false)
    }
  }, [result.url, result.platform, onRefresh])

  const metrics = result.engagementMetrics ?? {}
  const images = (result.imageUrls ?? []).slice(0, 20)

  // 拆分原文内容为回答卡片
  const answerCards = useMemo(() => splitAnswerCards(result.contentText || ''), [result.contentText])

  // 按平台差异化展示互动数据
  const metricParts: string[] = []
  if (result.platform === 'zhihu') {
    // 知乎问题聚合：显示回答数；文章：显示赞数和评论数
    const answerCount = metrics.answer_count ?? (answerCards.length > 1 ? answerCards.length : 0)
    if (answerCount > 0) metricParts.push(`${answerCount} 个回答`)
    if (metrics.likes != null && metrics.likes > 0) metricParts.push(`${formatNumber(metrics.likes)} 赞`)
    if (metrics.comments_count != null && metrics.comments_count > 0) metricParts.push(`${formatNumber(metrics.comments_count)} 评论`)
  } else if (result.platform === 'github') {
    // GitHub：Stars + Forks
    if (metrics.stars != null) metricParts.push(`${formatNumber(metrics.stars)} Stars`)
    if (metrics.forks != null) metricParts.push(`${formatNumber(metrics.forks)} Forks`)
    if (metrics.open_issues != null) metricParts.push(`${formatNumber(metrics.open_issues)} Issues`)
  } else {
    // 小红书/其他：赞 + 收藏 + 评论
    if (metrics.likes != null) metricParts.push(`${formatNumber(metrics.likes)} 赞`)
    if (metrics.collected != null) metricParts.push(`${formatNumber(metrics.collected)} 收藏`)
    if (metrics.comments_count != null || metrics.comments != null)
      metricParts.push(`${formatNumber(metrics.comments_count ?? metrics.comments ?? 0)} 评论`)
  }

  return (
    <div
      className="absolute inset-0 z-50 flex flex-col bg-[#F0F2F5] dark:bg-dark-bg overflow-hidden"
      role="dialog"
      aria-label={`预览: ${result.title}`}
      aria-modal="true"
    >
      {/* Header — 宽松些：标题加大 + 平台 + 评分 + 互动数据 */}
      <div className="flex items-center gap-4 px-6 py-4 border-b border-[#E8EAED] bg-white flex-shrink-0">
        <div className="flex-1 min-w-0">
          <button
            onClick={() => openExternalUrl(result.url)}
            className="text-[18px] font-bold text-[#1A1A18] dark:text-dark-text truncate leading-tight flex items-center gap-2 hover:text-[#1a73e8] hover:underline text-left w-full"
          >
            <PlatformIcon platform={result.platform} size={18} className="flex-shrink-0" />
            <span className="truncate">{result.title}</span>
          </button>
          <div className="flex items-center gap-2 mt-0.5">
            {metricParts.length > 0 && (
              <span className="text-[12px] text-[#9AA0A6]">{metricParts.join(' · ')}</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            aria-label="刷新内容"
            className={`w-8 h-8 flex items-center justify-center rounded-full hover:bg-[#F1F3F4] transition-colors text-[#5F6368] ${refreshing ? 'opacity-50 cursor-not-allowed' : ''}`}
            title="重新获取最新数据"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className={refreshing ? 'animate-spin' : ''}>
              <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
              <path d="M3 3v5h5" />
              <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
              <path d="M16 21v-5h5" />
            </svg>
          </button>
          <button
            onClick={onClose}
            aria-label="关闭预览"
            className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-[#F1F3F4] transition-colors text-[#5F6368]"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
      </div>

      {/* Scrollable content — 加大内边距 */}
      <div className="flex-1 overflow-y-auto scrollbar-thin px-8 py-6">
        {refreshing ? (
          <SkeletonContent />
        ) : (
          <article className="max-w-3xl mx-auto space-y-5">

            {/* 图片轮播 */}
            {images.length > 0 && (
              <div className="bg-white rounded-xl shadow-sm border border-[#E8EAED] p-4">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-[14px] font-semibold text-[#202124]">图片</h3>
                  <span className="text-[12px] px-2 py-0.5 bg-[#F4F5F7] rounded-full text-[#5F6368] font-medium">{imageIndex + 1} / {images.length}</span>
                </div>
                <div className="relative rounded-lg overflow-hidden border border-[#E8EAED]/50 bg-[#FAFAFA] flex items-center justify-center min-h-[120px]">
                  <a href={images[imageIndex]} target="_blank" rel="noopener noreferrer" className="w-full flex justify-center">
                    <img
                      src={images[imageIndex]}
                      alt={`图片 ${imageIndex + 1}`}
                      className="max-w-full object-contain rounded-lg"
                      style={{ maxHeight: '35vh' }}
                      loading="lazy"
                    />
                  </a>
                  {images.length > 1 && (
                    <>
                      <button
                        onClick={() => setImageIndex(i => (i - 1 + images.length) % images.length)}
                        className="absolute left-3 top-1/2 -translate-y-1/2 w-8 h-8 rounded-full bg-black/40 text-white flex items-center justify-center hover:bg-black/60 transition-colors shadow-sm backdrop-blur-sm"
                        aria-label="上一张"
                      >‹</button>
                      <button
                        onClick={() => setImageIndex(i => (i + 1) % images.length)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 w-8 h-8 rounded-full bg-black/40 text-white flex items-center justify-center hover:bg-black/60 transition-colors shadow-sm backdrop-blur-sm"
                        aria-label="下一张"
                      >›</button>
                    </>
                  )}
                </div>
              </div>
            )}

            {/* 内容整理 — markdown 渲染，整体评价用卡片包裹 */}
            {result.contentSummary ? (() => {
              // 拆分：整体评价 vs 剩余内容
              const summaryText = result.contentSummary
              const evalMatch = summaryText.match(/^([\s\S]*?)(##\s*整体评价\s*\n)([\s\S]*?)(?=\n##\s|$)/)
              const evalSection = evalMatch ? evalMatch[3].trim() : ''
              const restContent = evalMatch
                ? summaryText.replace(evalMatch[2] + evalMatch[3], '').trim()
                : summaryText

              return (
                <>
                  {evalSection && (
                    <div className="bg-white rounded-xl shadow-sm border border-[#E8EAED] p-5">
                      <h2 className="text-[16px] font-semibold text-[#1A1A18] mb-3 flex items-center gap-2">
                        <span className="w-1 h-4 bg-[#D97757] rounded-full inline-block"></span>
                        整体评价
                      </h2>
                      <div className="text-[14px] text-[#3C4043] leading-[1.85]">
                        <ReactMarkdown>{evalSection}</ReactMarkdown>
                      </div>
                    </div>
                  )}
                  {restContent && (
                    <div className="bg-white rounded-xl shadow-sm border border-[#E8EAED] p-5">
                      <div className="prose prose-sm max-w-none dark:prose-invert
                        prose-headings:text-[#1A1A18] prose-headings:font-bold
                        prose-h2:text-[18px] prose-h2:mt-1 prose-h2:mb-4 prose-h2:border-none
                        prose-h3:text-[15px] prose-h3:mt-5 prose-h3:mb-3 prose-h3:pl-3 prose-h3:border-l-[3px] prose-h3:border-[#D97757]
                        prose-p:text-[15px] prose-p:leading-[1.85] prose-p:text-[#3C4043] prose-p:my-3
                        prose-li:text-[15px] prose-li:leading-[1.85] prose-li:text-[#3C4043] prose-li:my-1.5 prose-li:marker:text-[#D97757]
                        prose-strong:text-[#202124] prose-strong:font-semibold
                        prose-a:text-[#1a73e8] prose-a:no-underline hover:prose-a:underline
                        prose-ul:my-3 prose-ol:my-3
                      ">
                        <ReactMarkdown>{restContent}</ReactMarkdown>
                      </div>
                    </div>
                  )}
                </>
              )
            })() : (
              <div className="bg-white rounded-xl shadow-sm border border-[#E8EAED] p-5">
                <p className="text-[14px] text-[#9AA0A6] text-center">AI 内容整理不可用（评估降级，仅保留原文）</p>
              </div>
            )}

            {/* 高赞评论 */}
            {result.topComments && result.topComments.length > 0 && (
              <div className="bg-white rounded-xl shadow-sm border border-[#E8EAED] p-5">
                <h2 className="text-[16px] font-semibold text-[#1A1A18] mb-4 flex items-center gap-2">
                  <span>🔥</span> 高赞评论
                </h2>
                <div className="space-y-3.5">
                  {result.topComments.slice(0, 5).map((c, i) => (
                    <div key={i} className="flex items-start gap-3">
                      <div className="w-8 h-8 rounded-full bg-[#F4F5F7] flex items-center justify-center text-sm flex-shrink-0 mt-0.5">
                        {AVATAR_EMOJIS[i % AVATAR_EMOJIS.length]}
                      </div>
                      <p className="text-[14px] text-[#3C4043] leading-[1.7] flex-1 pt-0.5">
                        {c}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 原文内容 — 按回答拆分成折叠卡片（GitHub 仓库不展示原文 README，只看 AI 总结） */}
            {result.platform !== 'github' && answerCards.length > 0 && (
              <div className="bg-white rounded-xl shadow-sm border border-[#E8EAED] p-5">
                <h2 className="text-[16px] font-semibold text-[#1A1A18] mb-4 flex items-center gap-2">
                  <span className="w-1 h-4 bg-[#1a73e8] rounded-full inline-block"></span>
                  原文内容
                </h2>
                <div className="space-y-3">
                  {answerCards.map((card, idx) => (
                    <AnswerCard key={idx} title={card.title} content={card.content} index={idx} />
                  ))}
                </div>
              </div>
            )}

            {/* Footer */}
            <div className="flex justify-center pt-2 pb-6">
              <span className="text-[12px] text-[#BDBDBD]">到底啦</span>
            </div>
          </article>
        )}
      </div>
    </div>
  )
}


// 随机头像 emoji 池，用于视觉区分不同回答者/评论者
const AVATAR_EMOJIS = ['🧑‍💻', '👩‍🔬', '🧑‍🎓', '👨‍🏫', '👩‍💼', '🧑‍🔧', '👨‍🎨', '👩‍🚀', '🧑‍⚕️', '👨‍🍳']

/** 单个回答折叠卡片 */
const AnswerCard: React.FC<{ title: string; content: string; index?: number }> = ({ title, content, index = 0 }) => {
  const [expanded, setExpanded] = useState(false)
  const lines = content.split('\n')
  const previewLines = 3
  const needsCollapse = lines.length > previewLines
  const displayText = expanded ? content : lines.slice(0, previewLines).join('\n') + (needsCollapse ? '...' : '')

  return (
    <div className="border border-[#E8EAED] rounded-lg overflow-hidden bg-[#FAFAFA]">
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-[#F1F3F4] transition-colors text-left"
      >
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <span className="text-sm flex-shrink-0">{AVATAR_EMOJIS[index % AVATAR_EMOJIS.length]}</span>
          <span className="text-[14px] font-medium text-[#202124] truncate">{title}</span>
        </div>
        <span className="text-[12px] text-[#9AA0A6] flex-shrink-0 ml-3">
          {expanded ? '收起 ▲' : '展开 ▼'}
        </span>
      </button>
      {(expanded || !needsCollapse) && (
        <div className="relative px-4 py-3 max-h-[50vh] overflow-y-auto scrollbar-thin bg-white border-t border-[#E8EAED]">
          <p className="text-[14px] text-[#3C4043] leading-[1.85] whitespace-pre-line">{displayText}</p>
          {expanded && needsCollapse && (
            <div className="sticky bottom-0 pt-4 pb-1 bg-gradient-to-t from-white via-white to-transparent dark:from-dark-bg dark:via-dark-bg flex justify-center mt-2">
              <button
                onClick={() => setExpanded(false)}
                className="text-[13px] text-[#1a73e8] hover:text-[#174ea6] font-medium px-4 py-1.5 rounded-full bg-[#1a73e8]/5 hover:bg-[#1a73e8]/10 transition-colors"
              >
                收起内容 ▲
              </button>
            </div>
          )}
        </div>
      )}
      {!expanded && needsCollapse && (
        <div className="px-4 py-3 bg-white border-t border-[#E8EAED]">
          <p className="text-[14px] text-[#3C4043] leading-[1.85] whitespace-pre-line">{displayText}</p>
        </div>
      )}
    </div>
  )
}

/** 将原文按【回答N·赞X】拆分成卡片，非聚合内容作为单个卡片 */
function splitAnswerCards(text: string): { title: string; content: string }[] {
  if (!text || !text.trim()) return []

  // 清理格式：去掉连续空行、无意义分割线
  const cleaned = cleanRawText(text)

  // 检测知乎聚合格式
  const answerPattern = /【回答(\d+)[·・]赞(\d+)】/g
  const matches = [...cleaned.matchAll(answerPattern)]

  if (matches.length >= 2) {
    // 多回答聚合：按标记拆分
    const cards: { title: string; content: string }[] = []
    for (let i = 0; i < matches.length; i++) {
      const match = matches[i]
      const start = match.index! + match[0].length
      const end = i + 1 < matches.length ? matches[i + 1].index! : cleaned.length
      const content = cleaned.slice(start, end).trim()
      cards.push({
        title: `回答 ${match[1]}（赞 ${match[2]}）`,
        content,
      })
    }
    return cards
  }

  // 非聚合内容：单个卡片
  return [{ title: '原文', content: cleaned }]
}

/** 清理原文格式 */
function cleanRawText(text: string): string {
  return text
    // 去掉连续分割线
    .replace(/[-=]{3,}/g, '')
    // 合并连续空行（>2 个换行 → 1 个）
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

function formatNumber(n: any): string {
  const num = Number(n)
  if (isNaN(num)) return String(n)
  if (num >= 10000) return (num / 10000).toFixed(1) + '万'
  return String(num)
}

const SkeletonContent: React.FC = () => (
  <div className="space-y-4 animate-pulse" data-testid="skeleton">
    <div className="h-3 bg-[#E8EAED] rounded w-3/4" />
    <div className="h-3 bg-[#E8EAED] rounded w-1/2" />
    <div className="h-20 bg-[#E8EAED] rounded-lg" />
    <div className="h-32 bg-[#E8EAED] rounded-lg" />
  </div>
)
