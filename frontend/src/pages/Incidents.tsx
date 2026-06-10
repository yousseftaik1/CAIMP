import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { getIncident, getIncidentStats, listIncidents, submitFeedback } from '../api'
import { clearSession } from '../auth'
import { useWebSocket } from '../useWebSocket'
import Logo from '../components/Logo'
import {
  AlertTriangle, Check, ChevronDown, ChevronRight,
  RefreshCw, Spinner, ThumbsDown, ThumbsUp,
} from '../components/Icons'
import type { IncidentDetail, IncidentStats, IncidentSummary, WsEvent } from '../types'

function SevBadge({ sev }: { sev: string }) {
  const c = sev === 'critical' ? 'var(--danger)' : 'var(--warning)'
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
      letterSpacing: '0.06em', background: `${c}18`,
      color: c, borderRadius: 6, padding: '2px 8px',
    }}>{sev}</span>
  )
}

function AIBadge({ status }: { status: string }) {
  if (status === 'complete') return (
    <span style={{ fontSize: 10, color: 'var(--success)', fontWeight: 600,
      display: 'flex', alignItems: 'center', gap: 3 }}>
      <Check size={10} />AI ready
    </span>
  )
  if (status === 'pending') return (
    <span style={{ fontSize: 10, color: 'var(--warning)', fontWeight: 600,
      display: 'flex', alignItems: 'center', gap: 3 }}>
      <Spinner size={10} />Analysing
    </span>
  )
  return <span style={{ fontSize: 10, color: 'var(--muted)' }}>—</span>
}

