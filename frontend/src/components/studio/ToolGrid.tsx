import React from 'react'
import { ToolCard } from './ToolCard'
import type { StudioTool } from '../../types'

interface ToolGridProps {
  tools: StudioTool[]
  onToolClick: (tool: StudioTool) => void
  loadingTool?: string
}

export const ToolGrid: React.FC<ToolGridProps> = ({ tools, onToolClick, loadingTool }) => (
  <div className="grid grid-cols-2 gap-2">
    {tools.map(tool => (
      <ToolCard
        key={tool.type}
        tool={tool}
        onClick={() => onToolClick(tool)}
        isLoading={loadingTool === tool.type}
      />
    ))}
  </div>
)
