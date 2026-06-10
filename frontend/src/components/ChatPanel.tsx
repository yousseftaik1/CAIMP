import { useEffect, useRef, useState, type ReactNode } from 'react'
import { getOrgId, getToken } from '../auth'
import {
  AlertTriangle, ArrowUp, Bot, BookOpen, Close, MessageCircle, Monitor, Search, Spinner,
} from './Icons'

interface Message {
  role:      'user' | 'assistant'
  content:   string
  intent?:   string
  streaming?: boolean
}

const INTENT_META: Record<string, { label: string; color: string; desc: string; icon: ReactNode }> = {
  host_query:    { label: 'Host query',    color: '#2563eb', desc: 'Recent incidents + AI explanations for this host',  icon: <Monitor size={13} color="#2563eb" /> },
  anomaly_query: { label: 'Anomaly',       color: '#dc2626', desc: 'Stored AI explanation for this incident',            icon: <AlertTriangle size={13} color="#dc2626" /> },
  runbook_query: { label: 'Runbook',       color: '#16a34a', desc: 'Runbook lookup from org knowledge base',            icon: <BookOpen size={13} color="#16a34a" /> },
  general:       { label: 'General',       color: '#6b7280', desc: 'Plain LLM answer — no DB context',                  icon: <MessageCircle size={13} color="#6b7280" /> },
}

const PROMPTS = [
  { text: 'What\'s happening on web-01?',           intent: 'host_query' },
  { text: 'How do I fix high memory usage?',        intent: 'runbook_query' },
  { text: 'Explain the last critical alert',        intent: 'anomaly_query' },
]

