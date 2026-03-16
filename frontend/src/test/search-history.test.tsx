/**
 * 单元测试：搜索历史状态转换
 *
 * 1. Searching → Done 状态转换 (store updateEntry)
 * 2. Searching → Error 状态转换 (store updateEntry)
 * 3. SearchHistoryCard 搜索中状态：加载动画渲染、展开操作禁用
 *
 * 需求: 4.2, 4.3, 4.4, 4.5
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { useSearchStore } from '../store/searchStore'
import { SearchHistoryCard } from '../components/source-panel/SearchHistoryCard'
import type { SearchHistoryEntry, SearchResult } from '../types'

/* ── helpers ─────────────────────────────────────────────────── */

function makeSearchingEntry(id = 'entry-1', query = '机器学习入门'): SearchHistoryEntry {
  return {
    id,
    query,
    platforms: ['bilibili', 'youtube'],
    results: [],
    resultCount: 0,
    searchedAt: new Date().toISOString(),
    status: 'searching',
  }
}

function makeDoneEntry(id = 'entry-1', query = '机器学习入门'): SearchHistoryEntry {
  return {
    id,
    query,
    platforms: ['bilibili', 'youtube'],
    results: [
      {
        id: 'r1',
        title: 'ML Tutorial',
        url: 'https://example.com/ml',
        platform: 'youtube',
        description: 'A great tutorial',
        qualityScore: 0.85,
      },
    ],
    resultCount: 1,
    searchedAt: new Date().toISOString(),
    status: 'done',
  }
}

function makeErrorEntry(id = 'entry-1', query = '机器学习入门'): SearchHistoryEntry {
  return {
    id,
    query,
    platforms: ['bilibili', 'youtube'],
    results: [],
    resultCount: 0,
    searchedAt: new Date().toISOString(),
    status: 'error',
  }
}

/* ── store state transitions ─────────────────────────────────── */

describe('搜索历史状态转换 — store updateEntry', () => {
  beforeEach(() => {
    useSearchStore.setState({
      history: [],
      resultDetailMap: {},
      loading: false,
      activeSearch: null,
    })
  })

  it('searching → done: updateEntry updates status and results', () => {
    // Start with a searching entry
    const searchingEntry = makeSearchingEntry('s1')
    useSearchStore.setState({ history: [searchingEntry] })

    // Simulate SSE done event: update entry with results
    const doneResults: SearchResult[] = [
      {
        id: 'r1',
        title: 'ML Tutorial',
        url: 'https://example.com/ml',
        platform: 'youtube',
        description: 'A great tutorial',
        qualityScore: 0.85,
      },
      {
        id: 'r2',
        title: 'Deep Learning Basics',
        url: 'https://example.com/dl',
        platform: 'bilibili',
        description: 'Intro to DL',
        qualityScore: 0.78,
      },
    ]

    useSearchStore.getState().updateEntry('s1', {
      status: 'done',
      results: doneResults,
      resultCount: doneResults.length,
    })

    const updated = useSearchStore.getState().history.find(e => e.id === 's1')
    expect(updated).toBeDefined()
    expect(updated!.status).toBe('done')
    expect(updated!.results).toHaveLength(2)
    expect(updated!.resultCount).toBe(2)
    expect(updated!.results[0].title).toBe('ML Tutorial')
    // resultDetailMap should also be updated
    expect(useSearchStore.getState().resultDetailMap['r1']).toBeDefined()
    expect(useSearchStore.getState().resultDetailMap['r2']).toBeDefined()
  })

  it('searching → error: updateEntry updates status to error', () => {
    const searchingEntry = makeSearchingEntry('s2')
    useSearchStore.setState({ history: [searchingEntry] })

    // Simulate SSE error event
    useSearchStore.getState().updateEntry('s2', {
      status: 'error',
    })

    const updated = useSearchStore.getState().history.find(e => e.id === 's2')
    expect(updated).toBeDefined()
    expect(updated!.status).toBe('error')
    expect(updated!.results).toHaveLength(0)
    expect(updated!.resultCount).toBe(0)
  })

  it('updateEntry preserves other fields when patching status', () => {
    const searchingEntry = makeSearchingEntry('s3', '深度学习')
    useSearchStore.setState({ history: [searchingEntry] })

    useSearchStore.getState().updateEntry('s3', { status: 'done' })

    const updated = useSearchStore.getState().history.find(e => e.id === 's3')
    expect(updated!.query).toBe('深度学习')
    expect(updated!.platforms).toEqual(['bilibili', 'youtube'])
  })

  it('updateEntry with non-existent id does not modify history', () => {
    const entry = makeSearchingEntry('s4')
    useSearchStore.setState({ history: [entry] })

    useSearchStore.getState().updateEntry('non-existent', { status: 'done' })

    const state = useSearchStore.getState()
    expect(state.history).toHaveLength(1)
    expect(state.history[0].status).toBe('searching')
  })
})

