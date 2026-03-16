/**
 * ContentViewer — AI 生成内容查看弹窗
 * - 普通内容：ReactMarkdown 渲染
 * - mind-map：markmap 交互式思维导图
 * - progress-report：结构化 JSON 渲染（fallback Markdown）
 * - learning-plan：结构化天数渲染（fallback Markdown）
 */
import React, { useRef, useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import type { GeneratedContent } from '../../types'
import { extractJSON } from '../../utils/jsonRepair'

interface ContentViewerProps {
  content: GeneratedContent
  onClose: () => void
}


/** 思维导图渲染组件 */
const MindMapRenderer: React.FC<{ markdown: string }> = ({ markdown }) => {
  const svgRef = useRef<SVGSVGElement>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let mm: any = null
    let cancelled = false
    const render = async () => {
      try {
        const { Transformer } = await import('markmap-lib')
        const { Markmap } = await import('markmap-view')
        if (cancelled || !svgRef.current) return
        const transformer = new Transformer()
        const { root } = transformer.transform(markdown)
        svgRef.current.innerHTML = ''
        mm = Markmap.create(svgRef.current, { duration: 300, maxWidth: 400 }, root)
        // 初始放大：等 fit 完成后 rescale 1.5x（相当于滚轮放大 ~2 次）
        setTimeout(() => {
          if (!cancelled && mm) {
            mm.rescale(1.5).catch(() => {})
          }
        }, 400)
      } catch { if (!cancelled) setError(true) }
    }
    render()
    return () => { cancelled = true; mm?.destroy?.() }
  }, [markdown])

  if (error) return <ReactMarkdown>{markdown}</ReactMarkdown>
  return (
    <div className="flex flex-col flex-1 min-h-0">
      <svg ref={svgRef} className="w-full flex-1" style={{ minHeight: 600 }} />
      <div className="text-center text-xs text-gray-400 py-2 flex-shrink-0">
        滚轮缩放 · 拖拽平移
      </div>
    </div>
  )
}

