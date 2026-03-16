import React from 'react'

interface BadgeProps {
  children: React.ReactNode
  variant?: 'default' | 'accent' | 'success' | 'error'
  className?: string
}

export const Badge: React.FC<BadgeProps> = ({ children, variant = 'default', className = '' }) => {
  const variants = {
    default: 'bg-primary-light text-primary',
    accent: 'bg-accent-light text-accent',
    success: 'bg-green-100 text-green-700',
    error: 'bg-red-100 text-red-600',
  }

  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${variants[variant]} ${className}`}>
      {children}
    </span>
  )
}
