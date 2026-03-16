// Feature: search-strategy-optimization, Property 8: 搜索进行中历史始终可见
// **Validates: Requirements 4.1**

import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import * as fc from 'fast-check'
import { useSearchStore } from '../store/searchStore'
import { SearchPanel } from '../components/source-panel/SearchPanel'
import type { SearchStage, SearchHistoryEntry } from '../types'

/** Active search stages where search is "in progress" */
const ACTIVE_STAGES: SearchStage[] = ['searching', 'filtering', 'extracting', 'evaluating']

/** Generator for active search stages */
const activeStageArb = fc.constantFrom(...ACTIVE_STAGES)

/** A minimal history entry for testing */
function makeHistoryEntry(id: string, query: string): SearchHistoryEntry {
  return {
    id,
    query,
    platforms: ['bilibili'],
    results: [],
    resultCount: 0,
    searchedAt: new Date().toISOString(),
    status: 'done',
  }
}

describe('Property 8: 搜索进行中历史始终可见', () => {
  beforeEach(() => {
    // Reset store before each test
    useSearchStore.setState({
      history: [],
      activeSearch: null,
      resultDetailMap: {},
      loading: false,
    })
  })

  it('search history section is visible during any active search stage', () => {
    fc.assert(
      fc.property(activeStageArb, (stage: SearchStage) => {
        // Set up store with history entries and an active search at the given stage
        useSearchStore.setState({
          history: [
            makeHistoryEntry('h1', '测试搜索1'),
            makeHistoryEntry('h2', '测试搜索2'),
          ],
          activeSearch: {
            query: '当前搜索',
            platforms: ['bilibili', 'youtube'],
            stage,
            stageMessage: '搜索中...',
            results: [],
            error: '',
            abortController: null,
          },
        })

        const { unmount } = render(
          <SearchPanel planId="test-plan" onAddToMaterials={() => {}} />
        )

        // The "搜索历史" heading must be visible regardless of search stage
        const historyHeading = screen.getByText('搜索历史')
        expect(historyHeading).toBeInTheDocument()

        // History entries should also be rendered
        expect(screen.getByText('测试搜索1')).toBeInTheDocument()
        expect(screen.getByText('测试搜索2')).toBeInTheDocument()

        unmount()
      }),
      { numRuns: 100 }
    )
  })
})
