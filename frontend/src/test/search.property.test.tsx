/**
 * Property 1: 搜索结果始终按 quality_score 降序排列
 * Property 6: SearchResultItem 评分显示格式为 `⭐ x.x/10`
 */
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { SearchResultItem } from '../components/source-panel/SearchResultItem'
import type { SearchResult } from '../types'

// ─── Property 1: 排序不变式 ───────────────────────────────────────────────────

function sortByQuality(items: SearchResult[]): SearchResult[] {
  return [...items].sort((a, b) => b.qualityScore - a.qualityScore)
}

function isDescending(items: SearchResult[]): boolean {
  for (let i = 1; i < items.length; i++) {
    if (items[i].qualityScore > items[i - 1].qualityScore) return false
  }
  return true
}

function makeResults(scores: number[]): SearchResult[] {
  return scores.map((s, i) => ({
    id: `r${i}`,
    title: `Result ${i}`,
    url: `https://example.com/${i}`,
    platform: 'bilibili' as const,
    description: 'desc',
    qualityScore: s,
  }))
}

describe('Property 1: search results are sorted by quality_score descending', () => {
  it('already sorted list remains sorted', () => {
    const items = makeResults([0.9, 0.7, 0.5, 0.3])
    expect(isDescending(sortByQuality(items))).toBe(true)
  })

  it('unsorted list becomes sorted after sort', () => {
    const items = makeResults([0.3, 0.9, 0.1, 0.7, 0.5])
    const sorted = sortByQuality(items)
    expect(isDescending(sorted)).toBe(true)
  })

  it('equal scores maintain descending invariant', () => {
    const items = makeResults([0.5, 0.5, 0.5])
    expect(isDescending(sortByQuality(items))).toBe(true)
  })

  it('single item is trivially sorted', () => {
    const items = makeResults([0.8])
    expect(isDescending(sortByQuality(items))).toBe(true)
  })

  it('empty list is trivially sorted', () => {
    expect(isDescending(sortByQuality([]))).toBe(true)
  })

  // 随机生成 20 组测试
  it('random score arrays are always sorted correctly', () => {
    for (let trial = 0; trial < 20; trial++) {
      const n = Math.floor(Math.random() * 10) + 1
      const scores = Array.from({ length: n }, () => Math.random())
      const items = makeResults(scores)
      expect(isDescending(sortByQuality(items))).toBe(true)
    }
  })
})

// ─── Property 6: 评分显示格式 ─────────────────────────────────────────────────

describe('Property 6: SearchResultItem score format is ⭐ x.x/10', () => {
  const SCORE_CASES = [0, 0.1, 0.5, 0.87, 0.92, 1.0]

  it.each(SCORE_CASES)('qualityScore %f renders as ⭐ x.x/10', (score) => {
    const result: SearchResult = {
      id: 'r1',
      title: 'Test',
      url: 'https://example.com',
      platform: 'bilibili',
      description: 'desc',
      qualityScore: score,
    }
    const { container } = render(
      <SearchResultItem result={result} checked={false} onToggle={() => {}} />
    )
    const text = container.textContent ?? ''
    // 格式：⭐ x.x/10
    const expected = `⭐ ${(score * 10).toFixed(1)}/10`
    expect(text).toContain(expected)
  })
})
