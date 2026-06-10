/**
 * PipelineFlow — visualises the CAIMP backend data pipeline as a horizontal
 * node graph with live status indicators.
 *
 * Data flow: Agents → Telemetry Writer → NATS → AI Worker + Forecast Engine
 *            → PostgreSQL → Query API → Frontend (WebSocket for live updates)
 */

import { useEffect, useState } from 'react'
import { getToken } from '../auth'

interface SvcStatus {
  key:    string
  label:  string
  port:   string
  color:  string
  emoji:  string
  desc:   string
  online: boolean | null
}

const INITIAL_SERVICES: SvcStatus[] = [
  { key: 'query-api', label: 'Query API',      port: ':8002', color: 'var(--pipe-db)',   emoji: '🗄',  desc: 'Data queries',    online: null },
  { key: 'ai-orch',   label: 'AI Orchestrator',port: ':8010', color: 'var(--pipe-ai)',   emoji: '🧠',  desc: 'Chat + LLM',      online: null },
  { key: 'ws',        label: 'WS Gateway',     port: ':8080', color: 'var(--pipe-ws)',   emoji: '⚡',  desc: 'Live push events',online: null },
]

async function checkHealth(path: string): Promise<boolean> {
  try {
    const res = await fetch(path, {
      headers: { Authorization: `Bearer ${getToken() ?? ''}` },
      signal: AbortSignal.timeout(3000),
    })
    return res.ok
  } catch { return false }
}

const PIPELINE_NODES = [
  { key: 'agent',    label: 'Agents',       port: 'OTLP',   color: 'var(--pipe-agent)',  emoji: '📡', desc: 'System metrics every 15s' },
  { key: 'tw',       label: 'Telemetry',    port: ':4318',  color: 'var(--pipe-ingest)', emoji: '📥', desc: 'OTLP ingestion + anomaly detection' },
  { key: 'ct',       label: 'Changes',      port: ':8011',  color: 'var(--pipe-ingest)', emoji: '🔔', desc: 'Docker/package/SSH events' },
  { key: 'nats',     label: 'NATS',         port: ':4222',  color: 'var(--pipe-nats)',   emoji: '📬', desc: 'JetStream event bus' },
  { key: 'aiw',      label: 'AI Worker',    port: ':9092',  color: 'var(--pipe-ai)',     emoji: '🤖', desc: 'RAG + LLM explanations' },
  { key: 'corr',     label: 'Correlation',  port: ':9095',  color: 'var(--pipe-ai)',     emoji: '🔗', desc: 'Change→anomaly correlation' },
  { key: 'forecast', label: 'Forecast',     port: ':9094',  color: 'var(--pipe-llm)',    emoji: '📈', desc: 'Holt-Winters 24h predictions' },
  { key: 'postgres', label: 'Postgres',     port: ':5432',  color: 'var(--pipe-db)',     emoji: '🐘', desc: 'TimescaleDB + pgvector' },
  { key: 'ws',       label: 'WS Gateway',   port: ':8080',  color: 'var(--pipe-ws)',     emoji: '🔌', desc: 'Live push to browser' },
  { key: 'ui',       label: 'Frontend',     port: ':3000',  color: 'var(--pipe-ui)',     emoji: '🖥',  desc: 'React SPA' },
]

