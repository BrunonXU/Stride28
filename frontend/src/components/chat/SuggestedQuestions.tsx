import React, { useState } from 'react'

interface SuggestedQuestionsProps {
  questions: string[]
  onSelect: (q: string) => void
}

export const SuggestedQuestions: React.FC<SuggestedQuestionsProps> = ({ questions, onSelect }) => {
  const [collapsed, setCollapsed] = useState(false)

  if (questions.length === 0) return null

  return (
    <div className="border-b border-border dark:border-dark-border flex-shrink-0">
      <button
        onClick={() => setCollapsed(c => !c)}
        className="w-full flex items-center justify-between px-6 py-2 text-xs text-text-secondary hover:bg-surface-tertiary transition-colors duration-50"
        aria-expanded={!collapsed}
      >
        <span className="font-medium uppercase tracking-wide">建议问题</span>
        <span>{collapsed ? '▼' : '▲'}</span>
      </button>
      {!collapsed && (
        <div className="flex flex-wrap gap-2 px-6 pb-3">
          {questions.map((q, i) => (
            <button
              key={i}
              onClick={() => onSelect(q)}
              className="rounded-full border border-border text-sm px-3 py-1 text-text-secondary hover:bg-surface-tertiary hover:border-primary hover:text-primary transition-all duration-50"
            >
              {q}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
