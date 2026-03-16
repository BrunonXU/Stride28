import React, { useState } from 'react'
import { Modal } from '../ui/Modal'
import type { CitationSource } from '../../types'

interface SourceCitationProps {
  sources: CitationSource[]
}

export const SourceCitation: React.FC<SourceCitationProps> = ({ sources }) => {
  const [activeSource, setActiveSource] = useState<CitationSource | null>(null)

  return (
    <>
      <div className="flex flex-wrap gap-1.5">
        {sources.map((s, i) => (
          <button
            key={i}
            onClick={() => setActiveSource(s)}
            className="inline-flex items-center gap-1 bg-primary-light text-primary text-xs rounded-full px-2 py-0.5 cursor-pointer hover:bg-primary hover:text-white transition-colors duration-50"
            aria-label={`查看来源：${s.materialName}`}
          >
            📎 {s.materialName}
          </button>
        ))}
      </div>

      <Modal
        open={!!activeSource}
        onClose={() => setActiveSource(null)}
        title={activeSource?.materialName}
        width="max-w-md"
      >
        <p className="text-sm text-text-secondary leading-relaxed whitespace-pre-wrap">
          {activeSource?.snippet}
        </p>
      </Modal>
    </>
  )
}
