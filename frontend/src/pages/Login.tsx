import { FormEvent, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiLogin } from '../api'
import { saveSession } from '../auth'
import { AlertTriangle, ArrowRight } from '../components/Icons'
import Logo from '../components/Logo'

export default function Login() {
  const navigate = useNavigate()
  const [email, setEmail]       = useState('admin@caimp.local')
  const [password, setPassword] = useState('')
  const [error, setError]       = useState('')
  const [loading, setLoading]   = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const { access_token, refresh_token } = await apiLogin(email, password)
      saveSession(access_token, refresh_token)
      navigate('/')
    } catch {
      setError('Invalid email or password.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      {/* ── Brand panel ─────────────────────────────────── */}
      <div style={{
        width: '44%',
        background: '#1a3d5c',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '48px 40px',
        position: 'relative',
        overflow: 'hidden',
        flexShrink: 0,
      }}>
        {/* Decorative circles */}
        <div style={{
          position: 'absolute', top: -80, right: -80,
          width: 320, height: 320, borderRadius: '50%',
          background: 'rgba(255,255,255,0.05)',
        }} />
        <div style={{
          position: 'absolute', bottom: -60, left: -60,
          width: 240, height: 240, borderRadius: '50%',
          background: 'rgba(255,255,255,0.05)',
        }} />
        {/* Teal accent circle (from logo) */}
        <div style={{
          position: 'absolute', top: '30%', right: -40,
          width: 160, height: 160, borderRadius: '50%',
          background: 'rgba(46,169,159,0.10)',
        }} />

        {/* Logo — large version */}
        <div style={{ position: 'relative', textAlign: 'center', marginBottom: 36 }}>
          <Logo variant="light" size="lg" />
        </div>

        {/* Divider */}
        <div style={{
          width: 48, height: 2,
          background: 'rgba(46,169,159,0.6)',
          margin: '0 auto 20px',
          borderRadius: 1,
        }} />

        {/* Tagline */}
        <div style={{
          fontSize: 13,
          color: 'rgba(255,255,255,0.55)',
          fontStyle: 'italic',
          marginBottom: 36,
          lineHeight: 1.6,
          textAlign: 'center',
          maxWidth: 280,
        }}>The DevOps engineer your small team doesn't have</div>

        {/* Feature bullets */}
        <div style={{ position: 'relative', display: 'flex', flexDirection: 'column', gap: 18 }}>
          {[
            { text: 'Tells you WHY something broke, not just that it broke' },
            { text: 'Correlates changes to incidents automatically' },
            { text: 'Plain-English answers — no DevOps knowledge needed' },
          ].map(f => (
            <div key={f.text} style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
              <span style={{
                width: 6, height: 6, borderRadius: '50%',
                background: 'rgba(46,169,159,0.8)',
                marginTop: 4, flexShrink: 0,
              }} />
              <span style={{ color: 'rgba(255,255,255,0.75)', fontSize: 13, lineHeight: 1.5 }}>
                {f.text}
              </span>
            </div>
          ))}
        </div>

        <div style={{
          position: 'absolute', bottom: 24,
          fontSize: 11, color: 'rgba(255,255,255,0.25)',
          letterSpacing: '0.05em',
        }}>v2.0 · AI SRE for Small Teams</div>
      </div>

      {/* ── Form panel ──────────────────────────────────── */}
      <div style={{
        flex: 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '48px 40px',
        background: 'var(--bg)',
      }}>
        <div style={{ width: '100%', maxWidth: 380 }}>
          <div style={{ marginBottom: 36 }}>
            <h1 style={{
              fontSize: 26,
              fontWeight: 700,
              color: 'var(--text)',
              letterSpacing: '-0.02em',
              marginBottom: 8,
            }}>Sign in</h1>
            <p style={{ fontSize: 14, color: 'var(--muted)' }}>
              Enter your credentials to access the dashboard.
            </p>
          </div>

          <form onSubmit={onSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
            <div>
              <label style={{
                display: 'block', fontSize: 12, fontWeight: 600,
                color: 'var(--text)', letterSpacing: '0.04em',
                textTransform: 'uppercase', marginBottom: 6,
              }}>Email address</label>
              <input
                type="email" required autoFocus
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="you@domain.com"
              />
            </div>

            <div>
              <label style={{
                display: 'block', fontSize: 12, fontWeight: 600,
                color: 'var(--text)', letterSpacing: '0.04em',
                textTransform: 'uppercase', marginBottom: 6,
              }}>Password</label>
              <input
                type="password" required
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="••••••••"
              />
            </div>

            {error && (
              <div style={{
                background: 'var(--error-banner-bg)',
                border: '1px solid var(--error-banner-border)',
                color: 'var(--danger)',
                padding: '10px 14px',
                borderRadius: 8,
                fontSize: 13,
                display: 'flex',
                alignItems: 'center',
                gap: 8,
              }}>
                <AlertTriangle size={14} color="#b91c1c" />
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              style={{
                background: '#1a3d5c',
                color: '#ffffff',
                padding: '12px 0',
                fontSize: 15,
                fontWeight: 600,
                borderRadius: 10,
                letterSpacing: '0.02em',
                marginTop: 4,
                boxShadow: '0 2px 8px rgba(26,61,92,0.30)',
                transition: 'background 0.15s, transform 0.1s',
              }}
              onMouseEnter={e => { if (!loading) (e.currentTarget.style.background = '#2c5282') }}
              onMouseLeave={e => { (e.currentTarget.style.background = '#1a3d5c') }}
            >
              {loading ? 'Signing in…' : (
                <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
                  Sign in <ArrowRight size={15} />
                </span>
              )}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
