/**
 * SearchPanel — 资源搜索面板（重设计版）
 *
 * 不再是独立 tab，而是嵌入在 SourcePanel 中的搜索区域。
 * - 紧凑搜索栏（输入框 + 搜索按钮一体）
 * - 单行水平滚动平台 pills
 * - 搜索结果 / 进度 / 历史
 */
import React, { useState, useRef, useCallback, useEffect } from 'react'
import { SearchResultItem } from './SearchResultItem'
import { SearchHistoryCard } from './SearchHistoryCard'
import { PlatformIcon } from '../ui/PlatformIcon'
import { useSearchStore } from '../../store/searchStore'
import type { SearchResult, PlatformType, SearchStage } from '../../types'

const PLATFORMS: { key: PlatformType; label: string; disabled?: boolean; tooltip?: string }[] = [
  { key: 'xiaohongshu', label: '小红书' },
  { key: 'zhihu', label: '知乎' },
  { key: 'github', label: 'GitHub' },
  { key: 'bilibili', label: 'B站', disabled: true, tooltip: '即将支持' },
  { key: 'youtube', label: 'YouTube', disabled: true, tooltip: '即将支持' },
  { key: 'google', label: 'Google', disabled: true, tooltip: '即将支持' },
  { key: 'wechat', label: '微信', disabled: true, tooltip: '即将支持' },
  { key: 'stackoverflow', label: 'SO', disabled: true, tooltip: '即将支持' },
]

/** 根据 SSE stage 字段生成中文状态文案 */
function stageToMessage(stage: SearchStage, evt?: any): string {
  switch (stage) {
    case 'searching':
      return evt?.message || '正在搜索...'
    case 'filtering':
      return evt?.message || `已获取 ${evt?.total ?? 0} 条，正在初筛...`
    case 'extracting': {
      const completed = evt?.completed ?? 0
      const total = evt?.total ?? 0
      return evt?.message || `正在提取详情（${completed}/${total}）...`
    }
    case 'evaluating':
      return 'AI 正在评估内容质量...'
    case 'error':
      return evt?.message || '搜索出错'
    default:
      return ''
  }
}

interface SearchPanelProps {
  planId?: string
  onAddToMaterials: (results: SearchResult[]) => void
  onViewDetail?: (result: SearchResult) => void
  /** 选中数量变化时通知父组件，附带触发添加的回调 */
  onCheckedChange?: (count: number, triggerAdd: (() => void) | null) => void
}

/** 解析 SSE done 事件中的结果列表 */
function parseResults(evt: any): SearchResult[] {
  return (evt.results ?? [])
    .map((item: any) => ({
      id: item.id,
      title: item.title,
      url: item.url,
      platform: item.platform as PlatformType,
      description: item.description ?? '',
      qualityScore: item.qualityScore ?? 0,
      contentSummary: item.contentSummary,
      engagementMetrics: item.engagementMetrics,
      imageUrls: item.imageUrls,
      topComments: item.topComments,
      contentText: item.contentText,
    }))
    .sort((a: SearchResult, b: SearchResult) => b.qualityScore - a.qualityScore)
}

