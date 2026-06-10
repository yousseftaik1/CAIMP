import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts'
import { listForecasts, listServers } from '../api'
import { clearSession } from '../auth'
import Logo from '../components/Logo'
import {
  AlertTriangle, BarChart, Check, ChevronDown, ChevronRight,
  Minus, RefreshCw, Spinner, TrendingDown, TrendingUp,
} from '../components/Icons'
import type { ForecastResponse, Server } from '../types'

// ── Types ─────────────────────────────────────────────────────────────────────

type HealthLevel = 'critical' | 'warning' | 'healthy' | 'unknown'

// ── Helpers ───────────────────────────────────────────────────────────────────

const METRIC_LABEL: Record<string, string> = {
  cpu_percent:    'CPU',
  memory_percent: 'RAM',
  disk_percent:   'Disk',
}
const METRIC_ORDER = ['cpu_percent', 'memory_percent', 'disk_percent']

function metricHealth(f: ForecastResponse | undefined): HealthLevel {
  if (!f || !f.points.length) return 'unknown'
  const next1h = f.points[0]?.predicted ?? 0
  if (next1h >= (f.critical_threshold ?? 0.9) ||
      (f.time_to_critical !== null && f.time_to_critical <= 4)) return 'critical'
  if (next1h >= 0.75 ||
      (f.time_to_critical !== null && f.time_to_critical <= 12)) return 'warning'
  return 'healthy'
}

function serverHealth(forecasts: ForecastResponse[]): HealthLevel {
  if (!forecasts.length) return 'unknown'
  const levels = forecasts.map(f => metricHealth(f))
  if (levels.includes('critical')) return 'critical'
  if (levels.includes('warning'))  return 'warning'
  if (levels.every(l => l === 'healthy')) return 'healthy'
  return 'unknown'
}

function healthColor(h: HealthLevel): string {
  if (h === 'critical') return 'var(--danger)'
  if (h === 'warning')  return 'var(--warning)'
  if (h === 'healthy')  return 'var(--success)'
  return 'var(--muted)'
}

function healthLabel(h: HealthLevel): string {
  if (h === 'critical') return 'CRITICAL'
  if (h === 'warning')  return 'AT RISK'
  if (h === 'healthy')  return 'HEALTHY'
  return 'NO DATA'
}

function TrendIcon({ slope, color }: { slope: number | null; color: string }) {
  if (slope === null) return <Minus size={13} color={color} />
  if (slope >  0.003)  return <TrendingUp  size={14} color={color} style={{ strokeWidth: 2.5 }} />
  if (slope >  0.0005) return <TrendingUp  size={13} color={color} />
  if (slope < -0.003)  return <TrendingDown size={14} color={color} style={{ strokeWidth: 2.5 }} />
  if (slope < -0.0005) return <TrendingDown size={13} color={color} />
  return <Minus size={13} color={color} />
}

function trendColor(slope: number | null): string {
  if (slope === null) return 'var(--muted)'
  if (slope > 0.0005)  return 'var(--danger)'
  if (slope < -0.0005) return 'var(--success)'
  return 'var(--muted)'
}

function fmtTtc(ttc: number | null): string {
  if (ttc === null) return '—'
  if (ttc < 1)      return '<1h'
  return `${ttc.toFixed(1)}h`
}

function ttcColor(ttc: number | null): string {
  if (ttc === null) return 'var(--success)'
  if (ttc <= 6)     return 'var(--danger)'
  if (ttc <= 24)    return 'var(--warning)'
  return 'var(--muted)'
}

// ── SparkLine ─────────────────────────────────────────────────────────────────

