import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  PieChart, Pie, Cell, AreaChart, Area,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { listAnomalies, listServers, getServerSummary, downloadServerReport } from '../api'
import { clearSession } from '../auth'
import { useWebSocket } from '../useWebSocket'
import Logo from '../components/Logo'
import PipelineFlow from '../components/PipelineFlow'
import { AlertTriangle, ArrowRight, Check, Download, Spinner } from '../components/Icons'
import type { Anomaly, ServerSummary, WsEvent } from '../types'

// ── helpers ───────────────────────────────────────────────────────────────────

function fmt(n: number) { return n >= 1000 ? `${(n/1000).toFixed(1)}k` : String(n) }

function GaugeBar({ label, pct, warn = 75, crit = 90 }: {
  label: string; pct: number; warn?: number; crit?: number
}) {
  const color = pct >= crit ? 'var(--danger)' : pct >= warn ? 'var(--warning)' : 'var(--success)'
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 11 }}>
        <span style={{ color: 'var(--muted)', fontWeight: 500 }}>{label}</span>
        <span style={{ fontWeight: 700, color, fontFamily: 'JetBrains Mono, monospace', fontSize: 11 }}>
          {pct.toFixed(1)}%
        </span>
      </div>
      <div className="progress-bar">
        <div className="progress-bar__fill" style={{ width: `${Math.min(pct, 100)}%`, background: color }} />
      </div>
    </div>
  )
}

function ServerCard({ server }: { server: ServerSummary }) {
  const isOk  = server.status === 'online'
  const isBad = server.status === 'offline'
  const [exporting, setExporting] = useState(false)

  const borderColor = isBad ? 'var(--danger)' : isOk ? 'var(--success)' : 'var(--warning)'

  async function handleExport(e: MouseEvent) {
    e.preventDefault(); e.stopPropagation()
    setExporting(true)
    try { await downloadServerReport(server.id, server.name) }
    catch (err) { console.error(err) }
    finally { setExporting(false) }
  }

  return (
    <Link to={`/servers/${server.id}`} className="server-card">
      <div className="card" style={{ borderLeft: `3px solid ${borderColor}`, padding: '16px 18px' }}>
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
          <div>
            <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 2 }}>{server.name}</div>
            <div style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 10, color: 'var(--muted)' }}>
              {server.hostname}
            </div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6 }}>
            <span className={`badge badge-${server.status}`}>{server.status}</span>
            <button
              onClick={handleExport}
              disabled={exporting}
              title="Export PDF report"
              style={{
                background: 'transparent', border: '1px solid var(--border)',
                color: 'var(--muted)', borderRadius: 5, padding: '2px 7px',
                fontSize: 10, cursor: exporting ? 'not-allowed' : 'pointer',
              }}
            >
              {exporting ? <Spinner size={11} /> : <><Download size={11} style={{ marginRight: 3 }} />PDF</>}
            </button>
          </div>
        </div>

        {/* Gauges */}
        <GaugeBar label="CPU"  pct={server.cpu_pct}  />
        <GaugeBar label="RAM"  pct={server.ram_pct}  />
        <GaugeBar label="Disk" pct={server.disk_pct} />

        {/* Anomaly badge */}
        {server.anomaly_count_24h > 0 ? (
          <div style={{
            marginTop: 10, display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          }}>
            <span style={{
              fontSize: 11, fontWeight: 600,
              color: server.anomaly_count_24h > 5 ? 'var(--danger)' : 'var(--warning)',
              display: 'flex', alignItems: 'center', gap: 4,
            }}>
              <AlertTriangle size={12} style={{ marginRight: 3 }} />{server.anomaly_count_24h} anomal{server.anomaly_count_24h === 1 ? 'y' : 'ies'} / 24h
            </span>
            <span style={{ fontSize: 10, color: 'var(--muted-lt)', display: 'flex', alignItems: 'center', gap: 2 }}><ArrowRight size={11} /> details</span>
          </div>
        ) : (
          <div style={{ marginTop: 10, fontSize: 11, color: 'var(--success)', fontWeight: 500, display: 'flex', alignItems: 'center', gap: 4 }}>
            <Check size={12} />No anomalies
          </div>
        )}
      </div>
    </Link>
  )
}