function ExplanationCard({ incidentId }: { incidentId: string }) {
  const [detail,   setDetail]   = useState<IncidentDetail | null>(null)
  const [loading,  setLoading]  = useState(true)
  const [feedback, setFeedback] = useState<-1 | 1 | null>(null)
  const [fbDone,   setFbDone]   = useState(false)

  useEffect(() => {
    getIncident(incidentId).then(setDetail).catch(console.error).finally(() => setLoading(false))
  }, [incidentId])

  async function rate(r: -1 | 1) {
    if (fbDone) return
    setFeedback(r)
    try { await submitFeedback(incidentId, r); setFbDone(true) } catch {}
  }

  if (loading) return (
    <div style={{ padding: '16px 20px', display: 'flex', gap: 8, color: 'var(--muted)', fontSize: 13 }}>
      <Spinner size={14} color="var(--muted)" /> Loading AI analysis…
    </div>
  )
  if (!detail?.explanation) return (
    <div style={{ padding: '16px 20px', fontSize: 13, color: 'var(--muted)' }}>
      {detail
        ? <><AlertTriangle size={13} style={{ marginRight: 6 }} />AI analysis is still processing.</>
        : 'Could not load incident details.'}
    </div>
  )
  const ax = detail.explanation
  return (
    <div style={{ padding: '16px 20px', borderTop: '1px solid var(--border-lt)', fontSize: 13 }}>
      {ax.explanation && (
        <p style={{ marginBottom: 14, lineHeight: 1.7, color: 'var(--text)' }}>{ax.explanation}</p>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 14 }}>
        {ax.root_cause && (
          <div style={{ background: 'var(--bg)', border: '1px solid var(--border)',
            borderLeft: '3px solid var(--warning)', borderRadius: 8, padding: '10px 14px' }}>
            <div style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
              letterSpacing: '0.07em', color: 'var(--warning)', marginBottom: 5 }}>Why it happened</div>
            <div style={{ color: 'var(--text)', fontSize: 12.5, lineHeight: 1.55 }}>{ax.root_cause}</div>
          </div>
        )}
        {ax.recommended_action && (
          <div style={{ background: 'var(--brand-pale)', border: '1px solid var(--border)',
            borderLeft: '3px solid var(--brand)', borderRadius: 8, padding: '10px 14px' }}>
            <div style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
              letterSpacing: '0.07em', color: 'var(--brand)', marginBottom: 5 }}>What to do</div>
            <div style={{ color: 'var(--text)', fontSize: 12.5, lineHeight: 1.55 }}>{ax.recommended_action}</div>
          </div>
        )}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10,
        borderTop: '1px solid var(--border-lt)', paddingTop: 10 }}>
        {ax.confidence && (
          <span style={{ fontSize: 11, color: 'var(--muted)' }}>
            Confidence: <strong>{ax.confidence}</strong>
          </span>
        )}
        {ax.model && (
          <span style={{ fontSize: 10, color: 'var(--muted)', fontFamily: 'JetBrains Mono, monospace',
            background: 'var(--bg-alt)', padding: '2px 7px', borderRadius: 6,
            border: '1px solid var(--border-lt)' }}>{ax.model}</span>
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 11, color: 'var(--muted)' }}>Helpful?</span>
          {fbDone ? (
            <span style={{ fontSize: 11, color: 'var(--success)', display: 'flex',
              alignItems: 'center', gap: 3 }}><Check size={12} />Thanks</span>
          ) : (
            <>
              <button onClick={() => rate(1)} style={{
                background: feedback === 1 ? 'var(--success)' : 'var(--bg)',
                color: feedback === 1 ? '#fff' : 'var(--muted)',
                border: '1px solid var(--border)', borderRadius: 6, padding: '4px 10px',
              }}><ThumbsUp size={13} /></button>
              <button onClick={() => rate(-1)} style={{
                background: feedback === -1 ? 'var(--danger)' : 'var(--bg)',
                color: feedback === -1 ? '#fff' : 'var(--muted)',
                border: '1px solid var(--border)', borderRadius: 6, padding: '4px 10px',
              }}><ThumbsDown size={13} /></button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

export default function Incidents() {
  const navigate = useNavigate()
  const [incidents,  setIncidents]  = useState<IncidentSummary[]>([])
  const [stats,      setStats]      = useState<IncidentStats | null>(null)
  const [loading,    setLoading]    = useState(true)
  const [expanded,   setExpanded]   = useState<string | null>(null)
  const [severityF,  setSeverityF]  = useState('')
  const [refreshing, setRefreshing] = useState(false)

  async function load(quiet = false) {
    if (!quiet) setLoading(true); else setRefreshing(true)
    try {
      const [inc, st] = await Promise.all([
        listIncidents({ severity: severityF || undefined, limit: 100 }),
        getIncidentStats(),
      ])
      setIncidents(inc); setStats(st)
    } catch (e) { console.error(e) }
    finally { setLoading(false); setRefreshing(false) }
  }

  useEffect(() => { load() }, [severityF])

  const handleWs = useCallback((e: WsEvent) => {
    if (e._event === 'anomaly' || e._event === 'explanation') setTimeout(() => load(true), 1500)
  }, [severityF])
  const { connected } = useWebSocket(handleWs)

  return (
    <>
      <nav className="navbar">
        <div className="navbar-inner">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Logo variant="dark" size="sm" />
            <div style={{ width: 1, height: 20, background: 'var(--border)', margin: '0 8px' }} />
            <Link to="/"          className="nav-link">Dashboard</Link>
            <Link to="/metrics"   className="nav-link">Metrics</Link>
            <Link to="/incidents" className="nav-link nav-link--active">Incidents</Link>
            <Link to="/runbooks"  className="nav-link">Runbooks</Link>
            <Link to="/forecasts" className="nav-link">Forecasts</Link>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 11, color: 'var(--muted)', display: 'flex',
              alignItems: 'center', gap: 5, padding: '4px 10px',
              background: 'var(--bg-alt)', borderRadius: 20, border: '1px solid var(--border-lt)' }}>
              <span className={`live-dot live-dot--${connected ? 'on' : 'off'}`} />
              <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 10 }}>
                {connected ? 'live' : 'offline'}
              </span>
            </span>
            <button onClick={() => load(true)} disabled={refreshing}
              style={{ background: 'var(--bg)', border: '1px solid var(--border)',
                color: 'var(--text)', padding: '6px 14px', fontSize: 13 }}>
              {refreshing ? <Spinner size={13} /> : <><RefreshCw size={13} style={{ marginRight: 4 }} />Refresh</>}
            </button>
            <button onClick={() => { clearSession(); navigate('/login') }}
              style={{ background: 'transparent', color: 'var(--muted)',
                border: '1px solid var(--border)', padding: '6px 14px', fontSize: 13 }}>
              Sign out
            </button>
          </div>
        </div>
      </nav>

      <div className="page fade-in">
        <div className="grid grid-5" style={{ marginBottom: 24 }}>
          {[
            { label: 'Total (24h)',  value: stats?.total ?? '—',               color: 'var(--text)' },
            { label: 'Critical',     value: stats?.critical ?? '—',            color: 'var(--danger)' },
            { label: 'Warning',      value: stats?.warning ?? '—',             color: 'var(--warning)' },
            { label: 'AI Explained', value: stats?.with_ai_explanation ?? '—', color: 'var(--success)' },
            { label: 'Pending AI',   value: stats?.pending_ai ?? '—',          color: 'var(--muted)' },
          ].map(k => (
            <div key={k.label} className="kpi-card">
              <div className="kpi-value" style={{ color: k.color, fontSize: 26 }}>{k.value}</div>
              <div className="kpi-label">{k.label}</div>
            </div>
          ))}
        </div>

        <div style={{ display: 'flex', gap: 8, marginBottom: 18, alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 600 }}>Severity:</span>
          {(['', 'critical', 'warning'] as const).map(s => (
            <button key={s} onClick={() => setSeverityF(s)} style={{
              padding: '5px 14px', fontSize: 12, borderRadius: 20,
              background: severityF === s ? 'var(--brand)' : 'var(--bg-alt)',
              color:      severityF === s ? '#fff'         : 'var(--muted)',
              border: `1px solid ${severityF === s ? 'var(--brand)' : 'var(--border)'}`,
            }}>{s === '' ? 'All' : s.charAt(0).toUpperCase() + s.slice(1)}</button>
          ))}
          <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--muted)' }}>
            {incidents.length} incident{incidents.length !== 1 ? 's' : ''}
          </span>
        </div>

        {loading ? (
          <div style={{ textAlign: 'center', padding: 60, color: 'var(--muted)' }}>
            <Spinner size={26} color="var(--muted)" style={{ marginBottom: 10 }} /><div>Loading…</div>
          </div>
        ) : incidents.length === 0 ? (
          <div className="card" style={{ textAlign: 'center', padding: '48px 0', fontWeight: 600,
            fontSize: 14, display: 'flex', alignItems: 'center', justifyContent: 'center',
            gap: 8, color: 'var(--success)' }}>
            <Check size={20} />No incidents in the last 24 hours
          </div>
        ) : (
          <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
            <div style={{
              display: 'grid', gridTemplateColumns: '36px 1fr 130px 80px 100px 90px 80px',
              padding: '8px 16px', background: 'var(--bg-alt)',
              borderBottom: '1px solid var(--border)',
              fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
              letterSpacing: '0.07em', color: 'var(--muted)',
            }}>
              <span /><span>Server / Metric</span><span>Time</span>
              <span>Value</span><span>Detector</span><span>Severity</span><span>AI</span>
            </div>
            {incidents.map(inc => (
              <div key={inc.id} style={{ borderBottom: '1px solid var(--border-lt)' }}>
                <div onClick={() => setExpanded(e => e === inc.id ? null : inc.id)}
                  style={{
                    display: 'grid', gridTemplateColumns: '36px 1fr 130px 80px 100px 90px 80px',
                    padding: '10px 16px', alignItems: 'center', cursor: 'pointer',
                    background: expanded === inc.id ? 'var(--brand-pale)' : 'var(--surface)',
                    transition: 'background 0.1s',
                  }}>
                  <span style={{ color: 'var(--muted)' }}>
                    {expanded === inc.id ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  </span>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 13 }}>{inc.server_name}</div>
                    <div style={{ fontSize: 11, color: 'var(--muted)',
                      fontFamily: 'JetBrains Mono, monospace' }}>{inc.metric_name}</div>
                  </div>
                  <span style={{ fontSize: 11, color: 'var(--muted)',
                    fontFamily: 'JetBrains Mono, monospace' }}>
                    {new Date(inc.time).toLocaleString([], {
                      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
                    })}
                  </span>
                  <span style={{ fontFamily: 'JetBrains Mono, monospace',
                    fontSize: 12, fontWeight: 600 }}>{inc.value.toFixed(1)}%</span>
                  <span style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'capitalize' }}>
                    {inc.detector.replace(/_/g, ' ')}
                  </span>
                  <SevBadge sev={inc.severity} />
                  <AIBadge status={inc.ai_status} />
                </div>
                {expanded === inc.id && <ExplanationCard incidentId={inc.id} />}
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  )
}