export const SearchPanel: React.FC<SearchPanelProps> = ({ planId = '', onAddToMaterials, onViewDetail, onCheckedChange }) => {
  const [query, setQuery] = useState('')
  const [selectedPlatforms, setSelectedPlatforms] = useState<Set<PlatformType>>(new Set())
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [expandedHistoryId, setExpandedHistoryId] = useState<string | null>(null)
  const [historyChecked, setHistoryChecked] = useState<Set<string>>(new Set())
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const history = useSearchStore(s => s.history)
  const activeSearch = useSearchStore(s => s.activeSearch)

  // 从 store 派生的状态
  const results = activeSearch?.results ?? []
  const searchStage = activeSearch?.stage ?? 'idle'
  const stageMessage = activeSearch?.stageMessage ?? ''
  const error = activeSearch?.error ?? ''
  const isSearching = activeSearch != null
    && activeSearch.stage !== 'idle'
    && activeSearch.stage !== 'done'
    && activeSearch.stage !== 'error'

  // 组件挂载时，如果有已完成的搜索结果，恢复 query
  useEffect(() => {
    if (activeSearch?.query && activeSearch.stage === 'done') {
      setQuery(activeSearch.query)
    }
  }, [])

  const togglePlatform = (p: PlatformType) => {
    setSelectedPlatforms(prev => {
      const next = new Set(prev)
      next.has(p) ? next.delete(p) : next.add(p)
      return next
    })
  }

  const handleSearch = useCallback(async () => {
    if (!query.trim()) return

    const store = useSearchStore.getState()

    // 取消当前进行中的搜索
    store.activeSearch?.abortController?.abort()
    if (timeoutRef.current) clearTimeout(timeoutRef.current)

    const abortController = new AbortController()
    const platforms = selectedPlatforms.size > 0 ? Array.from(selectedPlatforms) : undefined

    // 初始化 store 中的搜索状态
    const placeholderId = `search-${Date.now()}`
    store.setActiveSearch({
      query: query.trim(),
      platforms: platforms ?? PLATFORMS.filter(p => !p.disabled).map(p => p.key),
      stage: 'searching',
      stageMessage: '正在搜索...',
      results: [],
      error: '',
      abortController,
    })

    // 立即创建"搜索中..."占位历史条目
    store.addEntry(planId, {
      id: placeholderId,
      query: query.trim(),
      platforms: platforms ?? PLATFORMS.filter(p => !p.disabled).map(p => p.key),
      results: [],
      resultCount: 0,
      searchedAt: new Date().toISOString(),
      status: 'searching',
    })

    // 300s 超时（知乎搜索 + LLM 评估可能需要 3-4 分钟）
    timeoutRef.current = setTimeout(() => {
      abortController.abort()
      useSearchStore.getState().updateActiveSearch({
        stage: 'error',
        error: '搜索超时，请重试',
        abortController: null,
      })
    }, 300000)

    try {
      const res = await fetch('/api/search/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: query.trim(), platforms }),
        signal: abortController.signal,
      })

      if (!res.ok || !res.body) {
        throw new Error(`Search failed: ${res.status}`)
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const evt = JSON.parse(line.slice(6))
            const stage = evt.stage as SearchStage | undefined
            const update = useSearchStore.getState().updateActiveSearch

            if (stage === 'searching') {
              update({ stage: 'searching', stageMessage: stageToMessage('searching', evt) })
            } else if (stage === 'filtering') {
              update({ stage: 'filtering', stageMessage: stageToMessage('filtering', evt) })
            } else if (stage === 'extracting') {
              update({ stage: 'extracting', stageMessage: stageToMessage('extracting', evt) })
            } else if (stage === 'evaluating') {
              update({ stage: 'evaluating', stageMessage: stageToMessage('evaluating', evt) })
            } else if (stage === 'done') {
              if (timeoutRef.current) clearTimeout(timeoutRef.current)
              const items = parseResults(evt)
              update({
                stage: 'done',
                stageMessage: '',
                results: items,
                abortController: null,
              })
              useSearchStore.getState().updateEntry(placeholderId, {
                results: items,
                resultCount: items.length,
                status: 'done',
              }, planId)
            } else if (stage === 'error') {
              if (timeoutRef.current) clearTimeout(timeoutRef.current)
              update({
                stage: 'error',
                error: evt.message || '搜索出错',
                abortController: null,
              })
              useSearchStore.getState().updateEntry(placeholderId, {
                status: 'error',
              }, planId)
            }
          } catch { /* 忽略解析错误 */ }
        }
      }
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        useSearchStore.getState().updateActiveSearch({
          stage: 'error',
          error: '搜索失败，请检查网络或重试',
          abortController: null,
        })
      }
    } finally {
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
    }
  }, [query, selectedPlatforms, planId])

  // 清理：只清 timeout，不 abort SSE
  useEffect(() => () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current)
  }, [])

  const toggleCheck = (id: string) => {
    setChecked(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const handleAdd = useCallback(() => {
    const selected = results.filter(r => checked.has(r.id))
    if (selected.length > 0) {
      onAddToMaterials(selected)
      useSearchStore.getState().setActiveSearch(null)
      setChecked(new Set())
      setQuery('')
    }
    // 搜索历史中选中的
    if (historyChecked.size > 0 && expandedHistoryId) {
      const entry = history.find(e => e.id === expandedHistoryId)
      if (entry) {
        const historySelected = entry.results.filter(r => historyChecked.has(r.id))
        if (historySelected.length > 0) {
          onAddToMaterials(historySelected)
        }
      }
      setHistoryChecked(new Set())
    }
  }, [results, checked, historyChecked, expandedHistoryId, history, onAddToMaterials])

  // 合并当前搜索 + 搜索历史的选中数量，通知父组件
  const totalChecked = checked.size + historyChecked.size
  useEffect(() => {
    onCheckedChange?.(totalChecked, totalChecked > 0 ? handleAdd : null)
  }, [totalChecked, handleAdd, onCheckedChange])

  const isActive = isSearching && searchStage !== 'idle' && searchStage !== 'done' && searchStage !== 'error'

  return (
    <div className="flex flex-col gap-2.5">
      {/* 搜索栏标题 */}
      <p className="text-xs font-medium text-[#5F6368] uppercase tracking-wide">搜索资源</p>

      {/* 搜索输入 — 沉浸式大圆角搜索栏 */}
      <div className="flex items-center h-11 rounded-2xl bg-[#F0F2F5] transition-all duration-50 focus-within:bg-white focus-within:ring-2 focus-within:ring-[#D97757]/30 focus-within:shadow-sm">
        <span className="pl-4 pr-2 text-[#9AA0A6] text-sm flex-shrink-0">🔍</span>
        <input
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSearch()}
          placeholder="搜索学习资源..."
          className="flex-1 h-full bg-transparent text-[14px] text-[#1A1A18] placeholder:text-[#9AA0A6] outline-none"
          aria-label="搜索关键词"
        />
        {/* 内嵌搜索/取消按钮 */}
        {isSearching ? (
          <button
            onClick={() => {
              const store = useSearchStore.getState()
              store.activeSearch?.abortController?.abort()
              if (timeoutRef.current) clearTimeout(timeoutRef.current)
              store.updateActiveSearch({
                stage: 'error',
                error: '搜索已取消',
                abortController: null,
              })
              const entry = store.history.find(e => e.status === 'searching')
              if (entry) {
                store.updateEntry(entry.id, { status: 'error' }, planId)
              }
            }}
            aria-label="取消搜索"
            className="flex-shrink-0 mr-1.5 w-8 h-8 flex items-center justify-center rounded-xl text-[#9AA0A6] hover:bg-[#E8EAED] hover:text-[#D93025] transition-colors"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
          </button>
        ) : (
          <button
            onClick={handleSearch}
            disabled={!query.trim()}
            aria-label="搜索"
            className="flex-shrink-0 mr-1.5 w-8 h-8 flex items-center justify-center rounded-xl text-[#D97757] hover:bg-[#FDF5F0] disabled:opacity-40 disabled:hover:bg-transparent transition-colors"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>
          </button>
        )}
      </div>

      {/* 平台选择 — 柔和化药丸/小卡片 */}
      <div className="flex flex-wrap gap-2 pt-1 pb-2">
          {PLATFORMS.map(p => {
             const isSelected = selectedPlatforms.has(p.key)
             return (
              <button
                key={p.key}
                onClick={() => !p.disabled && togglePlatform(p.key)}
                disabled={p.disabled}
                aria-pressed={isSelected}
                aria-label={p.label}
                title={p.disabled ? (p.tooltip ?? p.label) : p.label}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-[12px] transition-all duration-50 ${
                  p.disabled
                    ? 'opacity-40 cursor-not-allowed bg-[#F8F9FA] text-[#9AA0A6] grayscale'
                    : isSelected
                    ? 'bg-[#FFF7ED] text-[#D97757] font-medium border border-[#F2DFD3]'
                    : 'bg-[#F8F9FA] text-[#5F6368] border border-transparent hover:bg-[#F0F2F5]'
                }`}
              >
                <PlatformIcon platform={p.key} size={14} />
                {p.label}
              </button>
             )
          })}
      </div>

      {/* 搜索阶段进度 — 内联化 */}
      {isActive && (
        <div className="flex items-center gap-2.5 px-4 py-3 bg-[#F8F9FA] rounded-xl border border-[#F0F2F5]">
          <span className="relative flex h-2.5 w-2.5 flex-shrink-0 mt-px">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#D97757] opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-[#D97757]"></span>
          </span>
          <span className="text-[13px] text-[#5F6368]">
            {stageMessage || '正在搜索...'}
          </span>
        </div>
      )}

      {error && <p className="text-xs text-red-500">{error}</p>}

      {/* 搜索结果 */}
      {results.length > 0 && (
        <>
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium text-[#5F6368] uppercase tracking-wide">
              搜索结果（{results.length} 条）
            </p>
            <button
              onClick={() => {
                const allIds = new Set(results.map(r => r.id))
                const allChecked = results.every(r => checked.has(r.id))
                setChecked(allChecked ? new Set() : allIds)
              }}
              className="text-[11px] text-[#D97757] hover:text-[#C06144] font-medium transition-colors"
            >
              {results.every(r => checked.has(r.id)) ? '取消全选' : '全选'}
            </button>
          </div>
          <div className="flex flex-col gap-2">
            {results.map(r => (
              <SearchResultItem
                key={r.id}
                result={r}
                checked={checked.has(r.id)}
                onToggle={() => toggleCheck(r.id)}
                onViewDetail={onViewDetail}
              />
            ))}
          </div>
        </>
      )}

      {results.length === 0 && !isSearching && !error && history.length === 0 && (
        <p className="text-xs text-[#9AA0A6] text-center py-2">
          输入关键词搜索学习资源
        </p>
      )}

      {/* 搜索历史 */}
      {history.length > 0 && (
        <div className="flex flex-col gap-1.5 mt-2 pt-3 border-t border-[#E5E5E5]">
          <p className="text-xs font-medium text-[#5F6368] uppercase tracking-wide">
            搜索历史
          </p>
          {history.map(entry => (
            <SearchHistoryCard
              key={entry.id}
              entry={entry}
              isExpanded={expandedHistoryId === entry.id}
              onToggle={() =>
                setExpandedHistoryId(prev => prev === entry.id ? null : entry.id)
              }
              onAddToMaterials={onAddToMaterials}
              onRemove={(id: string) => useSearchStore.getState().removeEntry(id, planId)}
              onViewDetail={onViewDetail}
              onCheckedChange={(ids) => setHistoryChecked(ids)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
