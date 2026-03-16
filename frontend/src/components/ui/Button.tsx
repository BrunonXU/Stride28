import React from 'react'

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost'
  size?: 'sm' | 'md'
  loading?: boolean
}

export const Button: React.FC<ButtonProps> = ({
  variant = 'primary',
  size = 'md',
  loading = false,
  disabled,
  children,
  className = '',
  ...props
}) => {
  const base = 'inline-flex items-center justify-center rounded-lg font-medium transition-all duration-50 ease-in-out active:scale-95 focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 outline-none'

  const variants = {
    primary: 'bg-primary text-white hover:bg-primary-hover disabled:opacity-50 disabled:cursor-not-allowed',
    secondary: 'bg-surface border border-border text-text-primary hover:bg-surface-tertiary disabled:opacity-50 disabled:cursor-not-allowed',
    ghost: 'text-text-secondary hover:bg-surface-tertiary disabled:opacity-50 disabled:cursor-not-allowed',
  }

  const sizes = {
    sm: 'px-3 py-1.5 text-sm',
    md: 'px-4 py-2 text-base',
  }

  return (
    <button
      className={`${base} ${variants[variant]} ${sizes[size]} ${className}`}
      disabled={disabled || loading}
      {...props}
    >
      {loading && (
        <svg className="animate-spin -ml-1 mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      )}
      {children}
    </button>
  )
}
