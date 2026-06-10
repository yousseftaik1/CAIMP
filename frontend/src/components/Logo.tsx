// CAIMP Logo — network/ECG icon (SVG) + wordmark (HTML)
// Splitting icon and text gives reliable font rendering at every size.
export default function Logo({ variant = 'dark', size = 'md' }: {
  variant?: 'dark' | 'light'
  size?: 'sm' | 'md' | 'lg'
}) {
  const iconPx  = { sm: 26,  md: 34,  lg: 48  }[size]
  const namePx  = { sm: 14,  md: 18,  lg: 26  }[size]
  const subPx   = { sm: 7.5, md: 8.5, lg: 10.5 }[size]
  const gap     = { sm: 8,   md: 10,  lg: 14  }[size]

  const navy = variant === 'light' ? '#ffffff' : '#1a3d5c'
  const teal = variant === 'light' ? 'rgba(255,255,255,0.85)' : '#2ea99f'
  const sub  = variant === 'light' ? 'rgba(255,255,255,0.55)' : '#6b8cae'

  return (
    <div style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap,
      userSelect: 'none',
      flexShrink: 0,
    }}>
      {/* ── Icon: network nodes + ECG heartbeat ── */}
      <svg
        width={iconPx}
        height={iconPx}
        viewBox="0 0 36 36"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        style={{ flexShrink: 0 }}
      >
        {/* Connection lines */}
        <line x1="6"  y1="10" x2="18" y2="18" stroke={navy} strokeWidth="1.6" strokeLinecap="round"/>
        <line x1="6"  y1="26" x2="18" y2="18" stroke={navy} strokeWidth="1.6" strokeLinecap="round"/>
        <line x1="12" y1="18" x2="18" y2="18" stroke={navy} strokeWidth="1.6" strokeLinecap="round"/>
        {/* Peripheral nodes */}
        <circle cx="6"  cy="10" r="2.8" fill={teal}/>
        <circle cx="6"  cy="26" r="2.3" fill={navy}/>
        <circle cx="12" cy="18" r="2.0" fill={navy}/>
        {/* Central hub */}
        <circle cx="18" cy="18" r="3.4" fill={navy}/>
        {/* ECG line */}
        <polyline
          points="18,18 22,18 25,10 28.5,26 31.5,18 36,18"
          stroke={navy}
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
          fill="none"
        />
      </svg>

      {/* ── Text: CAIMP + subtitle ── */}
      <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1 }}>
        <span style={{
          fontFamily: "'Syne', 'Helvetica Neue', Arial, sans-serif",
          fontSize: namePx,
          fontWeight: 800,
          color: navy,
          letterSpacing: '0.12em',
          lineHeight: 1.1,
        }}>
          CAIMP
        </span>
        <span style={{
          fontSize: subPx,
          fontWeight: 500,
          color: sub,
          letterSpacing: '0.16em',
          textTransform: 'uppercase',
          lineHeight: 1.2,
          marginTop: 2,
        }}>
          Infrastructure Monitor
        </span>
      </div>
    </div>
  )
}
