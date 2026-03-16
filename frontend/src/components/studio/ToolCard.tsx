import React from 'react'
import { Spinner } from '../ui/Spinner'
import type { StudioTool } from '../../types'

interface ToolCardProps {
  tool: StudioTool
  onClick: () => void
  isLoading?: boolean
}

export const ToolCard: React.FC<ToolCardProps> = ({ tool, onClick, isLoading }) => (
  <button
    onClick={onClick}
    disabled={isLoading}
    className="h-20 bg-white rounded-xl border border-[#DADCE0] shadow-sm flex flex-col items-center justify-center gap-1.5
               hover:shadow-md hover:border-[#D97757] hover:-translate-y-0.5
               cursor-pointer transition-all duration-50 active:scale-95
               focus-visible:ring-2 focus-visible:ring-[#D97757] outline-none"
    aria-label={tool.label}
  >
    {isLoading ? (
      <>
        <Spinner size="sm" />
        <span className="text-xs font-medium text-[#5F6368]">生成中...</span>
      </>
    ) : (
      <>
        <span className="text-2xl" aria-hidden="true">{tool.icon}</span>
        <span className="text-sm font-medium text-[#202124]">{tool.label}</span>
      </>
    )}
  </button>
)