export default function PipelineFlow({ wsConnected }: { wsConnected: boolean }) {
  const [services, setServices] = useState<SvcStatus[]>(INITIAL_SERVICES)

  useEffect(() => {
    async function probe() {
      const checks = await Promise.allSettled([
        checkHealth('/api/v1/health'),
        checkHealth('/api/ai/health'),
        checkHealth('/ws/health'),
      ])
      setServices(prev => prev.map((s, i) => ({
        ...s,
        online: checks[i].status === 'fulfilled'
          ? (checks[i] as PromiseFulfilledResult<boolean>).value
          : false,
      })))
    }
    probe()
    const t = setInterval(probe, 30_000)
    return () => clearInterval(t)
  }, [])

  return (
    <div className="card" style={{ padding: '16px 20px 14px', marginBottom: 28, overflow: 'hidden' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
        <div className="section-title" style={{ marginBottom: 0 }}>Backend Pipeline</div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          {services.map(svc => (
            <div key={svc.key} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11 }}>
              <span className={`live-dot ${
                svc.online === null ? 'live-dot--warn' : svc.online ? 'live-dot--on' : 'live-dot--off'
              }`} />
              <span style={{ color: 'var(--muted)', fontFamily: 'JetBrains Mono, monospace', fontSize: 10 }}>
                {svc.label}
              </span>
            </div>
          ))}
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11 }}>
            <span className={`live-dot ${wsConnected ? 'live-dot--on' : 'live-dot--off'}`} />
            <span style={{ color: 'var(--muted)', fontFamily: 'JetBrains Mono, monospace', fontSize: 10 }}>
              WebSocket
            </span>
          </div>
        </div>
      </div>

      {/* Flow nodes */}
      <div style={{ overflowX: 'auto', paddingBottom: 4 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 0, minWidth: 'max-content' }}>
          {PIPELINE_NODES.map((node, i) => (
            <div key={node.key} style={{ display: 'flex', alignItems: 'center' }}>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 5, width: 74 }}>
                <div style={{
                  width: 40, height: 40, borderRadius: 10,
                  background: `${node.color}18`, border: `1.5px solid ${node.color}40`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 17, position: 'relative', cursor: 'default', transition: 'transform 0.15s',
                }}
                onMouseEnter={e => (e.currentTarget.style.transform = 'scale(1.1)')}
                onMouseLeave={e => (e.currentTarget.style.transform = 'scale(1)')}
                title={`${node.label} — ${node.desc}`}>
                  {node.emoji}
                  {node.key === 'ws' && (
                    <span style={{
                      position: 'absolute', top: -3, right: -3,
                      width: 8, height: 8, borderRadius: '50%',
                      background: wsConnected ? 'var(--success)' : 'var(--muted)',
                      border: '1.5px solid var(--surface)',
                    }} />
                  )}
                </div>
                <div style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase',
                  letterSpacing: '0.05em', color: 'var(--muted)', textAlign: 'center', lineHeight: 1.2 }}>
                  {node.label}
                </div>
                <div style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 8, color: `${node.color}cc` }}>
                  {node.port}
                </div>
              </div>
              {i < PIPELINE_NODES.length - 1 && (
                <div style={{ display: 'flex', alignItems: 'center', marginTop: -20, padding: '0 2px' }}>
                  <svg width="20" height="10" viewBox="0 0 20 10" fill="none">
                    <line x1="0" y1="5" x2="14" y2="5" stroke="var(--border)" strokeWidth="1.5"/>
                    <polyline points="11,2 16,5 11,8" fill="none" stroke="var(--border)" strokeWidth="1.5" strokeLinejoin="round"/>
                  </svg>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Legend */}
      <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--border-lt)',
        display: 'flex', gap: 20, flexWrap: 'wrap' }}>
        {[
          { color: 'var(--pipe-ingest)', label: 'Metrics path: Agents → Telemetry Writer → TimescaleDB' },
          { color: 'var(--pipe-ai)',     label: 'AI path: NATS → AI Worker → Ollama LLM → PostgreSQL' },
          { color: 'var(--pipe-nats)',   label: 'Event bus: NATS JetStream → WS Gateway → React UI' },
        ].map(leg => (
          <div key={leg.label} style={{ display: 'flex', alignItems: 'center', gap: 6,
            fontSize: 10.5, color: 'var(--muted)' }}>
            <span style={{ width: 24, height: 2, background: leg.color, borderRadius: 2, flexShrink: 0 }} />
            {leg.label}
          </div>
        ))}
      </div>
    </div>
  )
}