// ── live event feed ───────────────────────────────────────────────────────────

interface FeedEvent {
  id:       string
  type:     'anomaly' | 'explanation' | 'connected' | 'metric'
  label:    string
  detail:   string
  ts:       Date
}

const TYPE_STYLE: Record<string, { bg: string; color: string; text: string }> = {
  anomaly:     { bg: 'var(--event-anomaly-bg)', color: 'var(--event-anomaly-fg)', text: 'ANOMALY' },
  explanation: { bg: 'var(--event-ai-bg)',      color: 'var(--event-ai-fg)',      text: 'AI DONE' },
  connected:   { bg: 'var(--event-conn-bg)',     color: 'var(--event-conn-fg)',    text: 'CONN' },
  metric:      { bg: 'var(--event-metric-bg)',   color: 'var(--event-metric-fg)',  text: 'METRIC' },
}

// ── charts config ─────────────────────────────────────────────────────────────

const HEALTH_COLORS: Record<string, string> = {
  Online:   '#16a34a',
  Degraded: '#d97706',
  Offline:  '#dc2626',
  Pending:  '#6366f1',
}

const SEV_COLORS: Record<string, string> = {
  critical: '#dc2626',
  high:     '#ea580c',
  medium:   '#d97706',
  warning:  '#d97706',
  low:      '#16a34a',
}

let _feedId = 0

// ── Dashboard ─────────────────────────────────────────────────────────────────

