/**
 * SourcePanel — 左侧学习材料面板
 *
 * 双 tab 布局：
 * - 「来源」tab：上传区 + 材料列表
 * - 「搜索」tab：SearchPanel（平台选择 + 搜索历史 + 结果）
 */
import React, { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { MaterialList } from './MaterialList'
import { MaterialIcon } from './MaterialItem'
import { SearchPanel } from './SearchPanel'
import { UploadArea } from './UploadArea'
import { PreviewPopup } from './PreviewPopup'
import { ContentViewer } from './ContentViewer'
import { useSourceStore } from '../../store/sourceStore'
import { useSearchStore } from '../../store/searchStore'
import type { Material, SearchResult } from '../../types'

function isLocalFile(m: Material): boolean {
  return m.type === 'other' || !m.url
}

function inferFileType(name: string): 'markdown' | 'pdf' | 'text' {
  const lower = name.toLowerCase()
  if (lower.endsWith('.md') || lower.endsWith('.markdown')) return 'markdown'
  if (lower.endsWith('.pdf')) return 'pdf'
  return 'text'
}

interface SourcePanelProps {
  planId?: string
  onReadingChange?: (reading: boolean) => void
  isCollapsed?: boolean
  onToggleCollapse?: () => void
}

export const SourcePanel: React.FC<SourcePanelProps> = ({
  planId = '', onReadingChange, isCollapsed = false, onToggleCollapse
}) => {
  const [tab, setTab] = useState<'sources' | 'search'>('sources')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [previewResult, setPreviewResult] = useState<SearchResult | null>(null)
  const [viewingMaterial, setViewingMaterial] = useState<Material | null>(null)
  const [hoveredFile, setHoveredFile] = useState<{ id: string, rect: DOMRect } | null>(null)
  const [searchCheckedCount, setSearchCheckedCount] = useState(0)
  const [searchTriggerAdd, setSearchTriggerAdd] = useState<(() => void) | null>(null)
  const { materials, removeMaterial, addMaterial } = useSourceStore()
  const pendingPreview = useSourceStore(s => s.pendingPreview)

  // 聊天区搜索结果点击 → 打开 PreviewPopup
  useEffect(() => {
    if (pendingPreview) {
      setPreviewResult(pendingPreview)
      onReadingChange?.(true)
      useSourceStore.getState().setPendingPreview(null)
    }
  }, [pendingPreview]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const tempMats = materials.filter(m => m.id.startsWith('temp-'))
    tempMats.forEach(m => removeMaterial(m.id))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handleRemove = async (id: string) => {
    removeMaterial(id)
    try {
      await fetch(`/api/material/${id}?plan_id=${planId}`, { method: 'DELETE' })
    } catch {
      // quiet
    }
  }

  const handleSelect = async (id: string) => {
    if (selectedId === id) {
      setSelectedId(null)
      return
    }
    setSelectedId(id)

    const mat = materials.find(m => m.id === id)
    if (!mat) return

    // 标记为已查看
    if (!mat.viewedAt) {
      useSourceStore.getState().updateMaterial(id, { viewedAt: new Date().toISOString() })
      fetch(`/api/material/${id}/viewed`, { method: 'PATCH' }).catch(() => {})
    }

    if (isLocalFile(mat)) {
      setViewingMaterial(mat)
      onReadingChange?.(true)
    } else {
      onReadingChange?.(true)
      const detail = useSearchStore.getState().getResultDetail(id)
      if (detail) {
        setPreviewResult(detail)
      } else {
        // Fallback: 从 mat.extraData 构建 SearchResult（兼容 snake_case / camelCase）
        const e = mat.extraData ?? {}
        setPreviewResult({
          id: mat.id,
          title: mat.name,
          url: mat.url || '',
          platform: mat.type,
          description: e.description ?? '',
          qualityScore: e.qualityScore ?? e.quality_score ?? 0,
          contentSummary: e.contentSummary ?? e.content_summary ?? '',
          contentText: e.contentText ?? e.content_text,
          engagementMetrics: e.engagementMetrics ?? e.engagement_metrics ?? {},
          imageUrls: e.imageUrls ?? e.image_urls ?? [],
          topComments: e.topComments ?? e.comments_preview ?? [],
        })
      }
    }
  }

  const handleAddFromSearch = (results: SearchResult[]) => {
    useSearchStore.getState().saveResultDetails(results)
    results.forEach(r => {
      addMaterial({
        id: r.id,
        type: r.platform,
        name: r.title.slice(0, 40),
        url: r.url,
        status: 'ready',
        addedAt: new Date().toISOString(),
      })
    })

    // 持久化到后端数据库
    if (planId) {
      fetch('/api/materials/from-search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          items: results.map(r => ({
            id: r.id,
            planId: planId,
            platform: r.platform,
            name: r.title.slice(0, 40),
            url: r.url,
            extraData: {
              description: r.description,
              qualityScore: r.qualityScore,
              contentSummary: r.contentSummary,
              engagementMetrics: r.engagementMetrics,
              imageUrls: r.imageUrls,
              topComments: r.topComments,
              contentText: r.contentText,
            },
          })),
        }),
      }).catch(() => { /* 静默失败 */ })
    }

    // 异步触发深度分析（不阻塞 UI）
    results.forEach(r => {
      useSearchStore.getState().markDeepAnalysisPending(r.id)
      fetch('/api/resource/deep-analysis', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          materialId: r.id,
          title: r.title,
          url: r.url,
          platform: r.platform,
          description: r.description,
          contentSummary: r.contentSummary ?? '',
          topComments: r.topComments ?? [],
          engagementMetrics: r.engagementMetrics ?? {},
        }),
      })
        .then(res => res.ok ? res.json() : null)
        .then(data => {
          if (data) {
            useSearchStore.getState().updateResultDetail(r.id, {
              contentSummary: data.contentSummary,
            })
          }
        })
        .catch(() => { /* 静默失败 */ })
        .finally(() => {
          useSearchStore.getState().markDeepAnalysisDone(r.id)
        })
    })
  }

  return (
    <div className="flex flex-col h-full overflow-hidden relative">
      {previewResult && (
        <PreviewPopup
          result={previewResult}
          onClose={() => { setPreviewResult(null); setSelectedId(null); onReadingChange?.(false) }}
          onRefresh={() => {
            if (previewResult) {
              useSearchStore.getState().saveResultDetails([previewResult])
            }
          }}
        />
      )}

      {viewingMaterial && (
        <div className="absolute inset-0 z-50 bg-white dark:bg-dark-surface overflow-hidden">
          <ContentViewer
            materialId={viewingMaterial.id}
            materialName={viewingMaterial.name}
            fileType={inferFileType(viewingMaterial.name)}
            planId={planId}
            onBack={() => { setViewingMaterial(null); setSelectedId(null); onReadingChange?.(false) }}
          />
        </div>
      )}

      {/* 顶栏：tab 切换 + 折叠按钮 */}
      <div className={`flex items-center h-[68px] flex-shrink-0 ${isCollapsed ? 'justify-center px-0' : 'px-4 justify-between border-b border-[#E5E5E5]'}`}>
        {!isCollapsed && (
          <div className="flex items-center gap-0 h-full pt-1">
            <button
              onClick={() => setTab('sources')}
              className={`relative px-3 h-full flex items-center gap-1 text-sm transition-colors ${tab === 'sources' ? 'text-[#202124] font-medium' : 'text-[#9AA0A6] hover:text-[#5F6368]'}`}
            >
              来源
              {materials.length > 0 && (
                <span className="text-[11px] bg-[#F2DFD3] text-[#D97757] w-5 h-5 rounded-full inline-flex items-center justify-center font-medium">
                  {materials.length}
                </span>
              )}
              {tab === 'sources' && <span className="absolute bottom-0 left-3 right-3 h-[3px] bg-[#D97757] rounded-t-sm" />}
            </button>
            <button
              onClick={() => setTab('search')}
              className={`relative px-3 h-full flex items-center text-sm transition-colors ${tab === 'search' ? 'text-[#202124] font-medium' : 'text-[#9AA0A6] hover:text-[#5F6368]'}`}
            >
              搜索
              {tab === 'search' && <span className="absolute bottom-0 left-3 right-3 h-[3px] bg-[#D97757] rounded-t-sm" />}
            </button>
          </div>
        )}
        <button
          aria-label={isCollapsed ? "展开侧边栏" : "收起侧边栏"}
          onClick={onToggleCollapse}
          className="w-8 h-8 flex items-center justify-center rounded-lg text-[#5F6368] hover:bg-[#F1F3F4] transition-colors duration-50"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="9" y1="3" x2="9" y2="21"/></svg>
        </button>
      </div>

      {!isCollapsed ? (
        <div className="flex-1 overflow-y-auto scrollbar-thin px-4 py-3">
          {tab === 'sources' ? (
            <div className="flex flex-col gap-4">
              <UploadArea planId={planId} />
              <MaterialList
                materials={materials}
                planId={planId}
                selectedId={selectedId ?? undefined}
                onSelect={handleSelect}
                onRemove={handleRemove}
              />
            </div>
          ) : (
            <SearchPanel
              planId={planId}
              onAddToMaterials={handleAddFromSearch}
              onViewDetail={(r) => { setPreviewResult(r); onReadingChange?.(true) }}
              onCheckedChange={(count, triggerAdd) => {
                setSearchCheckedCount(count)
                setSearchTriggerAdd(() => () => triggerAdd?.())
              }}
            />
          )}
        </div>
      ) : (
        /* 折叠态：图标列表 */
        <div className="flex-1 overflow-y-auto scrollbar-thin py-4">
          <ul className="flex flex-col items-center gap-3 w-full relative">
            <li
              className="w-10 h-10 flex items-center justify-center rounded-full text-[#5F6368] hover:bg-[#F1F3F4] transition-colors duration-50 cursor-pointer text-xl"
              onClick={onToggleCollapse}
            >
              +
            </li>
            {materials.map(m => (
              <li key={m.id} onClick={() => handleSelect(m.id)}
                onMouseEnter={(e) => setHoveredFile({ id: m.id, rect: e.currentTarget.getBoundingClientRect() })}
                onMouseLeave={() => setHoveredFile(null)}
                draggable
                onDragStart={(e) => {
                  e.dataTransfer.effectAllowed = 'move'
                  e.dataTransfer.setData('application/material', JSON.stringify({
                    id: m.id, name: m.name, platform: m.type,
                  }))
                }}
                className="group relative flex items-center justify-center w-full focus:outline-none">
                <div className={`w-10 h-10 flex items-center justify-center rounded-full cursor-pointer transition-all duration-50 ${selectedId === m.id ? 'bg-[#F2DFD3]' : 'hover:bg-[#F1F3F4]'}`}>
                  <MaterialIcon material={m} className="w-6 h-7 text-[10px]" />
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 浮动添加按钮 — 选中搜索结果时固定在面板底部 */}
      {!isCollapsed && tab === 'search' && searchCheckedCount > 0 && searchTriggerAdd && (
        <div className="flex-shrink-0 px-4 py-2 border-t border-[#E5E5E5] bg-white dark:bg-dark-surface shadow-[0_-4px_12px_rgba(0,0,0,0.06)]">
          <button
            onClick={searchTriggerAdd}
            className="w-full h-9 rounded-lg bg-[#D97757] hover:bg-[#C06144] text-white text-sm font-medium transition-colors"
          >
            加入学习材料（{searchCheckedCount} 项已选）
          </button>
        </div>
      )}

      {/* Tooltip Portal */}
      {hoveredFile && isCollapsed && createPortal(
        <div style={{ top: hoveredFile.rect.top + (hoveredFile.rect.height / 2), left: hoveredFile.rect.right + 8, transform: 'translateY(-50%)' }}
          className="fixed z-[9999] px-3 py-1.5 bg-[#1E1E1E] text-white text-[13px] whitespace-nowrap rounded-md shadow-lg pointer-events-none fade-in duration-50">
          {materials.find(m => m.id === hoveredFile.id)?.name}
        </div>,
        document.body
      )}
    </div>
  )
}
