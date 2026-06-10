import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { getDashboardSummary } from '../api'
import { clearSession } from '../auth'
import { useWebSocket } from '../useWebSocket'
import Logo from '../components/Logo'
import {
  AlertTriangle, ArrowRight, Check, RefreshCw, Spinner,
} from '../components/Icons'
import type { DashboardSummary, PotentialIssue, WsEvent } from '../types'

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusBanner({ summary }: { summary: DashboardSummary }) {
  const isHealthy  = summary.overall_status === 'healthy'
  const isCritical = summary.overall_status === 'critical'

  const bg    = isCritical ? 'var(--danger)' : isHealthy ? 'var(--success)' : 'var(--warning)'
  const faint = isCritical ? '#2d0808'        : isHealthy ? '#052e16'        : '#431407'
  const icon  = isCritical ? <AlertTriangle size={28} color="#fff" />
              : isHealthy  ? <Check size={28} color="#fff" />
              : <AlertTriangle size={28} color="#fff" />

  return (
    <div style={{
      background: faint, border: `1.5px solid ${bg}`,
      borderRadius: 14, padding: '20px 28px',
      display: 'flex', alignItems: 'center', gap: 16,
      marginBottom: 28,
    }}>
      <div style={{
        width: 52, height: 52, borderRadius: '50%',
        background: bg, display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexShrink: 0,
      }}>
        {icon}
      </div>
      <div>
        <div style={{
          fontSize: 18, fontWeight: 800, color: bg,
          fontFamily: 'Syne, sans-serif', letterSpacing: '-0.01em', marginBottom: 4,
        }}>
          {isHealthy ? 'All Systems Healthy' : isCritical ? 'Action Required' : 'Potential Issues Detected'}
        </div>
        <div style={{ fontSize: 13.5, color: 'var(--text-2)', lineHeight: 1.5 }}>
          {summary.overall_message}
        </div>
      </div>
      <div style={{ marginLeft: 'auto', textAlign: 'right', flexShrink: 0 }}>
        <div style={{ fontSize: 22, fontWeight: 800, color: 'var(--text)', fontFamily: 'Syne, sans-serif' }}>
          {summary.online_count}/{summary.server_count}
        </div>
        <div style={{ fontSize: 11, color: 'var(--muted)', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
          servers online
        </div>
      </div>
    </div>
  )
}

// ── Issue row ─────────────────────────────────────────────────────────────────

function IssueRow({ issue }: { issue: PotentialIssue }) {
  const isCrit = issue.severity === 'critical'
  const isWarn = issue.severity === 'warning'
  const color  = isCrit ? 'var(--danger)' : isWarn ? 'var(--warning)' : 'var(--info)'
  const bg     = isCrit ? 'var(--event-anomaly-bg)' : isWarn ? '#fff7ed' : 'var(--bg-alt)'

  return (
    <Link to={`/servers/${issue.server_id}`} style={{ textDecoration: 'none' }}>
      <div style={{
        display: 'flex', alignItems: 'flex-start', gap: 12,
        padding: '12px 16px', borderRadius: 10, background: bg,
        border: `1px solid ${color}22`, marginBottom: 8,
        transition: 'border-color 0.15s',
        cursor: 'pointer',
      }}>
        <div style={{
          width: 8, height: 8, borderRadius: '50%', background: color,
          marginTop: 6, flexShrink: 0,
        }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 13.5, color: 'var(--text)', marginBottom: 3 }}>
            {issue.title}
          </div>
          <div style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.55 }}>
            {issue.detail}
          </div>
        </div>
        <ArrowRight size={14} color="var(--muted)" style={{ marginTop: 4, flexShrink: 0 }} />
      </div>
    </Link>
  )
}

// ── Server mini-grid ──────────────────────────────────────────────────────────

