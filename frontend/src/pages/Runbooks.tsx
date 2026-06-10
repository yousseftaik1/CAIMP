import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  createRunbook, deleteRunbook, listRunbooks, updateRunbook,
} from '../api'
import { clearSession } from '../auth'
import Logo from '../components/Logo'
import { Close, FileText, Spinner } from '../components/Icons'
import type { RunbookSummary } from '../types'

const ANOMALY_TYPES = [
  'cpu_saturation',
  'memory_pressure',
  'disk_fill',
  'network_anomaly',
  'security_event',
]

const TYPE_LABEL: Record<string, string> = {
  cpu_saturation:  'CPU Saturation',
  memory_pressure: 'Memory Pressure',
  disk_fill:       'Disk Fill',
  network_anomaly: 'Network Anomaly',
  security_event:  'Security Event',
}

const TYPE_COLOR: Record<string, string> = {
  cpu_saturation:  '#dc2626',
  memory_pressure: '#d97706',
  disk_fill:       '#ca8a04',
  network_anomaly: '#2563eb',
  security_event:  '#9333ea',
}

interface FormState {
  title:        string
  anomaly_type: string
  content:      string
}

const EMPTY_FORM: FormState = { title: '', anomaly_type: 'cpu_saturation', content: '' }

const inputStyle: React.CSSProperties = {
  background: 'var(--bg)', border: '1.5px solid var(--border)',
  borderRadius: 8, color: 'var(--text)', padding: '9px 12px',
  fontSize: 13, fontFamily: 'DM Sans, system-ui, sans-serif', width: '100%', outline: 'none',
}

// ── RAG embedding status badge ────────────────────────────────────────────────

function RagBadge({ hasEmbedding }: { hasEmbedding: boolean }) {
  return hasEmbedding ? (
    <span style={{
      fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em',
      color: 'var(--success)', background: '#dcfce7',
      padding: '2px 7px', borderRadius: 8,
      display: 'inline-flex', alignItems: 'center', gap: 4,
    }}>
      <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--success)', display: 'inline-block' }} />
      pgvector
    </span>
  ) : (
    <span style={{
      fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em',
      color: 'var(--warning)', background: '#fef9c3',
      padding: '2px 7px', borderRadius: 8,
      display: 'inline-flex', alignItems: 'center', gap: 4,
    }}>
      <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--warning)', display: 'inline-block' }} />
      no embed
    </span>
  )
}

// ── Single runbook card ───────────────────────────────────────────────────────

interface CardProps {
  runbook:   RunbookSummary
  onEdit:    (id: string) => void
  onDelete:  (id: string) => void
  deleting:  boolean
}

