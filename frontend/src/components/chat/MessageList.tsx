import React from 'react'
import { MessageBubble } from './MessageBubble'
import type { ChatMessage } from '../../types'

interface MessageListProps {
  messages: ChatMessage[]
  isStreaming?: boolean
  planId?: string
}

// 格式化时间戳：
// - 今天： "19:40"
// - 昨天： "昨天 19:40"
// - 更早： "3月4日 19:40" (如果跨年还可以加年份)
function formatTimestamp(isoString: string): string {
  const d = new Date(isoString);
  const now = new Date();

  const isSameYear = d.getFullYear() === now.getFullYear();
  const isToday = isSameYear && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();

  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const isYesterday = d.getFullYear() === yesterday.getFullYear() &&
    d.getMonth() === yesterday.getMonth() &&
    d.getDate() === yesterday.getDate();

  const hours = d.getHours().toString().padStart(2, '0');
  const minutes = d.getMinutes().toString().padStart(2, '0');
  const timeStr = `${hours}:${minutes}`;

  if (isToday) return timeStr;
  if (isYesterday) return `昨天 ${timeStr}`;

  const month = d.getMonth() + 1;
  const date = d.getDate();
  const dateStr = `${month}月${date}日 ${timeStr}`;

  if (!isSameYear) {
    return `${d.getFullYear()}年${dateStr}`;
  }
  return dateStr;
}

// 判断两条消息间隔是否超过 5 分钟 (300,000 毫秒)
function shouldShowTimestamp(iso1: string | null, iso2: string): boolean {
  if (!iso1) return true;
  const t1 = new Date(iso1).getTime();
  const t2 = new Date(iso2).getTime();
  return (t2 - t1) > 5 * 60 * 1000;
}

export const MessageList: React.FC<MessageListProps> = ({ messages, isStreaming, planId }) => {
  if (messages.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center py-16">
        <span className="text-5xl mb-4">💬</span>
        <p className="text-text-secondary text-base">向 AI 提问，开始学习之旅</p>
      </div>
    )
  }

  const renderedElements: React.ReactNode[] = [];
  let lastTimestampIso: string | null = null;

  messages.forEach((msg, i) => {
    if (shouldShowTimestamp(lastTimestampIso, msg.createdAt)) {
      renderedElements.push(
        <div key={`date-${msg.id}`} className="flex justify-center my-4">
          <span className="text-xs font-semibold text-[#B0B5BA]">{formatTimestamp(msg.createdAt)}</span>
        </div>
      );
      lastTimestampIso = msg.createdAt;
    }

    renderedElements.push(
      <MessageBubble
        key={msg.id}
        message={msg}
        isStreaming={isStreaming && i === messages.length - 1}
        planId={planId}
      />
    );
  });

  return (
    <div className="flex flex-col gap-2">
      {renderedElements}
    </div>
  )
}
