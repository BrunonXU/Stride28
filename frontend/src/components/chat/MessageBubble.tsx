import React, { useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import { SourceCitation } from './SourceCitation'
import { InlineSearchResults } from './InlineSearchResults'
import { TypingIndicator } from '../ui/Spinner'
import type { ChatMessage, InlineSearchResult } from '../../types'

/**
 * 将 AI 回复中的 [1] [2] 引用标注替换为可点击链接。
 * 只在有 searchResults 时生效。
 */
function injectCitationLinks(content: string, results: InlineSearchResult[]): string {
  if (!results.length) return content
  // 匹配 [1] [2] 等引用标注，替换为 markdown 链接
  return content.replace(/\[(\d+)\]/g, (match, numStr) => {
    const idx = parseInt(numStr, 10) - 1 // [1] → index 0
    if (idx >= 0 && idx < results.length) {
      const r = results[idx]
      return `[\\[${numStr}\\]](${r.url} "${r.title}")`
    }
    return match
  })
}

interface MessageBubbleProps {
  message: ChatMessage
  isStreaming?: boolean
  planId?: string
}

export const MessageBubble: React.FC<MessageBubbleProps> = ({ message, isStreaming, planId }) => {
  const isUser = message.role === 'user'

  // 有搜索结果时，把 [1][2] 替换为可点击链接
  const processedContent = useMemo(() => {
    if (isUser || !message.searchResults?.length) return message.content
    return injectCitationLinks(message.content, message.searchResults)
  }, [message.content, message.searchResults, isUser])

  if (isUser) {
    return (
      <div className="flex justify-end mt-2 mb-4">
        <div className="bg-[#F1F3F4] text-[#202124] rounded-2xl rounded-tr-sm px-5 py-3.5 max-w-[75%] shadow-sm border border-[#E5E5E5]/50">
          {message.attachedMaterialIds && message.attachedMaterialIds.length > 0 && (
            <div className="flex flex-wrap gap-1 mb-2">
              {message.attachedMaterialIds.map(id => (
                <span key={id} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-[#F2DFD3]/80 text-[#D97757] text-[11px] font-medium">
                  📎 {id.slice(0, 8)}…
                </span>
              ))}
            </div>
          )}
          <p className="text-[15px] leading-relaxed whitespace-pre-wrap font-medium">{message.content}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2 max-w-[95%] mb-6">
      {/* 历史消息中的搜索结果卡片 */}
      {message.searchResults && message.searchResults.length > 0 && planId && (
        <InlineSearchResults results={message.searchResults} planId={planId} defaultExpanded={false} />
      )}
      <div className="text-[#202124] w-fit max-w-[90%] pb-2">
        {isStreaming && !message.content ? (
          <TypingIndicator />
        ) : (
          <div className="prose max-w-none text-[#1A1A18] leading-[1.6] prose-p:my-1.5 prose-headings:mt-4 prose-headings:mb-2 prose-headings:font-bold prose-headings:text-black prose-strong:font-extrabold prose-strong:text-black prose-strong:tracking-tight prose-hr:my-3 prose-ul:my-1.5 prose-ol:my-1.5 prose-li:my-0.5 prose-code:bg-gray-100 prose-code:text-[#D97757] prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded-md prose-code:before:content-none prose-code:after:content-none prose-pre:bg-[#1E1E1E] prose-pre:text-gray-100 prose-pre:rounded-xl text-[16px] tracking-normal [&_pre_code]:bg-transparent [&_pre_code]:text-gray-100 [&_pre_code]:p-0">
            <ReactMarkdown
              components={{
                a: ({ href, children, ...props }) => (
                  <a href={href} target="_blank" rel="noopener noreferrer" {...props}>{children}</a>
                ),
              }}
            >{processedContent}</ReactMarkdown>
            {isStreaming && (
              <span className="inline-block w-0.5 h-[1em] bg-[#D97757] animate-pulse ml-1 align-middle" />
            )}
          </div>
        )}
      </div>
      {message.sources && message.sources.length > 0 && !isStreaming && (
        <SourceCitation sources={message.sources} />
      )}
    </div>
  )
}
