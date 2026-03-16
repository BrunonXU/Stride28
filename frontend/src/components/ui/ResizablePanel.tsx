import React, { useRef, useCallback } from 'react'

interface ResizablePanelGroupProps {
  children: React.ReactNode
  className?: string
}

interface ResizablePanelProps {
  children: React.ReactNode
  defaultWidth: number   // 百分比
  minWidth: number       // 百分比
  className?: string
}

// 三列可拖拽布局容器
export const ResizablePanelGroup: React.FC<ResizablePanelGroupProps> = ({ children, className = '' }) => (
  <div className={`flex h-full overflow-hidden ${className}`}>{children}</div>
)

export const ResizablePanel: React.FC<ResizablePanelProps> = ({
  children,
  defaultWidth,
  minWidth,
  className = '',
}) => {
  return (
    <div
      className={`flex flex-col overflow-hidden ${className}`}
      style={{ width: `${defaultWidth}%`, minWidth: `${minWidth}%` }}
    >
      {children}
    </div>
  )
}

// 拖拽分割线
interface DividerProps {
  onDrag: (delta: number) => void
}

export const ResizeDivider: React.FC<DividerProps> = ({ onDrag }) => {
  const isDragging = useRef(false)
  const lastX = useRef(0)

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    isDragging.current = true
    lastX.current = e.clientX
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'

    const onMouseMove = (e: MouseEvent) => {
      if (!isDragging.current) return
      const delta = e.clientX - lastX.current
      lastX.current = e.clientX
      onDrag(delta)
    }

    const onMouseUp = () => {
      isDragging.current = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
    }

    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
  }, [onDrag])

  return (
    <div
      className="w-px bg-border hover:bg-primary cursor-col-resize flex-shrink-0 transition-colors duration-50"
      onMouseDown={onMouseDown}
      role="separator"
      aria-orientation="vertical"
    />
  )
}