function RunbookCard({ runbook, onEdit, onDelete, deleting }: CardProps) {
  const color = TYPE_COLOR[runbook.anomaly_type] ?? 'var(--muted)'
  return (
    <div className="card" style={{ borderLeft: `3px solid ${color}`, position: 'relative', transition: 'box-shadow 0.15s' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
        <div style={{ flex: 1, minWidth: 0, marginRight: 12 }}>
          <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 6, lineHeight: 1.3 }}>{runbook.title}</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{
              fontSize: 10, fontWeight: 700, color,
              background: `${color}18`, padding: '2px 8px', borderRadius: 10,
              textTransform: 'uppercase', letterSpacing: '0.04em',
            }}>
              {TYPE_LABEL[runbook.anomaly_type] ?? runbook.anomaly_type}
            </span>
            <RagBadge hasEmbedding={runbook.has_embedding} />
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
          <button
            onClick={() => onEdit(runbook.id)}
            style={{ background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', padding: '4px 12px', fontSize: 12, borderRadius: 6 }}
          >
            Edit
          </button>
          <button
            onClick={() => onDelete(runbook.id)}
            disabled={deleting}
            style={{ background: 'transparent', border: '1px solid var(--border)', color: 'var(--danger)', padding: '4px 10px', fontSize: 12, borderRadius: 6 }}
          >
            {deleting ? '…' : 'Delete'}
          </button>
        </div>
      </div>

      {/* RAG pipeline flow indicator */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 8 }}>
        <span style={{ fontSize: 9, color: 'var(--muted)', fontFamily: 'JetBrains Mono, monospace' }}>RAG flow:</span>
        {['Runbook text', 'Ollama embed', 'pgvector store', 'Similarity search', 'LLM context'].map((step, i) => (
          <div key={step} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{
              fontSize: 9, padding: '1px 5px', borderRadius: 4,
              background: runbook.has_embedding || i === 0 ? `${color}12` : 'var(--bg)',
              color: runbook.has_embedding || i === 0 ? color : 'var(--muted)',
              border: `1px solid ${runbook.has_embedding || i === 0 ? color + '30' : 'var(--border)'}`,
              fontFamily: 'JetBrains Mono, monospace',
              opacity: !runbook.has_embedding && i > 0 ? 0.4 : 1,
            }}>
              {step}
            </span>
            {i < 4 && <svg width="6" height="8" viewBox="0 0 6 8" fill="none" style={{ opacity: 0.4, flexShrink: 0 }}><path d="M1 1l4 3-4 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>}
          </div>
        ))}
      </div>

      <div style={{ fontSize: 11, color: 'var(--muted-lt)', fontFamily: 'JetBrains Mono, monospace' }}>
        Updated {new Date(runbook.updated_at).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })}
      </div>
    </div>
  )
}

// ── Runbook form (create or edit) ─────────────────────────────────────────────

interface FormProps {
  initial:    FormState
  onSave:     (data: FormState) => Promise<void>
  onCancel:   () => void
  saving:     boolean
  mode:       'create' | 'edit'
}