function ServerMini({ srv }: { srv: DashboardSummary['servers'][0] }) {
  const isOk  = srv.status === 'online'
  const isBad = srv.status === 'offline'
  const dot   = isBad ? 'var(--danger)' : isOk ? 'var(--success)' : 'var(--warning)'

  function bar(pct: number | null) {
    if (pct == null) return null
    const c = pct >= 90 ? 'var(--danger)' : pct >= 75 ? 'var(--warning)' : 'var(--success)'
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
        <div style={{ flex: 1, height: 4, background: 'var(--border)', borderRadius: 2 }}>
          <div style={{ width: `${Math.min(pct, 100)}%`, height: '100%', background: c, borderRadius: 2 }} />
        </div>
        <span style={{ fontSize: 10, fontFamily: 'JetBrains Mono, monospace', color: c, minWidth: 36 }}>
          {pct.toFixed(0)}%
        </span>
      </div>
    )
  }

  return (
    <Link to={`/servers/${srv.id}`} style={{ textDecoration: 'none' }}>
      <div className="card" style={{ padding: '12px 14px', cursor: 'pointer' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 8 }}>
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: dot, flexShrink: 0 }} />
          <span style={{ fontWeight: 700, fontSize: 13 }}>{srv.name}</span>
          {srv.issues_24h > 0 && (
            <span style={{
              marginLeft: 'auto', fontSize: 10, fontWeight: 600,
              color: 'var(--warning)', display: 'flex', alignItems: 'center', gap: 3,
            }}>
              <AlertTriangle size={10} />{srv.issues_24h}
            </span>
          )}
        </div>
        {bar(srv.cpu_pct)}
        {bar(srv.ram_pct)}
        {bar(srv.disk_pct)}
        {srv.cpu_pct == null && (
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>No metrics</div>
        )}
      </div>
    </Link>
  )
}

// ── Dashboard ─────────────────────────────────────────────────────────────────

let _feedId = 0

