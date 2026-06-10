import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { getServerSummary, queryMetrics, listAnomalies, listExplanations, downloadServerReport } from '../api'
import { useWebSocket } from '../useWebSocket'
import { ArrowLeft, Check, Download, Spinner } from '../components/Icons'
import type { Anomaly, Explanation, MetricPoint, ServerSummary, WsEvent } from '../types'

function StatusBadge({ status }: { status: string }) {
  return <span className={`badge badge-${status}`}>{status}</span>
}

function GaugeBar({ label, pct, warn = 75, crit = 90 }: {
  label: string; pct: number; warn?: number; crit?: number
}) {
  const color = pct >= crit ? 'var(--danger)' : pct >= warn ? 'var(--warning)' : 'var(--success)'
  return (
    <div style={{ marginBottom: 10 }}>
      <div className="flex justify-between text-sm" style={{ marginBottom: 5 }}>
        <span className="text-muted">{label}</span>
        <span style={{ fontWeight: 700, color }}>{pct.toFixed(1)}%</span>
      </div>
      <div className="progress-bar">
        <div className="progress-bar__fill" style={{ width: `${Math.min(pct, 100)}%`, background: color }} />
      </div>
    </div>
  )
}

function MetricAreaChart({ title, data, color, gradientId }: {
  title: string; data: MetricPoint[]; color: string; gradientId: string
}) {
  const points = [...data].reverse().map(p => ({
    t: new Date(p.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    v: +((p.avg ?? p.value) * 100).toFixed(2),
  }))

  return (
    <div className="card">
      <div style={{ fontWeight: 700, marginBottom: 14, fontSize: 13, color: 'var(--text)' }}>{title}</div>
      {points.length === 0 ? (
        <div className="text-muted text-sm" style={{ textAlign: 'center', padding: 32 }}>No data</div>
      ) : (
        <ResponsiveContainer width="100%" height={175}>
          <AreaChart data={points} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor={color} stopOpacity={0.18} />
                <stop offset="95%" stopColor={color} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
            <XAxis
              dataKey="t"
              tick={{ fontSize: 10, fill: 'var(--muted)' }}
              tickLine={false}
              axisLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              domain={[0, 100]}
              tick={{ fontSize: 10, fill: 'var(--muted)' }}
              tickLine={false}
              axisLine={false}
              tickFormatter={v => `${v}%`}
            />
            <Tooltip
              contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }}
              formatter={(v: number) => [`${v}%`, title]}
              labelStyle={{ color: 'var(--muted)' }}
            />
            <Area
              type="monotone"
              dataKey="v"
              stroke={color}
              strokeWidth={2}
              fill={`url(#${gradientId})`}
              dot={false}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

const METRIC_CONFIGS = [
  { name: 'system.cpu.utilization',        label: 'CPU Utilization',    color: '#3d2b1f', gradientId: 'grad-cpu'  },
  { name: 'system.memory.utilization',     label: 'Memory Utilization', color: '#d97706', gradientId: 'grad-ram'  },
  { name: 'system.filesystem.utilization', label: 'Disk Utilization',   color: '#16a34a', gradientId: 'grad-disk' },
] as const

export default function ServerDetail() {
  const { id } = useParams<{ id: string }>()
  const [summary, setSummary]           = useState<ServerSummary | null>(null)
  const [metrics, setMetrics]           = useState<Record<string, MetricPoint[]>>({})
  const [anomalies, setAnomalies]       = useState<Anomaly[]>([])
  const [explanations, setExplanations] = useState<Explanation[]>([])
  const [loading, setLoading]           = useState(true)
  const [activeTab, setActiveTab]       = useState<'anomalies' | 'explanations'>('anomalies')
  const [exporting, setExporting]       = useState(false)
  const [countdown, setCountdown]       = useState(20)

  async function loadAll(quiet = false) {
    if (!id) return
    try {
      const [sum, anom, expl] = await Promise.all([
        getServerSummary(id),
        listAnomalies(id, 50),
        listExplanations(id),
      ])
      setSummary(sum)
      setAnomalies(anom)
      setExplanations(expl)

      const fromTime = new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString()
      const metricResults = await Promise.all(
        METRIC_CONFIGS.map(m => queryMetrics(id, m.name, '5m', fromTime).catch(() => []))
      )
      const metricMap: Record<string, MetricPoint[]> = {}
      METRIC_CONFIGS.forEach((m, i) => { metricMap[m.name] = metricResults[i] })
      setMetrics(metricMap)
      if (quiet) setCountdown(20)
    } catch (err) {
      console.error('Load failed', err)
    } finally {
      if (!quiet) setLoading(false)
    }
  }

  // Auto-refresh every 20 s to match agent collection interval
  useEffect(() => {
    loadAll()
    const refreshInterval = setInterval(() => loadAll(true), 20000)
    const tickInterval    = setInterval(() => setCountdown(c => Math.max(0, c - 1)), 1000)
    return () => { clearInterval(refreshInterval); clearInterval(tickInterval) }
  }, [id])

  const handleWsEvent = useCallback((event: WsEvent) => {
    if (!id) return
    const serverId = (event as Record<string, unknown>).server_id as string
    if (serverId !== id) return
    if (event._event === 'anomaly') {
      setAnomalies(prev => [event as unknown as Anomaly, ...prev.slice(0, 49)])
      getServerSummary(id).then(setSummary).catch(() => {})
    } else if (event._event === 'explanation') {
      setExplanations(prev => [event as unknown as Explanation, ...prev.slice(0, 49)])
    }
  }, [id])

  const { connected } = useWebSocket(handleWsEvent)

  if (loading) {
    return (
      <div style={{ textAlign: 'center', color: 'var(--muted)', padding: 80, fontSize: 15 }}>
        <Spinner size={28} color="var(--muted)" style={{ marginBottom: 12 }} />
        Loading server data…
      </div>
    )
  }

  if (!summary) {
    return (
      <div className="page">
        <div className="card text-muted" style={{ textAlign: 'center', padding: 40 }}>Server not found.</div>
      </div>
    )
  }

  const isCritical = summary.status === 'offline'
  const statusColor = isCritical ? 'var(--danger)' : summary.status === 'degraded' ? 'var(--warning)' : 'var(--success)'

  return (
    <div className="page fade-in">
      {/* ── Header ─────────────────────────────────────── */}
      <div style={{ marginBottom: 28 }}>
        <Link to="/" style={{
          display: 'inline-flex', alignItems: 'center', gap: 6,
          fontSize: 13, color: 'var(--muted)', fontWeight: 500, marginBottom: 12,
        }}>
          <ArrowLeft size={13} style={{ marginRight: 4 }} />Dashboard
        </Link>
        <div className="flex justify-between items-center">
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: '-0.02em' }}>{summary.name}</h1>
              <StatusBadge status={summary.status} />
            </div>
            <div className="text-muted text-sm mt-1">{summary.hostname}</div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ fontSize: 11, color: 'var(--muted)', display: 'flex', alignItems: 'center', gap: 5,
              padding: '4px 10px', background: 'var(--bg-alt)', borderRadius: 20, border: '1px solid var(--border-lt)' }}>
              <span className={`live-dot live-dot--${connected ? 'on' : 'off'}`} />
              <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 10 }}>
                {connected ? `live · ${countdown}s` : 'offline'}
              </span>
            </span>
            <button
              onClick={() => loadAll()}
              style={{ background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', padding: '7px 16px' }}
            >
              Refresh
            </button>
            <button
              disabled={exporting}
              onClick={async () => {
                setExporting(true)
                try { await downloadServerReport(id!, summary.name) }
                catch (err) { console.error('Export failed', err) }
                finally { setExporting(false) }
              }}
              style={{
                background: exporting ? 'var(--border)' : 'var(--brand)',
                border: 'none',
                color: '#fff',
                padding: '7px 16px',
                cursor: exporting ? 'not-allowed' : 'pointer',
                opacity: exporting ? 0.7 : 1,
                display: 'flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              {exporting
                ? <><Spinner size={13} style={{ marginRight: 6 }} />Generating…</>
                : <><Download size={13} style={{ marginRight: 6 }} />Export PDF</>}
            </button>
          </div>
        </div>
      </div>

      {/* ── Resources + Anomaly count ────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 280px', gap: 20, marginBottom: 24 }}>
        <div className="card">
          <div className="section-title">Current Resources</div>
          <GaugeBar label="CPU"  pct={summary.cpu_pct}  />
          <GaugeBar label="RAM"  pct={summary.ram_pct}  />
          <GaugeBar label="Disk" pct={summary.disk_pct} />
        </div>
        <div className="card" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', gap: 8 }}>
          <div style={{ fontSize: 52, fontWeight: 700, color: summary.anomaly_count_24h > 5 ? 'var(--danger)' : summary.anomaly_count_24h > 0 ? 'var(--warning)' : 'var(--success)', lineHeight: 1 }}>
            {summary.anomaly_count_24h}
          </div>
          <div style={{ fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--muted)', fontWeight: 600 }}>
            Anomalies (24h)
          </div>
          <div style={{ width: 48, height: 3, background: statusColor, borderRadius: 2, marginTop: 4 }} />
        </div>
      </div>

      {/* ── Metric area charts ───────────────────────── */}
      <div className="section-title">Metrics — Last 3 Hours</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginBottom: 32 }}>
        {METRIC_CONFIGS.map(m => (
          <MetricAreaChart
            key={m.name}
            title={m.label}
            data={metrics[m.name] ?? []}
            color={m.color}
            gradientId={m.gradientId}
          />
        ))}
      </div>

      {/* ── Tabs ────────────────────────────────────── */}
      <div className="tab-bar">
        <button
          className={`tab-btn${activeTab === 'anomalies' ? ' tab-btn--active' : ''}`}
          onClick={() => setActiveTab('anomalies')}
        >
          Anomalies ({anomalies.length})
        </button>
        <button
          className={`tab-btn${activeTab === 'explanations' ? ' tab-btn--active' : ''}`}
          onClick={() => setActiveTab('explanations')}
        >
          AI Explanations ({explanations.length})
        </button>
      </div>

      {/* ── Anomalies tab ───────────────────────────── */}
      {activeTab === 'anomalies' && (
        anomalies.length === 0 ? (
          <div className="card" style={{ padding: 32, textAlign: 'center' }}>
            <Check size={22} color="var(--success)" style={{ marginBottom: 8 }} />
            <div className="text-muted">No anomalies detected for this server.</div>
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
                {anomalies.map(a => (
                  <tr
                    key={a.id}
                    className={`data-table-row--${a.severity === 'critical' ? 'critical' : a.severity === 'warning' ? 'warning' : ''}`}
                  >
                    <td style={{ color: 'var(--muted)', whiteSpace: 'nowrap', fontSize: 12 }}>
                      {new Date(a.time).toLocaleString()}
                    </td>
                    <td style={{ fontFamily: 'monospace', fontSize: 12 }}>
                      {a.metric_name.replace('system.', '')}
                    </td>
                    <td style={{ fontWeight: 600 }}>{(a.value * 100).toFixed(1)}%</td>
                    <td style={{ color: 'var(--muted)', fontSize: 12 }}>
                      {a.threshold != null ? `${(a.threshold * 100).toFixed(1)}%` : '—'}
                    </td>
                    <td style={{ color: 'var(--muted)', fontSize: 12 }}>{a.detector}</td>
                    <td><StatusBadge status={a.severity} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}

      {/* ── Explanations tab ────────────────────────── */}
      {activeTab === 'explanations' && (
        explanations.length === 0 ? (
          <div className="card" style={{ padding: 32, textAlign: 'center' }}>
            <div style={{ color: 'var(--muted)', fontSize: 13 }}>No AI explanations generated yet.</div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {explanations.map(ex => (
              <div key={ex.id} className="card fade-in" style={{ borderLeft: `3px solid ${ex.severity === 'critical' ? 'var(--danger)' : ex.severity === 'warning' ? 'var(--warning)' : 'var(--success)'}` }}>
                <div className="flex justify-between items-center" style={{ marginBottom: 12 }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <StatusBadge status={ex.severity} />
                    <span style={{ fontFamily: 'monospace', fontSize: 12, color: 'var(--muted)' }}>
                      {ex.anomaly_type}
                    </span>
                  </div>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <span className={`badge badge-conf-${ex.confidence}`}>
                      {ex.confidence} confidence
                    </span>
                    <span className="text-muted text-xs">
                      {new Date(ex.created_at).toLocaleString()}
                    </span>
                  </div>
                </div>

                <p style={{ margin: '0 0 14px', fontSize: 13, lineHeight: 1.7, color: 'var(--text)' }}>
                  {ex.explanation}
                </p>

                {ex.root_cause && (
                  <div style={{ marginBottom: 12 }}>
                    <div className="detail-label">Root Cause</div>
                    <div className="detail-box">{ex.root_cause}</div>
                  </div>
                )}

                {ex.recommended_action && (
                  <div style={{ marginBottom: 12 }}>
                    <div className="detail-label">Recommended Action</div>
                    <div className="detail-box" style={{ borderLeft: '3px solid var(--brand)', background: 'var(--brand-pale)' }}>
                      {ex.recommended_action}
                    </div>
                  </div>
                )}

                <div style={{ marginTop: 4, fontSize: 11, color: 'var(--muted)' }}>
                  Model: {ex.model}
                </div>
              </div>
            ))}
          </div>
        )
      )}
    </div>
  )
}