function SparkLine({ forecast, height = 56 }: { forecast: ForecastResponse; height?: number }) {
  const health    = metricHealth(forecast)
  const lineColor = healthColor(health)
  const threshold = (forecast.critical_threshold ?? 0.9) * 100
  const uid       = forecast.id.slice(-8)

  const data = forecast.points.slice(0, 24).map(p => ({
    h:    p.hour,
    base: +(p.lower  * 100).toFixed(2),
    band: +((p.upper - p.lower) * 100).toFixed(2),
    val:  +(p.predicted * 100).toFixed(2),
  }))

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 4, right: 2, bottom: 2, left: 0 }}>
        <defs>
          <linearGradient id={`fg-${uid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%"   stopColor={lineColor} stopOpacity={0.35} />
            <stop offset="100%" stopColor={lineColor} stopOpacity={0.03} />
          </linearGradient>
        </defs>
        <XAxis dataKey="h" hide />
        <YAxis domain={[0, 100]} hide />
        <Tooltip
          contentStyle={{
            background: 'var(--surface)', border: '1px solid var(--border)',
            borderRadius: 6, fontSize: 11, fontFamily: 'JetBrains Mono, monospace',
            padding: '4px 8px',
          }}
          formatter={(v: number, name: string) =>
            name === 'val' ? [`${v.toFixed(1)}%`, 'Predicted'] : [null, null]
          }
          labelFormatter={(h: number) => `+${h}h`}
        />
        <ReferenceLine y={threshold} stroke="rgba(220,38,38,0.5)" strokeDasharray="3 3" />
        {/* confidence band stacked on a transparent baseline */}
        <Area type="monotone" dataKey="base" stroke="none" fill="transparent" stackId="b" />
        <Area type="monotone" dataKey="band" stroke="none" fill={lineColor} fillOpacity={0.08} stackId="b" />
        {/* predicted line */}
        <Area
          type="monotone" dataKey="val" stroke={lineColor} strokeWidth={1.5}
          fill={`url(#fg-${uid})`} dot={false} name="val"
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}

// ── MetricRow ─────────────────────────────────────────────────────────────────

function MetricRow({
  forecast,
  expanded,
  onToggle,
}: {
  forecast: ForecastResponse | undefined
  expanded: boolean
  onToggle: () => void
}) {
  if (!forecast) {
    return (
      <div style={{ padding: '8px 0', borderBottom: '1px solid var(--border)', opacity: 0.35, fontSize: 11, color: 'var(--muted)' }}>
        No data
      </div>
    )
  }

  const h      = metricHealth(forecast)
  const color  = healthColor(h)
  const next1h = forecast.points[0]?.predicted ?? 0
  const label  = METRIC_LABEL[forecast.metric_name] ?? forecast.metric_name

  return (
    <div style={{ borderBottom: '1px solid var(--border)' }}>
      <div
        onClick={onToggle}
        style={{
          display: 'grid',
          gridTemplateColumns: '38px 1fr 58px 24px 68px',
          alignItems: 'center',
          gap: 8,
          padding: '9px 0',
          cursor: 'pointer',
          userSelect: 'none',
        }}
      >
        <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--muted)', letterSpacing: '0.04em' }}>
          {label}
        </span>
        <div className="progress-bar" style={{ height: 4 }}>
          <div className="progress-bar__fill" style={{ width: `${Math.min(100, next1h * 100)}%`, background: color }} />
        </div>
        <span style={{
          fontFamily: 'JetBrains Mono, monospace', fontSize: 12, fontWeight: 700,
          color, textAlign: 'right',
        }}>
          {(next1h * 100).toFixed(1)}%
        </span>
        <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <TrendIcon slope={forecast.trend_slope} color={trendColor(forecast.trend_slope)} />
        </span>
        <span style={{
          fontFamily: 'JetBrains Mono, monospace', fontSize: 10, fontWeight: 600,
          color: ttcColor(forecast.time_to_critical), textAlign: 'right',
        }}>
          {forecast.time_to_critical !== null
            ? <span style={{ display: 'flex', alignItems: 'center', gap: 2, justifyContent: 'flex-end' }}><AlertTriangle size={10} />{fmtTtc(forecast.time_to_critical)}</span>
            : <span style={{ display: 'flex', alignItems: 'center', gap: 2, justifyContent: 'flex-end' }}><Check size={10} />safe</span>}
        </span>
      </div>

      {expanded && (
        <div style={{ paddingBottom: 10, paddingLeft: 46 }}>
          <SparkLine forecast={forecast} />
          <div style={{
            display: 'flex', justifyContent: 'space-between',
            marginTop: 2, fontSize: 9,
            fontFamily: 'JetBrains Mono, monospace', color: 'var(--muted)',
          }}>
            <span>+1h</span><span>+12h</span><span>+24h</span>
          </div>
        </div>
      )}
    </div>
  )
}

// ── ServerForecastCard ────────────────────────────────────────────────────────

