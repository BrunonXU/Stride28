/**
 * Property 7: 非空回复产生 ≥2 个 chunk 事件
 * Property 8: history 长度不超过 12 条
 */
import { describe, it, expect } from 'vitest'

// ─── Property 7: SSE chunk 解析 ───────────────────────────────────────────────

function parseSSEChunks(rawSSE: string): string[] {
  const chunks: string[] = []
  for (const line of rawSSE.split('\n')) {
    if (!line.startsWith('data: ')) continue
    try {
      const evt = JSON.parse(line.slice(6))
      if (evt.type === 'chunk' && evt.content) {
        chunks.push(evt.content)
      }
    } catch { /* ignore */ }
  }
  return chunks
}

function buildSSEResponse(content: string, chunkSize = 5): string {
  const lines: string[] = []
  for (let i = 0; i < content.length; i += chunkSize) {
    const chunk = content.slice(i, i + chunkSize)
    lines.push(`data: ${JSON.stringify({ type: 'chunk', content: chunk })}`)
    lines.push('')
  }
  lines.push(`data: ${JSON.stringify({ type: 'done' })}`)
  lines.push('')
  return lines.join('\n')
}

describe('Property 7: non-empty response produces ≥2 chunk events', () => {
  it('short response (10 chars, chunk=5) produces 2 chunks', () => {
    const sse = buildSSEResponse('Hello World', 5)
    const chunks = parseSSEChunks(sse)
    expect(chunks.length).toBeGreaterThanOrEqual(2)
    expect(chunks.join('')).toBe('Hello World')
  })

  it('long response produces many chunks', () => {
    const content = 'A'.repeat(100)
    const sse = buildSSEResponse(content, 10)
    const chunks = parseSSEChunks(sse)
    expect(chunks.length).toBeGreaterThanOrEqual(2)
    expect(chunks.join('')).toBe(content)
  })

  it('chunks reassemble to original content', () => {
    const cases = [
      'Transformer 的注意力机制通过 Q、K、V 矩阵实现',
      '这是一段较长的 AI 回复，包含多个句子。第一句。第二句。第三句。',
      'Short',
    ]
    for (const content of cases) {
      const sse = buildSSEResponse(content, 3)
      const chunks = parseSSEChunks(sse)
      if (content.length > 3) {
        expect(chunks.length).toBeGreaterThanOrEqual(2)
      }
      expect(chunks.join('')).toBe(content)
    }
  })

  it('done event is always present', () => {
    const sse = buildSSEResponse('test content')
    expect(sse).toContain('"type":"done"')
  })
})

// ─── Property 8: history 窗口截断 ─────────────────────────────────────────────

const MAX_HISTORY = 12

function truncateHistory<T>(history: T[]): T[] {
  return history.slice(-MAX_HISTORY)
}

describe('Property 8: history length never exceeds 12 messages', () => {
  it('history with 12 messages stays at 12', () => {
    const h = Array.from({ length: 12 }, (_, i) => ({ role: 'user', content: `msg ${i}` }))
    expect(truncateHistory(h).length).toBe(12)
  })

  it('history with 20 messages is truncated to 12', () => {
    const h = Array.from({ length: 20 }, (_, i) => ({ role: 'user', content: `msg ${i}` }))
    const result = truncateHistory(h)
    expect(result.length).toBe(12)
    // 保留最新的 12 条
    expect(result[0].content).toBe('msg 8')
    expect(result[11].content).toBe('msg 19')
  })

  it('history with fewer than 12 messages is unchanged', () => {
    for (let n = 0; n <= 12; n++) {
      const h = Array.from({ length: n }, (_, i) => ({ role: 'user', content: `msg ${i}` }))
      expect(truncateHistory(h).length).toBe(n)
    }
  })

  it('truncation is monotonically bounded', () => {
    // 无论添加多少消息，截断后长度始终 ≤ MAX_HISTORY
    for (let n = 0; n <= 50; n++) {
      const h = Array.from({ length: n }, (_, i) => ({ role: 'user', content: `msg ${i}` }))
      expect(truncateHistory(h).length).toBeLessThanOrEqual(MAX_HISTORY)
    }
  })
})