/* ── SearchHistoryCard searching state ───────────────────────── */

describe('SearchHistoryCard — 搜索中状态', () => {
  it('renders loading animation (bouncing dots) when status is searching', () => {
    const entry = makeSearchingEntry()
    render(
      <SearchHistoryCard
        entry={entry}
        isExpanded={false}
        onToggle={() => {}}
      />
    )

    // Should show "搜索中..." text
    expect(screen.getByText('搜索中...')).toBeInTheDocument()

    // Should show the query keyword
    expect(screen.getByText('机器学习入门')).toBeInTheDocument()

    // Should render bouncing dots (3 animated spans)
    const container = document.querySelector('.animate-bounce')
    expect(container).toBeInTheDocument()
  })

  it('disables expand operation when status is searching', () => {
    const onToggle = vi.fn()
    const entry = makeSearchingEntry()

    const { container } = render(
      <SearchHistoryCard
        entry={entry}
        isExpanded={false}
        onToggle={onToggle}
      />
    )

    // The searching state renders a div, not a button — no clickable toggle
    const button = container.querySelector('button')
    expect(button).toBeNull()

    // onToggle should not be callable from the searching state UI
    // Try clicking the container div
    const wrapper = container.firstElementChild as HTMLElement
    fireEvent.click(wrapper)
    expect(onToggle).not.toHaveBeenCalled()
  })

  it('does not render expanded content even if isExpanded is true', () => {
    const entry = makeSearchingEntry()
    const { container } = render(
      <SearchHistoryCard
        entry={entry}
        isExpanded={true}
        onToggle={() => {}}
      />
    )

    // Should not render any checkbox or result items
    expect(container.querySelector('input[type="checkbox"]')).toBeNull()
    // Should still show searching state
    expect(screen.getByText('搜索中...')).toBeInTheDocument()
  })
})

/* ── SearchHistoryCard error state ───────────────────────────── */

describe('SearchHistoryCard — 错误状态', () => {
  it('renders "搜索失败" when status is error', () => {
    const entry = makeErrorEntry()
    render(
      <SearchHistoryCard
        entry={entry}
        isExpanded={false}
        onToggle={() => {}}
      />
    )

    expect(screen.getByText('搜索失败')).toBeInTheDocument()
    expect(screen.getByText('机器学习入门')).toBeInTheDocument()
  })
})

/* ── SearchHistoryCard done state ────────────────────────────── */

describe('SearchHistoryCard — 完成状态', () => {
  it('renders result count and platform display when status is done', () => {
    const entry = makeDoneEntry()
    const { container } = render(
      <SearchHistoryCard
        entry={entry}
        isExpanded={false}
        onToggle={() => {}}
      />
    )

    expect(screen.getByText('机器学习入门')).toBeInTheDocument()
    // Should show result count
    expect(container.textContent).toContain('1')
  })
})