function ServerForecastCard({ server, forecasts }: {
  server: Server | undefined
  forecasts: ForecastResponse[]
}) {
  const [expandedMetric, setExpandedMetric] = useState<string | null>(null)
  const [showNarrative,  setShowNarrative]  = useState(false)

  const health = serverHealth(forecasts)
  const hColor = healthColor(health)

  const fByMetric = useMemo(() =>
    Object.fromEntries(forecasts.map(f => [f.metric_name, f])),
  [forecasts])

  // Nearest-breach forecast for the narrative
  const criticalForecast = useMemo(() =>
    [...forecasts]
      .filter(f => f.time_to_critical !== null)
      .sort((a, b) => (a.time_to_critical ?? 999) - (b.time_to_critical ?? 999))[0]
      ?? forecasts[0],
  [forecasts])

  const updatedAt = forecasts[0]?.forecasted_at
    ? new Date(forecasts[0].forecasted_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : '—'

  const toggleMetric = (m: string) =>
    setExpandedMetric(prev => prev === m ? null : m)

  const next1hWorstPct = Math.max(
    0,
    ...forecasts.map(f => (f.points[0]?.predicted ?? 0) * 100),
  )

  return (
    <div className="card" style={{ borderLeft: `3px solid ${hColor}`, padding: '18px 20px' }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 12 }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 3 }}>
            {server?.name ?? 'Unknown Server'}
          </div>
          <div style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 10, color: 'var(--muted)' }}>
            {server?.hostname ?? '—'}
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 5 }}>
          <span style={{
            fontSize: 11, fontWeight: 800, letterSpacing: '0.08em',
            padding: '3px 9px', borderRadius: 4,
            background: `${hColor}1a`, color: hColor, border: `1px solid ${hColor}44`,
          }}>
            {healthLabel(health)}
          </span>
          {server?.status && (
            <span className={`badge badge-${server.status}`} style={{ fontSize: 10 }}>
              {server.status}
            </span>
          )}
        </div>
      </div>

      {/* 1-hour verdict banner */}
      <div style={{
        background: `${hColor}0f`, border: `1px solid ${hColor}2a`,
        borderRadius: 6, padding: '8px 12px', marginBottom: 14, fontSize: 12,
      }}>
        <span style={{ color: hColor, fontWeight: 600 }}>
          {health === 'critical'
            ? `⚠ Critical — breach in ${fmtTtc(criticalForecast?.time_to_critical ?? null)}`
            : health === 'warning'
            ? `↑ Elevated — monitor closely (peak next-hour: ${next1hWorstPct.toFixed(0)}%)`
            : health === 'healthy'
            ? `✓ All metrics nominal — no breach within 24h`
            : '— Insufficient forecast data'}
        </span>
      </div>

      {/* Column headers */}
      <div style={{
        display: 'grid', gridTemplateColumns: '38px 1fr 58px 24px 68px',
        gap: 8, padding: '0 0 5px',
        fontSize: 10, color: 'var(--muted)', fontWeight: 500, letterSpacing: '0.05em',
        borderBottom: '1px solid var(--border-lt)',
      }}>
        <span></span><span></span>
        <span style={{ textAlign: 'right' }}>+1h</span>
        <span></span>
        <span style={{ textAlign: 'right' }}>Breach in</span>
      </div>

      {/* Metric rows */}
      <div style={{ marginBottom: 12 }}>
        {METRIC_ORDER.map(m => (
          <MetricRow
            key={m}
            forecast={fByMetric[m]}
            expanded={expandedMetric === m}
            onToggle={() => fByMetric[m] && toggleMetric(m)}
          />
        ))}
      </div>

      {/* AI Narrative */}
      {criticalForecast?.llm_narrative && (
        <div style={{ borderTop: '1px solid var(--border)', paddingTop: 10 }}>
          <button
            onClick={() => setShowNarrative(p => !p)}
            style={{
              background: 'transparent', border: 'none', padding: 0,
              cursor: 'pointer', color: 'var(--muted)', fontSize: 11,
              fontWeight: 600, display: 'flex', alignItems: 'center', gap: 5,
              marginBottom: showNarrative ? 8 : 0,
            }}
          >
            {showNarrative ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            AI Narrative
            {criticalForecast.llm_confidence && (
              <span style={{
                fontSize: 9, borderRadius: 3, padding: '1px 5px',
                background: criticalForecast.llm_confidence === 'high'
                  ? 'var(--success)' : criticalForecast.llm_confidence === 'medium'
                  ? 'var(--warning)' : 'var(--muted)',
                color: '#fff', marginLeft: 2,
              }}>
                {criticalForecast.llm_confidence.toUpperCase()} CONF
              </span>
            )}
            {criticalForecast.accuracy_score != null && (
              <span style={{ fontSize: 10, color: 'var(--muted)', marginLeft: 2 }}>
                · {Math.round(criticalForecast.accuracy_score * 100)}% acc
              </span>
            )}
          </button>
          {showNarrative && (
            <div style={{
              fontSize: 12, color: 'var(--muted)', lineHeight: 1.65,
              padding: '8px 12px', background: 'var(--bg-alt)',
              borderRadius: 6, fontStyle: 'italic',
            }}>
              {criticalForecast.llm_narrative}
            </div>
          )}
        </div>
      )}

      {/* Footer */}
      <div style={{
        marginTop: 10, paddingTop: 8, borderTop: '1px solid var(--border)',
        display: 'flex', justifyContent: 'space-between',
        fontSize: 10, color: 'var(--muted)', fontFamily: 'JetBrains Mono, monospace',
      }}>
        <span>holt_linear · 24h horizon · 90% threshold</span>
        <span>updated {updatedAt}</span>
      </div>
    </div>
  )
}

