/**
 * ContentViewer — 材料内容查看器
 *
 * - PDF：react-pdf 逐页渲染为 canvas（无工具栏，保留图片）
 * - Markdown：react-markdown + typography 样式
 * - TXT：等宽字体预格式化
 */
import React, { useState, useEffect, useCallback, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import rehypeSlug from 'rehype-slug'
import { Document, Page, pdfjs } from 'react-pdf'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import 'react-pdf/dist/Page/TextLayer.css'
import { Button } from '../ui/Button'

// pdf.js worker
pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`

interface ContentViewerProps {
  materialId: string
  materialName: string
  fileType: 'markdown' | 'pdf' | 'text'
  planId?: string
  onBack: () => void
}

export const ContentViewer: React.FC<ContentViewerProps> = ({
  materialId,
  materialName,
  fileType,
  planId = '',
  onBack,
}) => {
  const isPdf = fileType === 'pdf'
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // PDF state
  const [numPages, setNumPages] = useState(0)
  const containerRef = useRef<HTMLDivElement>(null)
  const [containerWidth, setContainerWidth] = useState(600)

  // 监听容器宽度变化，让 PDF 页面自适应
  useEffect(() => {
    if (!isPdf || !containerRef.current) return
    const obs = new ResizeObserver(entries => {
      for (const e of entries) setContainerWidth(e.contentRect.width)
    })
    obs.observe(containerRef.current)
    return () => obs.disconnect()
  }, [isPdf])

  // 非 PDF 文件 fetch 文本内容
  const fetchContent = useCallback(async () => {
    if (isPdf) { setLoading(false); return }
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`/api/material/${materialId}/content?plan_id=${planId}`)
      if (!res.ok) throw new Error(`加载失败 (${res.status})`)
      const data = await res.json()
      if (data.error) setError(data.error)
      else setContent(data.content || '')
    } catch (err: any) {
      setError(err.message || '加载内容失败')
    } finally {
      setLoading(false)
    }
  }, [materialId, planId, isPdf])

  useEffect(() => { fetchContent() }, [fetchContent])

  const pdfUrl = `/api/material/${materialId}/raw`
  const typeIcon = fileType === 'pdf' ? '📕' : fileType === 'markdown' ? '📝' : '📄'

  return (
    <div className="flex flex-col h-full bg-white dark:bg-dark-bg" role="article" aria-label={`查看: ${materialName}`}>
      {/* Header */}
      <div className="flex items-center gap-3 px-5 py-3.5 border-b border-border flex-shrink-0">
        <div className="flex-1 min-w-0">
          <h1 className="text-[15px] font-semibold text-text-primary truncate leading-tight">
            {typeIcon} {materialName}
          </h1>
        </div>
        <button
          onClick={onBack}
          aria-label="关闭查看器"
          className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-surface-tertiary transition-colors text-text-secondary flex-shrink-0"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {!isPdf && loading && <LoadingIndicator />}

        {error && !loading && (
          <div className="flex flex-col items-center gap-3 py-12">
            <p className="text-base text-red-500">{error}</p>
            <Button variant="secondary" size="sm" onClick={fetchContent}>重试</Button>
          </div>
        )}

        {/* PDF: react-pdf 逐页渲染 */}
        {isPdf && (
          <div ref={containerRef} className="h-full overflow-y-auto bg-[#F1F3F4] dark:bg-dark-surface">
            <Document
              file={pdfUrl}
              onLoadSuccess={({ numPages: n }) => setNumPages(n)}
              onLoadError={(err) => setError(err.message || 'PDF 加载失败')}
              loading={<LoadingIndicator />}
              className="flex flex-col items-center gap-2 py-4"
            >
              {Array.from({ length: numPages }, (_, i) => (
                <Page
                  key={i}
                  pageNumber={i + 1}
                  width={containerWidth - 32}
                  className="shadow-sm"
                  renderTextLayer={false}
                  renderAnnotationLayer={false}
                />
              ))}
            </Document>
          </div>
        )}

        {/* Markdown */}
        {!isPdf && !loading && !error && content && (
          <div className="h-full overflow-y-auto px-5 py-5">
            {fileType === 'markdown' ? (
              <article className="prose prose-base max-w-none dark:prose-invert
                prose-headings:text-[#202124] prose-headings:font-semibold
                prose-h1:text-2xl prose-h1:border-b prose-h1:border-border prose-h1:pb-2 prose-h1:mb-4
                prose-h2:text-xl prose-h2:mt-8 prose-h2:mb-3
                prose-h3:text-lg prose-h3:mt-6 prose-h3:mb-2
                prose-p:text-[15px] prose-p:leading-7 prose-p:text-[#3C4043]
                prose-a:text-primary prose-a:no-underline hover:prose-a:underline
                prose-strong:text-[#202124]
                prose-code:text-[13px] prose-code:bg-[#F1F3F4] prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:font-mono
                prose-pre:bg-[#F8F9FA] prose-pre:border prose-pre:border-border prose-pre:rounded-lg
                prose-blockquote:border-l-primary prose-blockquote:bg-[#F8F9FA] prose-blockquote:rounded-r-lg prose-blockquote:py-1
                prose-li:text-[15px] prose-li:leading-7 prose-li:text-[#3C4043]
                prose-img:rounded-lg prose-img:shadow-sm
              ">
                <ReactMarkdown rehypePlugins={[rehypeSlug]}>{content}</ReactMarkdown>
              </article>
            ) : (
              <div className="text-[15px] text-[#3C4043] whitespace-pre-wrap break-words leading-7">
                {content}
              </div>
            )}
          </div>
        )}

        {!isPdf && !loading && !error && !content && (
          <p className="text-base text-text-secondary text-center py-12">暂无内容</p>
        )}
      </div>
    </div>
  )
}

const LoadingIndicator: React.FC = () => (
  <div className="flex flex-col items-center gap-3 py-12" data-testid="loading">
    <div className="flex gap-1.5">
      <span className="w-2.5 h-2.5 rounded-full bg-primary animate-bounce [animation-delay:0ms]" />
      <span className="w-2.5 h-2.5 rounded-full bg-primary animate-bounce [animation-delay:150ms]" />
      <span className="w-2.5 h-2.5 rounded-full bg-primary animate-bounce [animation-delay:300ms]" />
    </div>
    <p className="text-sm text-text-secondary">加载内容中...</p>
  </div>
)