export default function Dashboard() {
  const navigate = useNavigate()
  const [servers,          setServers]          = useState<ServerSummary[]>([])
  const [recentAnomalies,  setRecentAnomalies]  = useState<Anomaly[]>([])
  const [loading,          setLoading]          = useState(true)
  const [feedEvents,       setFeedEvents]       = useState<FeedEvent[]>([])
  const [lastUpdated,      setLastUpdated]       = useState<Date | null>(null)
  const [countdown,        setCountdown]         = useState(20)
  const feedRef = useRef<HTMLDivElement>(null)

  function pushFeed(evt: FeedEvent) {
    setFeedEvents(prev => [evt, ...prev].slice(0, 40))
  }

  async function loadData(quiet = false) {
    if (!quiet) setLoading(true)
    try {
      const srvList = await listServers()
      const summaries = await Promise.all(
        srvList.map(s => getServerSummary(s.id).catch(() => ({
          ...s, cpu_pct: 0, ram_pct: 0, disk_pct: 0, anomaly_count_24h: 0,
        })))
      )
      setServers(summaries as ServerSummary[])
      const anomalies = await listAnomalies(undefined, 50)
      setRecentAnomalies(anomalies)
      setLastUpdated(new Date())
      setCountdown(20)
    } catch (err) {
      console.error('Load failed', err)
    } finally {
      if (!quiet) setLoading(false)
    }
  }

  // Auto-refresh every 20 s to match agent collection interval
  useEffect(() => {
    loadData()
    const refreshInterval = setInterval(() => loadData(true), 20000)
    const tickInterval    = setInterval(() => setCountdown(c => Math.max(0, c - 1)), 1000)
    return () => { clearInterval(refreshInterval); clearInterval(tickInterval) }
  }, [])

  // auto-scroll feed
  useEffect(() => {
    if (feedRef.current) feedRef.current.scrollTop = 0
  }, [feedEvents])

  const handleWsEvent = useCallback((event: WsEvent) => {
    if (event._event === 'anomaly') {
      const a = event as unknown as Anomaly & { server_id: string }
      setRecentAnomalies(prev => [event as unknown as Anomaly, ...prev.slice(0, 49)])
      if (a.server_id) {
        getServerSummary(a.server_id).then(s => {
          setServers(prev => prev.map(x => x.id === a.server_id ? s : x))
        }).catch(() => {})
      }
      pushFeed({
        id:     String(++_feedId),
        type:   'anomaly',
        label:  a.metric_name?.replace('system.', '') ?? 'metric',
        detail: `${a.severity ?? '?'} on ${(a as unknown as Record<string,string>).hostname ?? a.server_id ?? '?'}`,
        ts:     new Date(),
      })
    } else if (event._event === 'explanation') {
      pushFeed({
        id:     String(++_feedId),
        type:   'explanation',
        label:  'AI explanation',
        detail: `analysis complete`,
        ts:     new Date(),
      })
    }
  }, [])

  const { connected } = useWebSocket(handleWsEvent)

  useEffect(() => {
    if (connected) {
      pushFeed({ id: String(++_feedId), type: 'connected', label: 'WebSocket', detail: 'connected to WS Gateway :8080', ts: new Date() })
    }
  }, [connected])

  // ── derived chart data ────────────────────────────────────────────────────

  const healthPieData = useMemo(() =>
    Object.entries(
      servers.reduce((acc, s) => {
        const k = s.status.charAt(0).toUpperCase() + s.status.slice(1)
        acc[k] = (acc[k] ?? 0) + 1
        return acc
      }, {} as Record<string, number>)
    ).map(([name, value]) => ({ name, value }))
  , [servers])

  // Timeline: anomaly counts per last 20 events bucketed by minute
  const anomalyTimeline = useMemo(() => {
    if (!recentAnomalies.length) return []
    const buckets: Record<string, { t: string; critical: number; warning: number; low: number }> = {}
    recentAnomalies.slice(0, 30).forEach(a => {
      const t = new Date(a.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      if (!buckets[t]) buckets[t] = { t, critical: 0, warning: 0, low: 0 }
      const sev = a.severity === 'critical' ? 'critical' : a.severity === 'warning' ? 'warning' : 'low'
      buckets[t][sev]++
    })
    return Object.values(buckets).reverse()
  }, [recentAnomalies])

  const totalServers   = servers.length
  const onlineCount    = servers.filter(s => s.status === 'online').length
  const totalAnomalies = recentAnomalies.length
  const criticalCount  = recentAnomalies.filter(a => a.severity === 'critical').length
  const totalCpu       = servers.length ? Math.round(servers.reduce((s, x) => s + x.cpu_pct, 0) / servers.length) : 0
  const totalRam       = servers.length ? Math.round(servers.reduce((s, x) => s + x.ram_pct, 0) / servers.length) : 0

  function logout() { clearSession(); navigate('/login') }

  return (
    <>
      {/* ── Navbar ──────────────────────────────────────────────────── */}
      <nav className="navbar">
        <div className="navbar-inner">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Logo variant="dark" size="sm" />
            <div style={{ width: 1, height: 20, background: 'var(--border)', margin: '0 8px' }} />
            <Link to="/"           className="nav-link nav-link--active">Dashboard</Link>
            <Link to="/incidents"  className="nav-link">Incidents</Link>
            <Link to="/runbooks"   className="nav-link">Runbooks</Link>
            <Link to="/forecasts"  className="nav-link">Forecasts</Link>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ fontSize: 11, color: 'var(--muted)', display: 'flex', alignItems: 'center', gap: 5,
              padding: '4px 10px', background: 'var(--bg-alt)', borderRadius: 20, border: '1px solid var(--border-lt)' }}>
              <span className={`live-dot live-dot--${connected ? 'on' : 'off'}`} />
              <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 10 }}>
                {connected ? `live · refresh in ${countdown}s` : 'connecting'}
              </span>
            </div>
            <button onClick={() => loadData()} style={{ background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', padding: '6px 14px', fontSize: 13 }}>
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
          <div style={{ textAlign: 'center', color: 'var(--muted)', padding: 80, fontSize: 15 }}>
            <Spinner size={28} color="var(--muted)" style={{ marginBottom: 12 }} />
            Loading dashboard…
          </div>
        ) : (
          <>
            {/* ── Pipeline flow ────────────────────────────── */}
            <PipelineFlow wsConnected={connected} />

            {/* ── KPI strip ───────────────────────────────── */}
            <div className="grid grid-5" style={{ marginBottom: 28 }}>
              <div className="kpi-card kpi-card--brand">
                <div className="kpi-value">{totalServers}</div>
                <div className="kpi-label">Total Servers</div>
                <div className="kpi-sub">registered in org</div>
              </div>
              <div className="kpi-card kpi-card--success">
                <div className="kpi-value" style={{ color: 'var(--success)' }}>{onlineCount}</div>
                <div className="kpi-label">Online</div>
                <div className="kpi-sub">{totalServers ? Math.round(onlineCount/totalServers*100) : 0}% uptime</div>
              </div>
              <div className="kpi-card kpi-card--warning">
                <div className="kpi-value" style={{ color: totalAnomalies > 0 ? 'var(--warning)' : 'var(--text)' }}>{fmt(totalAnomalies)}</div>
                <div className="kpi-label">Anomalies</div>
                <div className="kpi-sub">last 24 h</div>
              </div>
              <div className="kpi-card kpi-card--danger">
                <div className="kpi-value" style={{ color: criticalCount > 0 ? 'var(--danger)' : 'var(--text)' }}>{criticalCount}</div>
                <div className="kpi-label">Critical</div>
                <div className="kpi-sub">require action</div>
              </div>
              <div className="kpi-card kpi-card--info">
                <div className="kpi-value" style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 24 }}>
                  {totalCpu}%
                </div>
                <div className="kpi-label">Avg CPU</div>
                <div className="kpi-sub">RAM avg {totalRam}%</div>
              </div>
            </div>

            {/* ── Main content: charts + event feed ────────── */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 300px', gap: 20, marginBottom: 28 }}>

              {/* Health pie */}
              <div className="card">
                <div className="section-title">Server Health Distribution</div>
                {healthPieData.length === 0 ? (
                  <div className="text-muted text-sm" style={{ textAlign: 'center', padding: 40 }}>No servers</div>
                ) : (
                  <>
                    <ResponsiveContainer width="100%" height={185}>
                      <PieChart>
                        <Pie data={healthPieData} cx="50%" cy="50%" innerRadius={52} outerRadius={80}
                          paddingAngle={3} dataKey="value" strokeWidth={0}>
                          {healthPieData.map(e => <Cell key={e.name} fill={HEALTH_COLORS[e.name] ?? '#6b7280'} />)}
                        </Pie>
                        <Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }} />
                      </PieChart>
                    </ResponsiveContainer>
                    <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
                      {healthPieData.map(e => (
                        <div key={e.name} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
                          <span style={{ width: 8, height: 8, borderRadius: '50%', background: HEALTH_COLORS[e.name] ?? '#6b7280', flexShrink: 0 }} />
                          <span style={{ color: 'var(--muted)' }}>{e.name}</span>
                          <span style={{ fontWeight: 700 }}>{e.value}</span>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>

              {/* Anomaly timeline */}
              <div className="card">
                <div className="section-title">Anomaly Timeline</div>
                {anomalyTimeline.length === 0 ? (
                  <div style={{ textAlign: 'center', padding: 48, color: 'var(--success)', fontWeight: 500, fontSize: 13, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
                    <Check size={16} />No anomalies detected
                  </div>
                ) : (
                  <ResponsiveContainer width="100%" height={185}>
                    <AreaChart data={anomalyTimeline} margin={{ top: 4, right: 8, left: -24, bottom: 0 }}>
                      <defs>
                        <linearGradient id="gcrit" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#dc2626" stopOpacity={0.25} />
                          <stop offset="95%" stopColor="#dc2626" stopOpacity={0} />
                        </linearGradient>
                        <linearGradient id="gwarn" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#d97706" stopOpacity={0.2} />
                          <stop offset="95%" stopColor="#d97706" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                      <XAxis dataKey="t" tick={{ fontSize: 9, fill: 'var(--muted)' }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
                      <YAxis tick={{ fontSize: 9, fill: 'var(--muted)' }} tickLine={false} axisLine={false} allowDecimals={false} />
                      <Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 11 }} />
                      <Area type="monotone" dataKey="critical" stroke="#dc2626" strokeWidth={2} fill="url(#gcrit)" dot={false} isAnimationActive={false} />
                      <Area type="monotone" dataKey="warning"  stroke="#d97706" strokeWidth={2} fill="url(#gwarn)" dot={false} isAnimationActive={false} />
                    </AreaChart>
                  </ResponsiveContainer>
                )}
              </div>

              {/* Live event feed */}
              <div className="card" style={{ padding: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
                <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--border-lt)',
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div className="section-title" style={{ marginBottom: 0, fontSize: 11 }}>Live Event Feed</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 10, color: 'var(--muted)' }}>
                    <span className={`live-dot live-dot--${connected ? 'on' : 'off'}`} />
                    WS :8080
                  </div>
                </div>
                <div ref={feedRef} className="event-feed" style={{ flex: 1, maxHeight: 220 }}>
                  {feedEvents.length === 0 ? (
                    <div style={{ padding: '24px 14px', textAlign: 'center', color: 'var(--muted)', fontSize: 12, lineHeight: 1.7 }}>
                      Waiting for live events…<br />
                      <span style={{ fontSize: 10 }}>Anomalies and AI completions appear here</span>
                    </div>
                  ) : (
                    feedEvents.map(ev => {
                      const style = TYPE_STYLE[ev.type] ?? TYPE_STYLE['metric']
                      return (
                        <div key={ev.id} className="event-item">
                          <span className="event-item__type" style={{ background: style.bg, color: style.color }}>
                            {style.text}
                          </span>
                          <div className="event-item__body">
                            <div style={{ fontWeight: 600, color: 'var(--text)' }}>{ev.label}</div>
                            <div style={{ color: 'var(--muted)' }}>{ev.detail}</div>
                          </div>
                          <span className="event-item__time">
                            {ev.ts.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                          </span>
                        </div>
                      )
                    })
                  )}
                </div>
              </div>
            </div>

            {/* ── Server grid ─────────────────────────────── */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
              <div className="section-title" style={{ marginBottom: 0 }}>
                Servers
                <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--muted)', marginLeft: 2 }}>({servers.length})</span>
              </div>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>Click a server for metrics detail and AI analysis</div>
            </div>

            {servers.length === 0 ? (
              <div className="card text-muted" style={{ textAlign: 'center', padding: 40 }}>
                No servers registered. Enroll one via the Admin API.
              </div>
            ) : (
              <div className="grid grid-2" style={{ marginBottom: 36 }}>
                {servers.map(s => <ServerCard key={s.id} server={s} />)}
              </div>
            )}

            {/* ── Recent anomalies table ───────────────────── */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <div className="section-title" style={{ marginBottom: 0 }}>
                Recent Anomalies
                <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--muted)', marginLeft: 2 }}>
                  ({recentAnomalies.length})
                </span>
              </div>
              <Link to="/incidents" style={{ fontSize: 12, color: 'var(--brand)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 4 }}>
                <ArrowRight size={13} />Incident log &amp; AI analysis
              </Link>
            </div>

            {recentAnomalies.length === 0 ? (
              <div className="card" style={{ padding: 28, textAlign: 'center' }}>
                <Check size={22} color="var(--success)" style={{ marginBottom: 8 }} />
                <div style={{ color: 'var(--muted)', fontSize: 13 }}>No anomalies in the last 24 hours.</div>
              </div>
            ) : (
              <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      {['Time', 'Metric', 'Value', 'Threshold', 'Detector', 'Severity'].map(h => (
                        <th key={h}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {recentAnomalies.slice(0, 25).map(a => (
                      <tr key={a.id} className={`data-table-row--${a.severity === 'critical' ? 'critical' : a.severity === 'warning' ? 'warning' : ''}`}>
                        <td style={{ color: 'var(--muted)', whiteSpace: 'nowrap', fontFamily: 'JetBrains Mono, monospace', fontSize: 11 }}>
                          {new Date(a.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                        </td>
                        <td style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 11 }}>
                          {a.metric_name.replace('system.', '')}
                        </td>
                        <td style={{ fontWeight: 700, fontFamily: 'JetBrains Mono, monospace', fontSize: 12 }}>
                          {(a.value * 100).toFixed(1)}%
                        </td>
                        <td style={{ color: 'var(--muted)', fontSize: 12 }}>
                          {a.threshold != null ? `${(a.threshold * 100).toFixed(1)}%` : '—'}
                        </td>
                        <td style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 10, color: 'var(--muted)' }}>
                          {a.detector}
                        </td>
                        <td>
                          <span style={{
                            fontSize: 11, fontWeight: 700,
                            color: SEV_COLORS[a.severity] ?? 'var(--muted)',
                            background: `${SEV_COLORS[a.severity] ?? 'var(--muted)'}18`,
                            padding: '2px 8px', borderRadius: 12,
                          }}>
                            {a.severity}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </>
  )
}