export default function ChatPanel() {
  const [open,     setOpen]     = useState(false)
  const [input,    setInput]    = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [busy,     setBusy]     = useState(false)
  const bottomRef  = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    if (open) textareaRef.current?.focus()
  }, [open])

  async function send(text?: string) {
    const msg = (text ?? input).trim()
    if (!msg || busy) return

    const history = messages.map(m => ({ role: m.role, content: m.content }))
    setMessages(prev => [
      ...prev,
      { role: 'user', content: msg },
      { role: 'assistant', content: '', streaming: true },
    ])
    setInput('')
    setBusy(true)

    let intent      = ''
    let accumulated = ''

    try {
      const res = await fetch('/api/ai/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${getToken()}`,
        },
        body: JSON.stringify({
          message:              msg,
          org_id:               getOrgId(),
          conversation_history: history,
        }),
      })

      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)

      const reader  = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })

        const parts = buf.split('\n\n')
        buf = parts.pop() ?? ''

        for (const part of parts) {
          for (const line of part.split('\n')) {
            if (!line.startsWith('data: ')) continue
            try {
              const evt = JSON.parse(line.slice(6))
              if (evt.type === 'token') {
                accumulated += evt.content
                setMessages(prev => {
                  const next = [...prev]
                  next[next.length - 1] = { ...next[next.length - 1], content: accumulated }
                  return next
                })
              } else if (evt.type === 'intent') {
                intent = evt.intent
                // Update the in-progress message with the intent immediately
                setMessages(prev => {
                  const next = [...prev]
                  next[next.length - 1] = { ...next[next.length - 1], intent }
                  return next
                })
              }
            } catch { /* partial JSON */ }
          }
        }
      }
    } catch (err) {
      accumulated = `Error: ${String(err)}`
    }

    setMessages(prev => {
      const next = [...prev]
      next[next.length - 1] = {
        role: 'assistant', content: accumulated || '(no response)',
        intent, streaming: false,
      }
      return next
    })
    setBusy(false)
  }

  function handleKey(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
  }

  const intentMeta = (intent?: string) => intent ? (INTENT_META[intent] ?? INTENT_META['general']) : null

  return (
    <>
      {/* ── Floating toggle ──────────────────────────────────────────── */}
      <button
        onClick={() => setOpen(o => !o)}
        title="CAIMP AI NOC Assistant"
        style={{
          position: 'fixed', bottom: 24, right: 24, zIndex: 1000,
          width: 50, height: 50, borderRadius: '50%',
          background: 'var(--brand)', color: '#fff',
          boxShadow: '0 4px 18px rgba(61,43,31,0.35)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 20, border: '2px solid rgba(255,255,255,0.15)',
          transition: 'transform 0.15s, box-shadow 0.15s',
        }}
        onMouseEnter={e => { e.currentTarget.style.transform = 'scale(1.1)'; e.currentTarget.style.boxShadow = '0 6px 24px rgba(61,43,31,0.45)' }}
        onMouseLeave={e => { e.currentTarget.style.transform = 'scale(1)';   e.currentTarget.style.boxShadow = '0 4px 18px rgba(61,43,31,0.35)' }}
      >
        {open ? <Close size={18} color="#fff" /> : <Bot size={22} color="#fff" />}
      </button>

      {/* ── Chat panel ───────────────────────────────────────────────── */}
      {open && (
        <div style={{
          position: 'fixed', bottom: 84, right: 24, zIndex: 999,
          width: 400, height: 560,
          background: 'var(--surface)', border: '1px solid var(--border)',
          borderRadius: 16, boxShadow: '0 12px 40px rgba(0,0,0,0.16)',
          display: 'flex', flexDirection: 'column', overflow: 'hidden',
          animation: 'fadeIn 0.18s ease',
        }}>

          {/* Header */}
          <div style={{
            padding: '11px 16px', borderBottom: '1px solid var(--border)',
            display: 'flex', alignItems: 'center', gap: 10,
            background: 'var(--brand)',
          }}>
            <Bot size={18} color="#fff" />
            <div>
              <div style={{ fontWeight: 800, fontSize: 13, color: '#fff', fontFamily: 'Syne, sans-serif', letterSpacing: '0.01em' }}>
                CAIMP AI Assistant
              </div>
              <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.55)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                NOC · ai-orchestrator :8010 · SSE streaming
              </div>
            </div>
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 10, alignItems: 'center' }}>
              {Object.entries(INTENT_META).map(([key, meta]) => (
                <div key={key} title={`${meta.label}: ${meta.desc}`}
                  style={{ fontSize: 10, cursor: 'default', opacity: 0.7 }}>
                  {meta.icon}
                </div>
              ))}
            </div>
          </div>

          {/* Intent legend */}
          <div style={{
            padding: '6px 12px', borderBottom: '1px solid var(--border-lt)',
            display: 'flex', gap: 6, flexWrap: 'wrap', background: 'var(--bg)',
          }}>
            {Object.entries(INTENT_META).map(([key, meta]) => (
              <span key={key} style={{
                fontSize: 9, padding: '2px 7px', borderRadius: 8,
                background: `${meta.color}15`, color: meta.color,
                fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em',
                cursor: 'default',
              }} title={meta.desc}>
                {meta.label}
              </span>
            ))}
          </div>

          {/* Messages */}
          <div style={{ flex: 1, overflowY: 'auto', padding: '12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
            {messages.length === 0 && (
              <div style={{ marginTop: 16 }}>
                <div style={{ color: 'var(--muted)', fontSize: 12, textAlign: 'center', marginBottom: 16, lineHeight: 1.6 }}>
                  Ask me about your infrastructure.<br />
                  <span style={{ fontSize: 10, color: 'var(--muted-lt)' }}>
                    I route to the right backend context automatically.
                  </span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {PROMPTS.map((p, i) => {
                    const meta = INTENT_META[p.intent]
                    return (
                      <button
                        key={i}
                        onClick={() => send(p.text)}
                        style={{
                          background: 'var(--bg)', border: '1px solid var(--border)',
                          borderRadius: 8, padding: '7px 12px',
                          textAlign: 'left', fontSize: 12, color: 'var(--text)',
                          display: 'flex', alignItems: 'center', gap: 8,
                          transition: 'all 0.12s',
                        }}
                        onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-alt)'; e.currentTarget.style.borderColor = 'var(--brand)' }}
                        onMouseLeave={e => { e.currentTarget.style.background = 'var(--bg)'; e.currentTarget.style.borderColor = 'var(--border)' }}
                      >
                        <span style={{ fontSize: 13 }}>{meta.icon}</span>
                        <span style={{ flex: 1, lineHeight: 1.3 }}>{p.text}</span>
                        <span style={{
                          fontSize: 9, padding: '1px 6px', borderRadius: 6,
                          background: `${meta.color}15`, color: meta.color,
                          fontWeight: 700, textTransform: 'uppercase', flexShrink: 0,
                        }}>
                          {meta.label}
                        </span>
                      </button>
                    )
                  })}
                </div>
              </div>
            )}

            {messages.map((m, i) => {
              const meta = m.intent ? intentMeta(m.intent) : null
              return (
                <div key={i} style={{ display: 'flex', justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
                  <div style={{
                    maxWidth: '92%',
                    background: m.role === 'user' ? 'var(--brand)' : 'var(--bg)',
                    color: m.role === 'user' ? '#fff' : 'var(--text)',
                    borderRadius: m.role === 'user' ? '14px 14px 4px 14px' : '4px 14px 14px 14px',
                    padding: '9px 12px',
                    fontSize: 12.5,
                    lineHeight: 1.6,
                    border: m.role === 'assistant' ? '1px solid var(--border)' : 'none',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                    boxShadow: m.role === 'user' ? 'none' : 'var(--shadow)',
                  }}>
                    {/* Intent badge — shown as soon as intent is known */}
                    {m.role === 'assistant' && meta && (
                      <div style={{ marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ fontSize: 11 }}>{meta.icon}</span>
                        <span style={{
                          fontSize: 9, fontWeight: 700,
                          color: meta.color,
                          background: `${meta.color}18`,
                          padding: '1px 7px', borderRadius: 8,
                          textTransform: 'uppercase', letterSpacing: '0.06em',
                        }}>
                          {meta.label}
                        </span>
                        {m.streaming && (
                          <span style={{ fontSize: 9, color: 'var(--muted-lt)' }}>streaming…</span>
                        )}
                      </div>
                    )}
                    {m.content}
                    {m.streaming && !m.content && (
                      <span style={{ color: 'var(--muted)' }}>thinking…</span>
                    )}
                    {m.streaming && (
                      <span style={{
                        display: 'inline-block', width: 7, height: 13,
                        background: m.role === 'user' ? '#fff' : 'var(--brand)',
                        borderRadius: 2, marginLeft: 2, verticalAlign: 'middle',
                        animation: 'blink 0.7s step-end infinite',
                        opacity: 0.7,
                      }} />
                    )}
                  </div>
                </div>
              )
            })}
            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <div style={{ padding: '10px 12px', borderTop: '1px solid var(--border)', display: 'flex', gap: 8, alignItems: 'flex-end' }}>
            <textarea
              ref={textareaRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKey}
              placeholder="Ask about servers, incidents, anomalies, runbooks…"
              disabled={busy}
              rows={2}
              style={{
                flex: 1, resize: 'none', border: '1.5px solid var(--border)',
                borderRadius: 8, padding: '8px 10px', fontSize: 12.5,
                fontFamily: 'DM Sans, system-ui, sans-serif',
                background: 'var(--bg)', color: 'var(--text)',
                outline: 'none', lineHeight: 1.4,
                transition: 'border-color 0.15s',
              }}
              onFocus={e => (e.target.style.borderColor = 'var(--brand)')}
              onBlur={e  => (e.target.style.borderColor = 'var(--border)')}
            />
            <button
              onClick={() => send()}
              disabled={busy || !input.trim()}
              style={{
                background: busy || !input.trim() ? 'var(--border)' : 'var(--brand)',
                color: '#fff', borderRadius: 8,
                padding: '0 14px', fontSize: 16,
                alignSelf: 'stretch', minWidth: 42,
                transition: 'background 0.15s',
              }}
            >
              {busy ? <Spinner size={16} color="#fff" /> : <ArrowUp size={16} color="#fff" />}
            </button>
          </div>
        </div>
      )}

      <style>{`@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }`}</style>
    </>
  )
}