// ── Forecasts page ────────────────────────────────────────────────────────────

export default function Forecasts() {
  const navigate = useNavigate()
  const [forecasts, setForecasts] = useState<ForecastResponse[]>([])
  const [servers,   setServers]   = useState<Server[]>([])
  const [loading,   setLoading]   = useState(true)

  async function loadData() {
    setLoading(true)
    try {
      const [fc, sv] = await Promise.all([listForecasts(100), listServers()])
      setForecasts(fc)
      setServers(sv)
    } catch (err) {
      console.error('Forecast load failed', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadData() }, [])

  const byServer = useMemo(() => {
    const map = new Map<string, ForecastResponse[]>()
    for (const f of forecasts) {
      if (!map.has(f.server_id)) map.set(f.server_id, [])
      map.get(f.server_id)!.push(f)
    }
    return map
  }, [forecasts])

  const serverMap = useMemo(() =>
    new Map(servers.map(s => [s.id, s])),
  [servers])

  const serverIds = Array.from(byServer.keys())

  const criticalCount = serverIds.filter(id => serverHealth(byServer.get(id)!) === 'critical').length
  const warningCount  = serverIds.filter(id => serverHealth(byServer.get(id)!) === 'warning').length
  const healthyCount  = serverIds.filter(id => serverHealth(byServer.get(id)!) === 'healthy').length

  const sortedServerIds = useMemo(() =>
    [...serverIds].sort((a, b) => {
      const order: Record<HealthLevel, number> = { critical: 0, warning: 1, healthy: 2, unknown: 3 }
      return (order[serverHealth(byServer.get(a) ?? [])] ?? 3)
           - (order[serverHealth(byServer.get(b) ?? [])] ?? 3)
    }),
  [serverIds, byServer])

  function logout() { clearSession(); navigate('/login') }

  return (
    <>
      {/* ── Navbar ──────────────────────────────────────────────────── */}
      <nav className="navbar">
        <div className="navbar-inner">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Logo variant="dark" size="sm" />
            <div style={{ width: 1, height: 20, background: 'var(--border)', margin: '0 8px' }} />
            <Link to="/"           className="nav-link">Dashboard</Link>
            <Link to="/incidents"  className="nav-link">Incidents</Link>
            <Link to="/runbooks"   className="nav-link">Runbooks</Link>
            <Link to="/forecasts"  className="nav-link nav-link--active">Forecasts</Link>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={loadData} style={{
              background: 'var(--bg)', border: '1px solid var(--border)',
              color: 'var(--text)', padding: '6px 14px', fontSize: 13,
            }}>
              <RefreshCw size={12} style={{ marginRight: 5 }} />Refresh
            </button>
            <button onClick={logout} style={{
              background: 'transparent', color: 'var(--muted)',
              border: '1px solid var(--border)', padding: '6px 14px', fontSize: 13,
            }}>
              Sign out
            </button>
          </div>
        </div>
      </nav>

      <div className="page fade-in">

        {/* ── Page header ──────────────────────────────────────────── */}
        <div style={{ marginBottom: 24 }}>
          <h1 style={{ fontSize: 24, fontWeight: 700, margin: '0 0 5px' }}>
            Server Health Forecasts
          </h1>
          <p style={{ fontSize: 13, color: 'var(--muted)', margin: 0 }}>
            Holt-Winters double exponential smoothing · Next 24 hours ·
            Click a metric row to expand its 24h sparkline
          </p>
        </div>

        {loading ? (
          <div style={{ textAlign: 'center', color: 'var(--muted)', padding: 80, fontSize: 15 }}>
            <Spinner size={28} color="var(--muted)" style={{ marginBottom: 12 }} />
            Loading forecasts…
          </div>

        ) : forecasts.length === 0 ? (
          <div className="card" style={{ textAlign: 'center', padding: 64, color: 'var(--muted)' }}>
            <BarChart size={40} color="var(--muted)" style={{ marginBottom: 14 }} />
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>No forecast data yet</div>
            <div style={{ fontSize: 13, maxWidth: 460, margin: '0 auto', lineHeight: 1.6 }}>
              The forecast engine runs every 30 minutes and needs at least 24 hours of
              metrics stored under the names{' '}
              <code>cpu_percent</code>, <code>memory_percent</code>, or{' '}
              <code>disk_percent</code>.
            </div>
            <div style={{ marginTop: 16, fontSize: 12 }}>
              Seed demo forecasts now:{' '}
              <code>powershell -ExecutionPolicy Bypass -File .\scripts\seed_demo.ps1</code>
            </div>
          </div>

        ) : (
          <>
            {/* ── KPI strip ───────────────────────────────────────── */}
            <div className="grid grid-4" style={{ marginBottom: 28 }}>
              <div className="kpi-card">
                <div className="kpi-value">{serverIds.length}</div>
                <div className="kpi-label">Monitored</div>
                <div className="kpi-sub">servers with active forecasts</div>
              </div>
              <div className="kpi-card kpi-card--danger">
                <div className="kpi-value" style={{ color: criticalCount > 0 ? 'var(--danger)' : 'var(--text)' }}>
                  {criticalCount}
                </div>
                <div className="kpi-label">Critical</div>
                <div className="kpi-sub">breach within 6 hours</div>
              </div>
              <div className="kpi-card kpi-card--warning">
                <div className="kpi-value" style={{ color: warningCount > 0 ? 'var(--warning)' : 'var(--text)' }}>
                  {warningCount}
                </div>
                <div className="kpi-label">At Risk</div>
                <div className="kpi-sub">breach within 24 hours</div>
              </div>
              <div className="kpi-card kpi-card--success">
                <div className="kpi-value" style={{ color: healthyCount > 0 ? 'var(--success)' : 'var(--text)' }}>
                  {healthyCount}
                </div>
                <div className="kpi-label">Healthy</div>
                <div className="kpi-sub">no breach predicted</div>
              </div>
            </div>

            {/* ── Server cards ────────────────────────────────────── */}
            <div className="grid grid-2">
              {sortedServerIds.map(sid => (
                <ServerForecastCard
                  key={sid}
                  server={serverMap.get(sid)}
                  forecasts={byServer.get(sid) ?? []}
                />
              ))}
            </div>

            {/* Legend */}
            <div style={{
              marginTop: 28, padding: '12px 16px',
              background: 'var(--bg-alt)', borderRadius: 8,
              border: '1px solid var(--border)',
              display: 'flex', gap: 24, fontSize: 11, color: 'var(--muted)',
              flexWrap: 'wrap',
            }}>
              <span style={{ fontWeight: 600 }}>Reading this page:</span>
              <span><span style={{ color: 'var(--danger)', fontWeight: 700 }}>CRITICAL</span> — breach predicted in &lt;6h or next-hour &gt;90%</span>
              <span><span style={{ color: 'var(--warning)', fontWeight: 700 }}>AT RISK</span> — breach predicted in 6–24h or next-hour &gt;75%</span>
              <span><span style={{ color: 'var(--success)', fontWeight: 700 }}>HEALTHY</span> — no breach within 24h and next-hour &lt;75%</span>
              <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}><TrendingUp size={12} color="var(--danger)" /> — rising trend (potential concern)</span>
              <span>Click metric row to expand 24h sparkline with confidence band</span>
            </div>
          </>
        )}
      </div>
    </>
  )
}
