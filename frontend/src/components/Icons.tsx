import type { CSSProperties } from 'react'

interface IconProps {
  size?: number
  color?: string
  style?: CSSProperties
  className?: string
  title?: string
}

const base = (size: number, extra?: CSSProperties): CSSProperties => ({
  width: size, height: size, display: 'inline-block', flexShrink: 0,
  verticalAlign: 'middle', ...extra,
})

export function Spinner({ size = 16, color = 'currentColor', style, className }: IconProps) {
  return (
    <svg style={{ ...base(size), animation: 'spin 0.8s linear infinite', ...style }}
      className={className} viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth={2.5} strokeLinecap="round">
      <path d="M12 2a10 10 0 0 1 10 10" opacity={0.3} />
      <path d="M12 2a10 10 0 0 1 10 10" />
    </svg>
  )
}

export function Check({ size = 16, color = 'currentColor', style, className }: IconProps) {
  return (
    <svg style={{ ...base(size), ...style }} className={className}
      viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  )
}

export function AlertTriangle({ size = 16, color = 'currentColor', style, className, title }: IconProps) {
  return (
    <svg style={{ ...base(size), ...style }} className={className}
      viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      {title && <title>{title}</title>}
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  )
}

export function Close({ size = 16, color = 'currentColor', style, className }: IconProps) {
  return (
    <svg style={{ ...base(size), ...style }} className={className}
      viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2.5} strokeLinecap="round">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  )
}

export function ChevronUp({ size = 16, color = 'currentColor', style, className }: IconProps) {
  return (
    <svg style={{ ...base(size), ...style }} className={className}
      viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
      <polyline points="18 15 12 9 6 15" />
    </svg>
  )
}

export function ChevronDown({ size = 16, color = 'currentColor', style, className }: IconProps) {
  return (
    <svg style={{ ...base(size), ...style }} className={className}
      viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
      <polyline points="6 9 12 15 18 9" />
    </svg>
  )
}

export function ChevronRight({ size = 14, color = 'currentColor', style, className }: IconProps) {
  return (
    <svg style={{ ...base(size), ...style }} className={className}
      viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
      <polyline points="9 18 15 12 9 6" />
    </svg>
  )
}

export function ArrowUp({ size = 16, color = 'currentColor', style, className }: IconProps) {
  return (
    <svg style={{ ...base(size), ...style }} className={className}
      viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="19" x2="12" y2="5" />
      <polyline points="5 12 12 5 19 12" />
    </svg>
  )
}

export function ArrowDown({ size = 16, color = 'currentColor', style, className }: IconProps) {
  return (
    <svg style={{ ...base(size), ...style }} className={className}
      viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="5" x2="12" y2="19" />
      <polyline points="19 12 12 19 5 12" />
    </svg>
  )
}

export function ArrowRight({ size = 14, color = 'currentColor', style, className }: IconProps) {
  return (
    <svg style={{ ...base(size), ...style }} className={className}
      viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
      <line x1="5" y1="12" x2="19" y2="12" />
      <polyline points="12 5 19 12 12 19" />
    </svg>
  )
}

export function ArrowLeft({ size = 14, color = 'currentColor', style, className }: IconProps) {
  return (
    <svg style={{ ...base(size), ...style }} className={className}
      viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
      <line x1="19" y1="12" x2="5" y2="12" />
      <polyline points="12 19 5 12 12 5" />
    </svg>
  )
}

export function TrendingUp({ size = 16, color = 'currentColor', style, className }: IconProps) {
  return (
    <svg style={{ ...base(size), ...style }} className={className}
      viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 6 13.5 15.5 8.5 10.5 1 18" />
      <polyline points="17 6 23 6 23 12" />
    </svg>
  )
}

export function TrendingDown({ size = 16, color = 'currentColor', style, className }: IconProps) {
  return (
    <svg style={{ ...base(size), ...style }} className={className}
      viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 18 13.5 8.5 8.5 13.5 1 6" />
      <polyline points="17 18 23 18 23 12" />
    </svg>
  )
}

export function Minus({ size = 16, color = 'currentColor', style, className }: IconProps) {
  return (
    <svg style={{ ...base(size), ...style }} className={className}
      viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2.5} strokeLinecap="round">
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  )
}

export function Download({ size = 14, color = 'currentColor', style, className }: IconProps) {
  return (
    <svg style={{ ...base(size), ...style }} className={className}
      viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  )
}

export function RefreshCw({ size = 16, color = 'currentColor', style, className }: IconProps) {
  return (
    <svg style={{ ...base(size), ...style }} className={className}
      viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 4 23 10 17 10" />
      <polyline points="1 20 1 14 7 14" />
      <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
    </svg>
  )
}

export function FileText({ size = 32, color = 'currentColor', style, className }: IconProps) {
  return (
    <svg style={{ ...base(size), ...style }} className={className}
      viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
      <polyline points="10 9 9 9 8 9" />
    </svg>
  )
}

export function BarChart({ size = 40, color = 'currentColor', style, className }: IconProps) {
  return (
    <svg style={{ ...base(size), ...style }} className={className}
      viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="20" x2="18" y2="10" />
      <line x1="12" y1="20" x2="12" y2="4" />
      <line x1="6" y1="20" x2="6" y2="14" />
    </svg>
  )
}

export function Bot({ size = 16, color = 'currentColor', style, className }: IconProps) {
  return (
    <svg style={{ ...base(size), ...style }} className={className}
      viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="11" width="18" height="10" rx="2" />
      <circle cx="12" cy="5" r="2" />
      <path d="M12 7v4" />
      <line x1="8" y1="16" x2="8" y2="16" strokeWidth={2.5} />
      <line x1="16" y1="16" x2="16" y2="16" strokeWidth={2.5} />
    </svg>
  )
}

export function ThumbsUp({ size = 16, color = 'currentColor', style, className }: IconProps) {
  return (
    <svg style={{ ...base(size), ...style }} className={className}
      viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3H14z" />
      <path d="M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3" />
    </svg>
  )
}

export function ThumbsDown({ size = 16, color = 'currentColor', style, className }: IconProps) {
  return (
    <svg style={{ ...base(size), ...style }} className={className}
      viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3H10z" />
      <path d="M17 2h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17" />
    </svg>
  )
}

export function Monitor({ size = 14, color = 'currentColor', style, className }: IconProps) {
  return (
    <svg style={{ ...base(size), ...style }} className={className}
      viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="3" width="20" height="14" rx="2" />
      <line x1="8" y1="21" x2="16" y2="21" />
      <line x1="12" y1="17" x2="12" y2="21" />
    </svg>
  )
}

export function Search({ size = 14, color = 'currentColor', style, className }: IconProps) {
  return (
    <svg style={{ ...base(size), ...style }} className={className}
      viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  )
}

export function BookOpen({ size = 14, color = 'currentColor', style, className }: IconProps) {
  return (
    <svg style={{ ...base(size), ...style }} className={className}
      viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
      <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
    </svg>
  )
}

export function MessageCircle({ size = 14, color = 'currentColor', style, className }: IconProps) {
  return (
    <svg style={{ ...base(size), ...style }} className={className}
      viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  )
}
