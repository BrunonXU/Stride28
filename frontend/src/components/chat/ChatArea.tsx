import React, { useRef, useEffect, useState, useCallback, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import { MessageList } from './MessageList'
import { ChatInput } from './ChatInput'
import { useChatStore } from '../../store/chatStore'
import { useSourceStore } from '../../store/sourceStore'
import { useSSE } from '../../hooks/useSSE'
import { InlineSearchResults } from './InlineSearchResults'
import { SearchProgress } from '../ui/SearchProgress'
import type { SearchProgressStage } from '../ui/SearchProgress'

interface ChatAreaProps {
  planId?: string
}

export const ChatArea: React.FC<ChatAreaProps> = ({ planId = '' }) => {
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const isAutoScrollEnabled = useRef(true)
  const [dragOver, setDragOver] = useState(false)
  const {
    messages,
    isStreaming,
    streamingContent,
    attachMaterial,
    clearMessages,
    searchResults,
    statusMessage,
    statusNode,
    searchStage,
  } = useChatStore()
  const { materials } = useSourceStore()
  const hasMaterials = materials.length > 0
  const { sendMessage, cancel } = useSSE(planId)

  // 流式输出中的引用标注处理
  const processedStreamingContent = useMemo(() => {
    if (!streamingContent || !searchResults?.length) return streamingContent
    // 匹配 [1] [2] 等引用标注，替换为 markdown 链接
    return streamingContent.replace(/\[(\d+)\]/g, (match, numStr) => {
      const idx = parseInt(numStr, 10) - 1
      if (idx >= 0 && idx < searchResults.length) {
        const r = searchResults[idx]
        return `[\\[${numStr}\\]](${r.url} "${r.title}")`
      }
      return match
    })
  }, [streamingContent, searchResults])

  const handleScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const { scrollTop, scrollHeight, clientHeight } = e.currentTarget
    // 如果距离底部只有轻微像素差距，则认为触底。考虑到可能有的设备缩放导致小数，放宽到 60px
    isAutoScrollEnabled.current = scrollHeight - Math.ceil(scrollTop) - clientHeight <= 60
  }, [])

  // 新消息/流式内容变化时，仅在用户处于最底部时才跟随滚动
  useEffect(() => {
    if (isAutoScrollEnabled.current) {
      // 正在流式输出时用 'auto'（瞬间同步避免动画冲突卡死），不输出时用 'smooth'
      const behavior = isStreaming ? 'auto' : 'smooth'
      messagesEndRef.current?.scrollIntoView({ behavior })
    }
  }, [messages.length, streamingContent, isStreaming])

  const handleDragOver = (e: React.DragEvent) => {
    if (e.dataTransfer.types.includes('application/material')) {
      e.preventDefault()
      setDragOver(true)
    }
  }
  const handleDragLeave = (e: React.DragEvent) => {
    // 只在离开整个区域时取消
    if (e.currentTarget.contains(e.relatedTarget as Node)) return
    setDragOver(false)
  }
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    try {
      const raw = e.dataTransfer.getData('application/material')
      if (raw) {
        const mat = JSON.parse(raw)
        attachMaterial(mat)
      }
    } catch { /* ignore */ }
  }

  return (
    <div
      className="flex flex-col h-full overflow-hidden bg-white relative"
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* 拖拽覆盖层 */}
      {dragOver && (
        <div className="absolute inset-0 z-50 bg-[#D97757]/5 border-2 border-dashed border-[#D97757]/40 rounded-xl flex items-center justify-center pointer-events-none">
          <div className="bg-white/90 px-6 py-4 rounded-2xl shadow-lg text-center">
            <span className="text-2xl block mb-1">📎</span>
            <span className="text-sm text-[#D97757] font-medium">松开以附加材料到对话</span>
          </div>
        </div>
      )}

      {/* 顶部标题栏 */}
      <div className="h-[68px] flex items-center justify-between px-8 flex-shrink-0 border-b border-[#E5E5E5] bg-white z-10">
        <span className="text-base font-semibold text-[#1A1A18]">对话</span>
        {messages.length > 0 && !isStreaming && (
          <button
            onClick={() => {
              if (window.confirm('确定清空对话？历史记忆会保留，AI 不会失忆。')) {
                clearMessages(planId)
              }
            }}
            className="text-xs text-gray-400 hover:text-[#D97757] transition-colors px-2 py-1 rounded-md hover:bg-[#FFF7ED]"
            title="清空对话消息（记忆会保留）"
          >
            清空对话
          </button>
        )}
      </div>

      {/* 消息和输入框的共同滚动容器（统一背景色消除断层） */}
      <div className="flex-1 overflow-hidden flex flex-col bg-[#FDFDFD]">
        {/* 标题栏下方留白（与其他面板一致） */}
        <div className="h-4 flex-shrink-0" />

        {/* 消息列表（只有这里滚动） */}
        <div
          ref={scrollContainerRef}
          onScroll={handleScroll}
          className="flex-1 overflow-y-auto scrollbar-thin flex flex-col items-center"
        >
          <div className="w-full max-w-3xl px-8 pt-4 pb-6 flex-1 flex flex-col">
            <MessageList messages={messages} isStreaming={isStreaming && !streamingContent} planId={planId} />

            {/* 搜索结果卡片（流式期间展示在 AI 回复上方） */}
            {isStreaming && searchResults && searchResults.length > 0 && (
              <div className="max-w-[95%] mt-6">
                <InlineSearchResults results={searchResults} planId={planId} />
              </div>
            )}

            {/* 搜索进度指示器（search 节点时显示多阶段进度条） */}
            {isStreaming && statusNode === 'search' && searchStage && !streamingContent && (
              <div className="max-w-[85%] mt-6 mb-2">
                <SearchProgress
                  stage={searchStage as SearchProgressStage}
                  message={statusMessage ?? undefined}
                  compact
                />
              </div>
            )}

            {/* 非搜索节点的状态指示器（意图分析、合成等） */}
            {isStreaming && statusMessage && statusNode !== 'search' && !streamingContent && (
              <div className="flex items-center gap-2 max-w-[85%] mt-6 mb-2">
                <div className="px-4 py-2.5 rounded-2xl bg-[#FFF7ED] border border-[#F2DFD3] text-sm text-[#D97757]">
                  {statusMessage}
                </div>
              </div>
            )}

            {/* 流式输出气泡 */}
            {isStreaming && streamingContent && (
              <div className="flex flex-col gap-2 max-w-[95%] mb-6 mt-6">
                <div className="text-[#202124] w-fit max-w-[90%] pb-2">
                  <div className="prose max-w-none text-[#1A1A18] leading-[1.6] prose-p:my-1.5 prose-headings:mt-4 prose-headings:mb-2 prose-headings:font-bold prose-headings:text-black prose-strong:font-extrabold prose-strong:text-black prose-strong:tracking-tight prose-hr:my-3 prose-ul:my-1.5 prose-ol:my-1.5 prose-li:my-0.5 prose-code:bg-gray-100 prose-code:text-[#D97757] prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded-md prose-code:before:content-none prose-code:after:content-none prose-pre:bg-[#1E1E1E] prose-pre:text-gray-100 prose-pre:rounded-xl text-[16px] tracking-normal [&_pre_code]:bg-transparent [&_pre_code]:text-gray-100 [&_pre_code]:p-0">
                    <ReactMarkdown
                      components={{
                        a: ({ href, children, ...props }) => (
                          <a href={href} target="_blank" rel="noopener noreferrer" {...props}>{children}</a>
                        ),
                      }}
                    >{processedStreamingContent}</ReactMarkdown>
                    <span className="inline-block w-0.5 h-[1em] bg-[#D97757] animate-pulse ml-1 align-middle" />
                  </div>
                </div>
              </div>
            )}

            {/* 等待 AI 响应的 typing 动画 */}
            {isStreaming && !streamingContent && (
              <div className="flex flex-col gap-2 max-w-[85%] mt-6">
                <div className="bg-[#F8F9FA] rounded-2xl rounded-tl-sm px-5 py-4 shadow-sm">
                  <div className="flex gap-1 items-center h-5">
                    <span className="w-2 h-2 rounded-full bg-[#9AA0A6] animate-bounce [animation-delay:0ms]" />
                    <span className="w-2 h-2 rounded-full bg-[#9AA0A6] animate-bounce [animation-delay:150ms]" />
                    <span className="w-2 h-2 rounded-full bg-[#9AA0A6] animate-bounce [animation-delay:300ms]" />
                  </div>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* 底部固定区域（提示横幅 + 输入框） */}
        <div className="flex-shrink-0 flex flex-col items-center">
          {/* 无材料提示横幅 */}
          {!hasMaterials && (
            <div className="flex justify-center w-full bg-transparent">
              <div className="w-full max-w-3xl mx-8 mb-2 bg-[#FFF7ED] border border-[#F97316] text-[#F97316] text-sm rounded-xl px-4 py-2.5 flex items-center gap-2">
                <span>⚠️</span>
                <span>添加学习材料后，AI 将基于你的材料回答</span>
              </div>
            </div>
          )}

          {/* 输入框 */}
          <ChatInput
            onSend={sendMessage}
            disabled={isStreaming}
            onCancel={isStreaming ? cancel : undefined}
          />
        </div>
      </div>
    </div>
  )
}