/** 进度报告 JSON 渲染 */
const ProgressReportRenderer: React.FC<{ content: any }> = ({ content }) => {
  const data = extractJSON(content)
  const textFallback = typeof content === 'string' ? content : JSON.stringify(content, null, 2);
  if (!data || typeof data !== 'object') return <ReactMarkdown>{textFallback}</ReactMarkdown>


  return (
    <div className="space-y-6">
      {data.summary && (
        <div>
          <h3 className="text-base font-semibold text-gray-800 mb-2">📋 总结</h3>
          {typeof data.summary === 'object' ? (
            <div className="space-y-2">
              {(data.summary.completedDays !== undefined || data.summary.totalDays !== undefined) && (
                <div className="flex items-center gap-3">
                  <div className="flex-1 bg-gray-100 rounded-full h-2">
                    <div className="bg-green-500 h-2 rounded-full transition-all"
                      style={{ width: `${Math.min(100, data.summary.percentage ?? (data.summary.totalDays ? Math.round((data.summary.completedDays / data.summary.totalDays) * 100) : 0))}%` }} />
                  </div>
                  <span className="text-sm font-semibold text-green-600 whitespace-nowrap">
                    {data.summary.completedDays ?? 0} / {data.summary.totalDays ?? 0} 天
                    {data.summary.percentage !== undefined && ` (${data.summary.percentage}%)`}
                  </span>
                </div>
              )}
              {data.summary.text && (
                <p className="text-sm text-gray-600 leading-relaxed">{data.summary.text}</p>
              )}
              {!data.summary.text && !data.summary.totalDays && (
                <p className="text-sm text-gray-600 leading-relaxed">{JSON.stringify(data.summary)}</p>
              )}
            </div>
          ) : (
            <p className="text-sm text-gray-600 leading-relaxed">{data.summary}</p>
          )}
        </div>
      )}
      {data.knowledgeGraph && Array.isArray(data.knowledgeGraph) && (
        <div>
          <h3 className="text-base font-semibold text-gray-800 mb-2">🧠 知识图谱</h3>
          <div className="flex flex-wrap gap-2">
            {data.knowledgeGraph.map((item: any, i: number) => {
              // 兼容两种格式：{topic, status} 和 {node, connections}
              const label = typeof item === 'string' ? item : (item.topic || item.node || item.name || JSON.stringify(item))
              const status = typeof item === 'object' ? item.status : null
              const connections = typeof item === 'object' && Array.isArray(item.connections) ? item.connections : null
              return (
                <div key={i} className="flex flex-col gap-1">
                  <span className={`px-3 py-1.5 rounded-full text-xs font-medium ${status === 'mastered' ? 'bg-green-100 text-green-700' :
                    status === 'learning' ? 'bg-yellow-100 text-yellow-700' :
                      'bg-blue-50 text-blue-700'
                    }`}>{label}</span>
                  {connections && connections.length > 0 && (
                    <div className="flex flex-wrap gap-1 ml-2">
                      {connections.map((c: string, j: number) => (
                        <span key={j} className="px-2 py-0.5 rounded text-[10px] bg-gray-100 text-gray-500">↳ {c}</span>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
      {data.timeline && Array.isArray(data.timeline) && (
        <div>
          <h3 className="text-base font-semibold text-gray-800 mb-2">📅 学习时间线</h3>
          <div className="space-y-2">
            {data.timeline.map((entry: any, i: number) => {
              // 兼容两种格式：对象 {day, title, status, score} 和纯数字
              const isObj = typeof entry === 'object' && entry !== null
              const dayLabel = isObj ? (entry.day || entry.date || `Day ${i + 1}`) : `Day ${entry}`
              const title = isObj ? (entry.title || entry.topic || entry.content || '') : ''
              const status = isObj ? entry.status : undefined
              const isCompleted = status === 'completed' || status === '已完成' || (isObj && entry.completed)
              return (
                <div key={i} className="flex items-center gap-3">
                  <div className={`w-3 h-3 rounded-full flex-shrink-0 ${isCompleted ? 'bg-green-500' : 'bg-gray-300'}`} />
                  <span className="text-sm font-medium text-gray-700 whitespace-nowrap">{dayLabel}</span>
                  {title && <span className="text-sm text-gray-500 flex-1 truncate">{title}</span>}
                  {isObj && entry.score != null && (
                    <span className="text-xs text-gray-400 flex-shrink-0">{entry.score}分</span>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
      {data.weakPoints && Array.isArray(data.weakPoints) && data.weakPoints.length > 0 && (
        <div>
          <h3 className="text-base font-semibold text-gray-800 mb-2">⚠️ 薄弱环节</h3>
          <ul className="list-disc list-inside space-y-1">
            {data.weakPoints.map((wp: any, i: number) => (
              <li key={i} className="text-sm text-gray-600">{typeof wp === 'string' ? wp : wp.topic || wp.description || JSON.stringify(wp)}</li>
            ))}
          </ul>
        </div>
      )}
      {data.nextSteps && Array.isArray(data.nextSteps) && (
        <div>
          <h3 className="text-base font-semibold text-gray-800 mb-2">🚀 下一步建议</h3>
          <ul className="list-disc list-inside space-y-1">
            {data.nextSteps.map((step: any, i: number) => (
              <li key={i} className="text-sm text-gray-600">{typeof step === 'string' ? step : step.description || step.action || JSON.stringify(step)}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

/** 学习计划 JSON 渲染 */
const LearningPlanRenderer: React.FC<{ content: any }> = ({ content }) => {
  const data = extractJSON(content)
  const textFallback = typeof content === 'string' ? content : JSON.stringify(content, null, 2);
  if (!data) return <ReactMarkdown>{textFallback}</ReactMarkdown>

  const days = data.days || (Array.isArray(data) ? data : null)
  if (!days) return <ReactMarkdown>{textFallback}</ReactMarkdown>

  return (
    <div className="space-y-4">
      {days.map((day: any, i: number) => (
        <div key={i} className="border border-gray-200 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2">
            <span className="w-8 h-8 rounded-lg bg-green-100 text-green-700 flex items-center justify-center text-sm font-bold">
              {day.dayNumber || i + 1}
            </span>
            <h4 className="text-sm font-semibold text-gray-800">{day.title}</h4>
          </div>
          {day.tasks && Array.isArray(day.tasks) && (
            <ul className="ml-10 space-y-1 mb-2">
              {day.tasks.map((t: any, j: number) => (
                <li key={j} className="text-sm text-gray-600 flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-gray-400 flex-shrink-0" />
                  {typeof t === 'string' ? t : t.title || JSON.stringify(t)}
                </li>
              ))}
            </ul>
          )}
          {day.learningObjectives && (
            <p className="text-xs text-orange-600 ml-10">🎯 {Array.isArray(day.learningObjectives) ? day.learningObjectives.join('、') : day.learningObjectives}</p>
          )}
          {day.knowledgePoints && Array.isArray(day.knowledgePoints) && (
            <div className="flex flex-wrap gap-1 ml-10 mt-1">
              {day.knowledgePoints.map((kp: string, k: number) => (
                <span key={k} className="px-2 py-0.5 bg-purple-50 text-purple-600 rounded text-xs">{kp}</span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

/** 测验渲染组件 — JSON 结构化渲染 + 答案 spoiler */
const QuizSpoiler: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [revealed, setRevealed] = useState(false)
  return (
    <div
      onClick={() => setRevealed(true)}
      className={`relative rounded-lg cursor-pointer select-none overflow-hidden transition-all duration-500 ${
        revealed ? '' : 'hover:opacity-90 active:opacity-80'
      }`}
      title={revealed ? undefined : '点击查看答案'}
    >
      <div className={`px-3 py-2 transition-opacity duration-500 ${revealed ? 'opacity-100' : 'opacity-0'}`}>
        {children}
      </div>
      {!revealed && (
        <div
          className="absolute inset-0 rounded-lg flex items-center justify-center"
          style={{
            background: `repeating-linear-gradient(-45deg, #e5e7eb, #e5e7eb 4px, #d1d5db 4px, #d1d5db 8px)`,
          }}
        >
          <span className="text-sm text-gray-500 bg-white/80 px-3 py-1 rounded-full backdrop-blur-sm">
            👆 点击揭晓答案
          </span>
        </div>
      )}
    </div>
  )
}

const TYPE_LABELS: Record<string, string> = {
  single: '单选题', multiple: '多选题', truefalse: '判断题', short: '简答题',
}

const QuizRenderer: React.FC<{ content: any }> = ({ content }) => {
  const data = extractJSON(content)
  const textFallback = typeof content === 'string' ? content : JSON.stringify(content, null, 2)

  // fallback: 无法解析 JSON 则用 markdown 渲染
  if (!data || !data.questions || !Array.isArray(data.questions)) {
    return <ReactMarkdown>{textFallback}</ReactMarkdown>
  }

  return (
    <div className="space-y-6">
      {data.questions.map((q: any, i: number) => (
        <div key={i} className="border border-gray-200 rounded-xl p-4">
          {/* 题号 + 题型标签 */}
          <div className="flex items-start gap-3 mb-3">
            <span className="w-7 h-7 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center text-sm font-bold flex-shrink-0">
              {i + 1}
            </span>
            <div className="flex-1">
              <div className="flex items-center gap-2 mb-1">
                {q.type && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 font-medium">
                    {TYPE_LABELS[q.type] || q.type}
                  </span>
                )}
              </div>
              <p className="text-sm text-gray-800 leading-relaxed">{q.question}</p>
            </div>
          </div>

          {/* 选项列表 */}
          {q.options && Array.isArray(q.options) && q.options.length > 0 && (
            <div className="ml-10 space-y-1.5 mb-3">
              {q.options.map((opt: string, j: number) => (
                <div key={j} className="flex items-start gap-2 text-sm text-gray-600">
                  <span className="w-5 h-5 rounded border border-gray-300 flex items-center justify-center text-xs text-gray-400 flex-shrink-0 mt-0.5">
                    {String.fromCharCode(65 + j)}
                  </span>
                  <span>{typeof opt === 'string' ? opt.replace(/^[A-D][\.\)、]\s*/, '') : opt}</span>
                </div>
              ))}
            </div>
          )}

          {/* 答案 + 解析（spoiler 遮罩） */}
          <div className="ml-10">
            <QuizSpoiler>
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-green-600 bg-green-50 px-2 py-0.5 rounded">正确答案</span>
                  <span className="text-sm font-medium text-gray-800">{q.answer}</span>
                </div>
                {q.explanation && (
                  <p className="text-sm text-gray-600 leading-relaxed">{q.explanation}</p>
                )}
              </div>
            </QuizSpoiler>
          </div>
        </div>
      ))}
    </div>
  )
}

export const ContentViewer: React.FC<ContentViewerProps> = ({ content, onClose }) => {
  const totalVersions = (content.versions?.length || 0) + 1
  const [viewingVersion, setViewingVersion] = useState(content.version || 1)

  // Build version list: current + history
  const allVersions = [
    { content: content.content, createdAt: content.createdAt, version: content.version || 1 },
    ...(content.versions || []),
  ].sort((a, b) => b.version - a.version)

  const current = allVersions.find(v => v.version === viewingVersion) || allVersions[0]

  const handleExport = () => {
    const textData = typeof current.content === 'string' ? current.content : JSON.stringify(current.content, null, 2);
    const blob = new Blob([textData], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${content.title}-v${viewingVersion}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  const renderContent = (text: any) => {
    if (content.type === 'mind-map') return <MindMapRenderer markdown={typeof text === 'string' ? text : JSON.stringify(text, null, 2)} />
    if (content.type === 'progress-report') return <ProgressReportRenderer content={text} />
    if (content.type === 'learning-plan') return <LearningPlanRenderer content={text} />
    if (content.type === 'quiz') return <QuizRenderer content={text} />
    // Fallback: 如果内容包含 days 数组结构，也用 LearningPlanRenderer
    const maybeJSON = extractJSON(text)
    if (maybeJSON?.days && Array.isArray(maybeJSON.days)) {
      return <LearningPlanRenderer content={text} />
    }
    const mdText = typeof text === 'string' ? text : (text ? JSON.stringify(text, null, 2) : '（内容为空）');
    return <ReactMarkdown>{mdText}</ReactMarkdown>
  }

  const fmtDate = (iso: string) => {
    try { return new Date(iso).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) } catch { return iso }
  }

  const isMindMap = content.type === 'mind-map'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={onClose}>
      <div className={`bg-white dark:bg-dark-surface rounded-2xl shadow-2xl flex flex-col overflow-hidden ${
        isMindMap ? 'w-[95vw] max-w-[1400px] h-[85vh]' : 'w-[90vw] max-w-[900px] max-h-[90vh]'
      }`}
        onClick={e => e.stopPropagation()}>
        {/* 标题栏 */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-[#DADCE0] dark:border-dark-border flex-shrink-0">
          <div className="flex items-center gap-3">
            <span className="text-base font-semibold text-[#202124] dark:text-dark-text">
              {content.title}
            </span>
            {totalVersions > 1 && (
              <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">
                V{viewingVersion} · {fmtDate(current.createdAt)}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {totalVersions > 1 && (
              <div className="flex items-center gap-1 mr-2">
                <button onClick={() => setViewingVersion(v => Math.max(1, v - 1))}
                  disabled={viewingVersion <= 1}
                  className="w-7 h-7 flex items-center justify-center rounded-lg text-gray-500 hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed text-sm">
                  ‹
                </button>
                <span className="text-xs text-gray-500 min-w-[40px] text-center">{viewingVersion}/{totalVersions}</span>
                <button onClick={() => setViewingVersion(v => Math.min(totalVersions, v + 1))}
                  disabled={viewingVersion >= totalVersions}
                  className="w-7 h-7 flex items-center justify-center rounded-lg text-gray-500 hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed text-sm">
                  ›
                </button>
              </div>
            )}
            <button onClick={handleExport} aria-label="导出"
              className="h-7 px-3 rounded-lg text-xs text-[#5F6368] hover:bg-[#F1F3F4] dark:hover:bg-dark-border transition-colors duration-50 flex items-center gap-1">
              ↓ 导出
            </button>
            <button onClick={onClose} aria-label="关闭"
              className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-gray-100 text-[#5F6368] hover:text-[#202124] transition-colors text-xl">
              ×
            </button>
          </div>
        </div>
        {/* 内容区 */}
        <div className={`flex-1 ${isMindMap ? 'flex flex-col min-h-0 px-2 py-2' : 'overflow-y-auto px-6 py-5'} ${content.type === 'mind-map' ? '' : content.type === 'progress-report' || content.type === 'learning-plan' ? '' : 'prose prose-sm max-w-none dark:prose-invert'}`}>
          {renderContent(current.content)}
        </div>
      </div>
    </div>
  )
}