export default function Dashboard() {
  const navigate = useNavigate()
  const [summary,   setSummary]   = useState<DashboardSummary | null>(null)
  const [loading,   setLoading]   = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [liveEvents, setLiveEvents] = useState<string[]>([])
  const [countdown,  setCountdown]  = useState(20)
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  async function load(quiet = false) {
    if (!quiet) setLoading(true)
    else setRefreshing(true)
    try {
      const s = await getDashboardSummary()
      setSummary(s)
      if (quiet) setCountdown(20)
    } catch (err) {
      console.error('Dashboard load failed', err)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  // Auto-refresh every 20 s to match agent collection interval
  useEffect(() => {
    load()
    const refreshInterval = setInterval(() => load(true), 20000)
    const tickInterval    = setInterval(() => setCountdown(c => Math.max(0, c - 1)), 1000)
    return () => { clearInterval(refreshInterval); clearInterval(tickInterval) }
  }, [])

  const handleWsEvent = useCallback((event: WsEvent) => {
    if (event._event === 'anomaly') {
      setLiveEvents(prev => [`New anomaly detected on server`, ...prev].slice(0, 3))
      // Debounce refresh — don't hammer the API on anomaly bursts
      if (refreshTimer.current) clearTimeout(refreshTimer.current)
      refreshTimer.current = setTimeout(() => load(true), 3000)
    } else if (event._event === 'explanation') {
      setLiveEvents(prev => [`AI analysis complete`, ...prev].slice(0, 3))
      if (refreshTimer.current) clearTimeout(refreshTimer.current)
      refreshTimer.current = setTimeout(() => load(true), 2000)
    }
  }, [])

  const { connected } = useWebSocket(handleWsEvent)

  function logout() { clearSession(); navigate('/login') }

  return (
    <>
      {/* ── Navbar ──────────────────────────────────────────────── */}
      <nav className="navbar">
        <div className="navbar-inner">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Logo variant="dark" size="sm" />
            <div style={{ width: 1, height: 20, background: 'var(--border)', margin: '0 8px' }} />
            <Link to="/"          className="nav-link nav-link--active">Dashboard</Link>
            <Link to="/metrics"   className="nav-link">Metrics</Link>
            <Link to="/incidents" className="nav-link">Incidents</Link>
            <Link to="/runbooks"  className="nav-link">Runbooks</Link>
            <Link to="/forecasts" className="nav-link">Forecasts</Link>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{
              fontSize: 11, color: 'var(--muted)', display: 'flex', alignItems: 'center', gap: 5,
              padding: '4px 10px', background: 'var(--bg-alt)', borderRadius: 20, border: '1px solid var(--border-lt)',
            }}>
              <span className={`live-dot live-dot--${connected ? 'on' : 'off'}`} />
              <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 10 }}>
                {connected ? `live · ${countdown}s` : 'offline'}
              </span>
            </div>
            <button
              onClick={() => load(true)}
              disabled={refreshing}
              style={{ background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', padding: '6px 14px', fontSize: 13 }}
            >
              {refreshing ? <Spinner size={13} /> : <RefreshCw size={13} style={{ marginRight: 4 }} />}
              Refresh
            </button>
            <button onClick={logout} style={{ background: 'transparent', color: 'var(--muted)', border: '1px solid var(--border)', padding: '6px 14px', fontSize: 13 }}>
              Sign out
            </button>
          </div>
        </div>
      </nav>

      <div className="page fade-in">
        {loading ? (
          <div style={{ textAlign: 'center', color: 'var(--muted)', padding: 80 }}>
            <Spinner size={28} color="var(--muted)" style={{ marginBottom: 12 }} />
            <div style={{ fontSize: 14 }}>Checking your systems…</div>
          </div>
        ) : !summary ? (
          <div style={{ textAlign: 'center', color: 'var(--danger)', padding: 80 }}>
            <AlertTriangle size={28} style={{ marginBottom: 10 }} />
            <div>Could not load dashboard. Is the API running?</div>
          </div>
        ) : (
          <>
            {/* ── Live events strip ───────────────── */}
            {liveEvents.length > 0 && (
              <div style={{
                display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 20,
              }}>
                {liveEvents.map((e, i) => (
                  <span key={i} style={{
                    fontSize: 11, background: 'var(--event-ai-bg)', color: 'var(--event-ai-fg)',
                    borderRadius: 20, padding: '3px 10px', fontWeight: 600,
                  }}>
                    {e}
                  </span>
                ))}
              </div>
            )}

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: 24, alignItems: 'start' }}>

              {/* ── Left column: issues + actions ──── */}
              <div>

                {/* Potential Issues */}
                <div className="card" style={{ marginBottom: 20 }}>
                  <div style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    marginBottom: 16,
                  }}>
                    <div>
                      <div className="section-title" style={{ marginBottom: 3 }}>Potential Issues</div>
                      <div style={{ fontSize: 12, color: 'var(--muted)' }}>
                        Things that might need your attention
                      </div>
                    </div>
                    {summary.potential_issues.length > 0 && (
                      <span style={{
                        background: summary.overall_status === 'critical' ? 'var(--event-anomaly-bg)' : '#fff7ed',
                        color: summary.overall_status === 'critical' ? 'var(--danger)' : 'var(--warning)',
                        fontSize: 11, fontWeight: 700, borderRadius: 20, padding: '3px 10px',
                      }}>
                        {summary.potential_issues.length} found
                      </span>
                    )}
                  </div>

                  {summary.potential_issues.length === 0 ? (
                    <div style={{
                      textAlign: 'center', padding: '28px 0',
                      display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                      color: 'var(--success)', fontWeight: 600, fontSize: 13,
                    }}>
                      <Check size={18} />Nothing to worry about right now
                    </div>
                  ) : (
                    summary.potential_issues.map((issue, i) => (
                      <IssueRow key={i} issue={issue} />
                    ))
                  )}
                </div>

                {/* Recommended Actions */}
                {summary.recommended_actions.length > 0 && (
                  <div className="card">
                    <div className="section-title" style={{ marginBottom: 4 }}>Recommended Actions</div>
                    <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 16 }}>
                      Do these in order to get ahead of problems
                    </div>

                    {summary.recommended_actions.map((action, i) => (
                      <div key={i} style={{
                        display: 'flex', gap: 14, paddingBottom: 14,
                        borderBottom: i < summary.recommended_actions.length - 1 ? '1px solid var(--border-lt)' : 'none',
                        marginBottom: i < summary.recommended_actions.length - 1 ? 14 : 0,
                      }}>
                        <div style={{
                          width: 26, height: 26, borderRadius: '50%', flexShrink: 0,
                          background: 'var(--brand)', color: '#fff',
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                          fontWeight: 800, fontSize: 12, fontFamily: 'Syne, sans-serif',
                        }}>
                          {action.priority}
                        </div>
                        <div style={{ flex: 1 }}>
                          <div style={{ fontWeight: 600, fontSize: 13.5, color: 'var(--text)', marginBottom: 4 }}>
                            {action.action}
                          </div>
                          <div style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.5 }}>
                            <span style={{ fontWeight: 600, color: 'var(--muted)', fontFamily: 'JetBrains Mono, monospace', fontSize: 10 }}>
                              {action.server_name}
                            </span>
                            {' — '}{action.reason}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* No actions needed */}
                {summary.recommended_actions.length === 0 && (
                  <div className="card" style={{ textAlign: 'center', padding: '24px 0' }}>
                    <Check size={20} color="var(--success)" style={{ marginBottom: 8 }} />
                    <div style={{ fontSize: 13, color: 'var(--success)', fontWeight: 600 }}>
                      No actions needed right now
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
                      Your systems are running smoothly.
                    </div>
                  </div>
                )}

              </div>

              {/* ── Right column: server mini-grid ─── */}
              <div>
                <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span className="section-title">Your Servers</span>
                  <Link to="/metrics" style={{
                    fontSize: 11, color: 'var(--brand)', fontWeight: 600,
                    display: 'flex', alignItems: 'center', gap: 3,
                  }}>
                    Full metrics <ArrowRight size={11} />
                  </Link>
                </div>

                {summary.servers.length === 0 ? (
                  <div className="card" style={{ textAlign: 'center', padding: 32, fontSize: 13, color: 'var(--muted)' }}>
                    No servers enrolled yet.<br />
                    <Link to="/metrics" style={{ color: 'var(--brand)', fontWeight: 600 }}>
                      Set up a server →
                    </Link>
                  </div>
                ) : (
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                    {summary.servers.map(srv => (
                      <ServerMini key={srv.id} srv={srv} />
                    ))}
                  </div>
                )}

                {/* Quick links */}
                <div style={{ marginTop: 20, display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <Link to="/forecasts" style={{ textDecoration: 'none' }}>
                    <div style={{
                      padding: '10px 14px', background: 'var(--bg-alt)', borderRadius: 9,
                      border: '1px solid var(--border)', display: 'flex',
                      justifyContent: 'space-between', alignItems: 'center', fontSize: 13,
                      color: 'var(--text)', fontWeight: 500,
                    }}>
                      24-hour predictions <ArrowRight size={13} color="var(--muted)" />
                    </div>
                  </Link>
                  <Link to="/incidents" style={{ textDecoration: 'none' }}>
                    <div style={{
                      padding: '10px 14px', background: 'var(--bg-alt)', borderRadius: 9,
                      border: '1px solid var(--border)', display: 'flex',
                      justifyContent: 'space-between', alignItems: 'center', fontSize: 13,
                      color: 'var(--text)', fontWeight: 500,
                    }}>
                      Incident log <ArrowRight size={13} color="var(--muted)" />
                    </div>
                  </Link>
                  <Link to="/runbooks" style={{ textDecoration: 'none' }}>
                    <div style={{
                      padding: '10px 14px', background: 'var(--bg-alt)', borderRadius: 9,
                      border: '1px solid var(--border)', display: 'flex',
                      justifyContent: 'space-between', alignItems: 'center', fontSize: 13,
                      color: 'var(--text)', fontWeight: 500,
                    }}>
                      Fix guides (runbooks) <ArrowRight size={13} color="var(--muted)" />
                    </div>
                  </Link>
                </div>

                {/* Last updated */}
                <div style={{ marginTop: 14, fontSize: 10, color: 'var(--muted-lt)', textAlign: 'center', fontFamily: 'JetBrains Mono, monospace' }}>
                  Updated {new Date(summary.generated_at).toLocaleTimeString()}
                </div>
              </div>

            </div>
          </>
        )}
      </div>
    </>
  )
}
