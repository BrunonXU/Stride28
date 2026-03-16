import type { Config } from 'tailwindcss'
import typography from '@tailwindcss/typography'

const config: Config = {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: '#FFFFFF',
          secondary: '#F8F9FA',
          tertiary: '#F1F3F4',
        },
        primary: {
          DEFAULT: '#1A73E8',
          hover: '#1557B0',
          light: '#E8F0FE',
        },
        accent: {
          DEFAULT: '#F97316',
          light: '#FFF7ED',
        },
        text: {
          primary: '#202124',
          secondary: '#5F6368',
          disabled: '#9AA0A6',
        },
        border: {
          DEFAULT: '#DADCE0',
          focus: '#1A73E8',
        },
        dark: {
          bg: '#1C1C1E',
          surface: '#2C2C2E',
          text: '#F5F5F7',
          border: '#3A3A3C',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
      // Removed custom fontSize to use Tailwind defaults (which are larger and more readable)
      boxShadow: {
        'soft': '0 4px 24px -4px rgba(0, 0, 0, 0.05), 0 2px 8px -2px rgba(0, 0, 0, 0.02)',
      },
      borderRadius: {
        lg: '8px',
        xl: '12px',
        '2xl': '16px',
        '3xl': '24px', // Added for the NotebookLM look
      },
      transitionDuration: {
        DEFAULT: '150ms',
      },
      keyframes: {
        'fade-in': {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        'scale-in': {
          from: { opacity: '0', transform: 'scale(0.95)' },
          to: { opacity: '1', transform: 'scale(1)' },
        },
      },
      animation: {
        'fade-in': 'fade-in 150ms ease-out',
        'scale-in': 'scale-in 150ms ease-out',
      },
    },
  },
  plugins: [typography],
}

export default config