function RunbookForm({ initial, onSave, onCancel, saving, mode }: FormProps) {
  const [form, setForm] = useState<FormState>(initial)

  function set(field: keyof FormState, value: string) {
    setForm(prev => ({ ...prev, [field]: value }))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!form.title.trim() || !form.content.trim()) return
    await onSave(form)
  }

  return (
    <form onSubmit={handleSubmit} className="card" style={{ marginBottom: 20, border: '2px solid var(--brand)' }}>
      <div style={{ fontWeight: 800, fontSize: 14, marginBottom: 16, color: 'var(--brand)', fontFamily: 'Syne, sans-serif' }}>
        {mode === 'create' ? '+ New Runbook' : 'Edit Runbook'}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Title *</div>
          <input
            value={form.title}
            onChange={e => set('title', e.target.value)}
            placeholder="e.g. High CPU — runaway process"
            required
            style={inputStyle}
          />
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Anomaly Type *</div>
          <select
            value={form.anomaly_type}
            onChange={e => set('anomaly_type', e.target.value)}
            style={{ ...inputStyle, cursor: 'pointer' }}
          >
            {ANOMALY_TYPES.map(t => (
              <option key={t} value={t}>{TYPE_LABEL[t] ?? t}</option>
            ))}
          </select>
        </div>
      </div>

      <div style={{ marginBottom: 14 }}>
        <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Content * <span style={{ fontWeight: 400, textTransform: 'none' }}>(diagnosis steps, commands, expected outcome)</span>
        </div>
        <textarea
          value={form.content}
          onChange={e => set('content', e.target.value)}
          placeholder={"1. Check top processes: ssh user@host 'ps aux --sort=-%cpu | head -20'\n2. Look for recent deployments…"}
          required
          rows={10}
          style={{ ...inputStyle, resize: 'vertical', lineHeight: 1.6, fontFamily: 'JetBrains Mono, monospace', fontSize: 12 }}
        />
      </div>

      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <button
          type="submit"
          disabled={saving || !form.title.trim() || !form.content.trim()}
          style={{ background: 'var(--brand)', color: '#fff', padding: '9px 24px', borderRadius: 'var(--radius)', fontWeight: 600 }}
        >
          {saving ? 'Saving…' : mode === 'create' ? 'Create Runbook' : 'Save Changes'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          style={{ background: 'transparent', border: '1px solid var(--border)', color: 'var(--muted)', padding: '9px 18px', borderRadius: 'var(--radius)' }}
        >
          Cancel
        </button>
        {mode === 'create' && (
          <span style={{ fontSize: 11, color: 'var(--muted)', marginLeft: 4 }}>
            Ollama will generate a pgvector embedding automatically.
          </span>
        )}
      </div>
    </form>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Runbooks() {
  const navigate = useNavigate()

  const [runbooks,     setRunbooks]     = useState<RunbookSummary[]>([])
  const [filterType,   setFilterType]   = useState('')
  const [loading,      setLoading]      = useState(true)
  const [error,        setError]        = useState('')

  const [showCreate,   setShowCreate]   = useState(false)
  const [editingId,    setEditingId]    = useState<string | null>(null)
  const [editForm,     setEditForm]     = useState<FormState>(EMPTY_FORM)
  const [saving,       setSaving]       = useState(false)

  const [deletingId,   setDeletingId]   = useState<string | null>(null)

  async function load() {
    setLoading(true)
    setError('')
    try {
      const data = await listRunbooks(filterType || undefined)
      setRunbooks(data)
    } catch (err) {
      setError(String(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  async function handleCreate(form: FormState) {
    setSaving(true)
    try {
      await createRunbook(form)
      setShowCreate(false)
      await load()
    } catch (err) {
      setError(String(err))
    } finally {
      setSaving(false)
    }
  }

  function startEdit(id: string) {
    const rb = runbooks.find(r => r.id === id)
    if (!rb) return
    setEditForm({ title: rb.title, anomaly_type: rb.anomaly_type, content: '' })
    setEditingId(id)
    setShowCreate(false)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  async function handleEdit(form: FormState) {
    if (!editingId) return
    setSaving(true)
    try {
      await updateRunbook(editingId, form)
      setEditingId(null)
      await load()
    } catch (err) {
      setError(String(err))
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(id: string) {
    if (!window.confirm('Delete this runbook? This cannot be undone.')) return
    setDeletingId(id)
    try {
      await deleteRunbook(id)
      setRunbooks(prev => prev.filter(r => r.id !== id))
    } catch (err) {
      setError(String(err))
    } finally {
      setDeletingId(null)
    }
  }

  function logout() { clearSession(); navigate('/login') }

  const filtered = filterType
    ? runbooks.filter(r => r.anomaly_type === filterType)
    : runbooks

  const grouped: Record<string, RunbookSummary[]> = {}
  for (const rb of filtered) {
    if (!grouped[rb.anomaly_type]) grouped[rb.anomaly_type] = []
    grouped[rb.anomaly_type].push(rb)
  }

  const ragIndexed    = runbooks.filter(r => r.has_embedding).length
  const missingEmbeds = runbooks.filter(r => !r.has_embedding).length

  return (
    <>
      {/* ── Navbar ─────────────────────────────────────────────────────── */}
      <nav className="navbar">
        <div className="navbar-inner">
          <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
            <Logo variant="dark" size="sm" />
            <Link to="/"           className="nav-link">Dashboard</Link>
            <Link to="/incidents"  className="nav-link">Incidents</Link>
            <Link to="/runbooks"   className="nav-link nav-link--active">Runbooks</Link>
            <Link to="/forecasts"  className="nav-link">Forecasts</Link>
          </div>
          <button
            onClick={logout}
            style={{ background: 'transparent', color: 'var(--muted)', border: '1px solid var(--border)', padding: '6px 14px', borderRadius: 'var(--radius)', fontSize: 13 }}
          >
            Sign out
          </button>
        </div>
      </nav>

      <div className="page fade-in">

        {/* ── Header + actions ─────────────────────────────────────────── */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 800, marginBottom: 4, fontFamily: 'Syne, sans-serif' }}>Runbooks</h1>
            <div style={{ fontSize: 13, color: 'var(--muted)' }}>
              Operator-written diagnosis guides — vectorised and retrieved by the AI pipeline
            </div>
          </div>
          <button
            onClick={() => { setShowCreate(true); setEditingId(null) }}
            style={{ background: 'var(--brand)', color: '#fff', padding: '9px 20px', fontWeight: 600, borderRadius: 'var(--radius)', flexShrink: 0 }}
          >
            + New Runbook
          </button>
        </div>

        {/* ── RAG pipeline context bar ──────────────────────────────────── */}
        <div style={{
          background: 'var(--surface)', border: '1px solid var(--border)',
          borderRadius: 10, padding: '10px 16px', marginBottom: 20,
          display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap',
        }}>
          <span style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--muted)', flexShrink: 0 }}>
            RAG Pipeline
          </span>
          {[
            { label: 'Runbook text', color: 'var(--pipe-ingest)' },
            { label: 'Ollama /embed', color: 'var(--pipe-llm)' },
            { label: 'pgvector store', color: 'var(--pipe-db)' },
            { label: 'Cosine similarity', color: 'var(--pipe-db)' },
            { label: 'Inject into LLM ctx', color: 'var(--pipe-ai)' },
          ].map((step, i) => (
            <div key={step.label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{
                fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 8,
                background: `${step.color}12`, border: `1px solid ${step.color}30`,
                color: step.color, textTransform: 'uppercase', letterSpacing: '0.04em',
                whiteSpace: 'nowrap',
              }}>
                {step.label}
              </span>
              {i < 4 && <span style={{ color: 'var(--muted)', display: 'flex', alignItems: 'center' }}><svg width="8" height="10" viewBox="0 0 8 10" fill="none"><path d="M1 5h6M4 2l3 3-3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg></span>}
            </div>
          ))}
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 12, flexShrink: 0 }}>
            <span style={{ fontSize: 11, color: 'var(--success)', fontFamily: 'JetBrains Mono, monospace', fontWeight: 600 }}>
              {ragIndexed} indexed
            </span>
            {missingEmbeds > 0 && (
              <span style={{ fontSize: 11, color: 'var(--warning)', fontFamily: 'JetBrains Mono, monospace', fontWeight: 600 }}>
                {missingEmbeds} missing embed
              </span>
            )}
          </div>
        </div>

        {/* ── Stats strip ──────────────────────────────────────────────── */}
        <div className="grid grid-4" style={{ marginBottom: 24 }}>
          <div className="kpi-card">
            <div className="kpi-value">{runbooks.length}</div>
            <div className="kpi-label">Total Runbooks</div>
          </div>
          <div className="kpi-card kpi-card--success">
            <div className="kpi-value" style={{ color: 'var(--success)' }}>
              {ragIndexed}
            </div>
            <div className="kpi-label">RAG-Indexed</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-value">
              {new Set(runbooks.map(r => r.anomaly_type)).size}
            </div>
            <div className="kpi-label">Types Covered</div>
          </div>
          <div className="kpi-card kpi-card--warning">
            <div className="kpi-value" style={{ color: missingEmbeds > 0 ? 'var(--warning)' : 'var(--text)' }}>
              {missingEmbeds}
            </div>
            <div className="kpi-label">Missing Embedding</div>
          </div>
        </div>

        {/* ── Create / Edit form ────────────────────────────────────────── */}
        {showCreate && (
          <RunbookForm
            initial={EMPTY_FORM}
            onSave={handleCreate}
            onCancel={() => setShowCreate(false)}
            saving={saving}
            mode="create"
          />
        )}
        {editingId && (
          <RunbookForm
            initial={editForm}
            onSave={handleEdit}
            onCancel={() => setEditingId(null)}
            saving={saving}
            mode="edit"
          />
        )}

        {/* ── Filter bar ────────────────────────────────────────────────── */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 20, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontSize: 11, color: 'var(--muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Filter:</span>
          <button
            onClick={() => setFilterType('')}
            style={{
              background: !filterType ? 'var(--brand)' : 'var(--bg)',
              color: !filterType ? '#fff' : 'var(--text)',
              border: `1px solid ${!filterType ? 'var(--brand)' : 'var(--border)'}`,
              borderRadius: 20, padding: '4px 14px', fontSize: 12,
            }}
          >
            All ({runbooks.length})
          </button>
          {ANOMALY_TYPES.map(t => {
            const count = runbooks.filter(r => r.anomaly_type === t).length
            if (count === 0) return null
            return (
              <button
                key={t}
                onClick={() => setFilterType(t)}
                style={{
                  background: filterType === t ? TYPE_COLOR[t] : 'var(--bg)',
                  color: filterType === t ? '#fff' : 'var(--text)',
                  border: `1px solid ${filterType === t ? TYPE_COLOR[t] : 'var(--border)'}`,
                  borderRadius: 20, padding: '4px 14px', fontSize: 12,
                }}
              >
                {TYPE_LABEL[t]} ({count})
              </button>
            )
          })}
        </div>

        {/* ── Error ─────────────────────────────────────────────────────── */}
        {error && (
          <div style={{ background: 'var(--error-banner-bg)', border: '1px solid var(--error-banner-border)', borderRadius: 8, padding: '12px 16px', color: 'var(--danger)', marginBottom: 16, fontSize: 13 }}>
            {error}
            <button onClick={() => setError('')} style={{ marginLeft: 12, background: 'transparent', color: 'var(--danger)', border: 'none', padding: 0, cursor: 'pointer', display: 'inline-flex' }}><Close size={14} /></button>
          </div>
        )}

        {/* ── List ─────────────────────────────────────────────────────── */}
        {loading ? (
          <div style={{ textAlign: 'center', color: 'var(--muted)', padding: 60, fontSize: 14 }}>
            <Spinner size={28} color="var(--muted)" style={{ marginBottom: 10 }} />
            Loading runbooks…
          </div>
        ) : filtered.length === 0 ? (
          <div className="card" style={{ textAlign: 'center', padding: 52 }}>
            <FileText size={32} color="var(--muted)" style={{ marginBottom: 12 }} />
            <div style={{ fontWeight: 700, marginBottom: 6, fontFamily: 'Syne, sans-serif' }}>No runbooks yet</div>
            <div style={{ color: 'var(--muted)', fontSize: 13, marginBottom: 18, lineHeight: 1.6 }}>
              Create a runbook to give the AI pipeline context for diagnosing incidents.<br />
              <span style={{ fontSize: 11 }}>Runbooks are vectorised by Ollama and stored in pgvector for RAG retrieval.</span>
            </div>
            <button
              onClick={() => setShowCreate(true)}
              style={{ background: 'var(--brand)', color: '#fff', padding: '9px 20px', borderRadius: 'var(--radius)', fontWeight: 600 }}
            >
              + Create First Runbook
            </button>
          </div>
        ) : filterType ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {filtered.map(rb => (
              <RunbookCard
                key={rb.id}
                runbook={rb}
                onEdit={startEdit}
                onDelete={handleDelete}
                deleting={deletingId === rb.id}
              />
            ))}
          </div>
        ) : (
          Object.entries(grouped).map(([type, items]) => (
            <div key={type} style={{ marginBottom: 28 }}>
              <div style={{
                fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
                letterSpacing: '0.06em', color: TYPE_COLOR[type] ?? 'var(--muted)',
                marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8,
              }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: TYPE_COLOR[type] ?? 'var(--muted)', display: 'inline-block' }} />
                {TYPE_LABEL[type] ?? type}
                <span style={{ fontWeight: 400, color: 'var(--muted)' }}>({items.length})</span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {items.map(rb => (
                  <RunbookCard
                    key={rb.id}
                    runbook={rb}
                    onEdit={startEdit}
                    onDelete={handleDelete}
                    deleting={deletingId === rb.id}
                  />
                ))}
              </div>
            </div>
          ))
        )}
      </div>
    </>
  )
}
