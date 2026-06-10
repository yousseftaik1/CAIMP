import { clearSession, getToken, saveSession } from './auth'
import type {
  Anomaly, DashboardSummary, Explanation, ForecastResponse,
  IncidentDetail, IncidentStats, IncidentSummary, MetricPoint,
  RunbookDetail, RunbookSummary, Server, ServerSummary,
} from './types'

function authHeaders(): HeadersInit {
  return { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` }
}

let _refreshing: Promise<boolean> | null = null

async function tryRefresh(): Promise<boolean> {
  if (_refreshing) return _refreshing
  _refreshing = (async () => {
    const rt = localStorage.getItem('caimp_refresh_token')
    if (!rt) return false
    try {
      const res = await fetch('/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: rt }),
      })
      if (!res.ok) return false
      const data = await res.json()
      saveSession(data.access_token, data.refresh_token ?? rt)
      return true
    } catch {
      return false
    } finally {
      _refreshing = null
    }
  })()
  return _refreshing
}

async function get<T>(path: string): Promise<T> {
  let res = await fetch(path, { headers: authHeaders() })
  if (res.status === 401) {
    const ok = await tryRefresh()
    if (ok) {
      res = await fetch(path, { headers: authHeaders() })
    } else {
      clearSession()
      window.location.href = '/login'
      throw new Error('Unauthorized')
    }
  }
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

// ── Auth ──────────────────────────────────────────────────────────────────────
export async function apiLogin(email: string, password: string) {
  const res = await fetch('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!res.ok) throw new Error('Invalid credentials')
  return res.json() as Promise<{ access_token: string; refresh_token: string }>
}

// ── Dashboard ─────────────────────────────────────────────────────────────────
export const getDashboardSummary = () => get<DashboardSummary>('/api/v1/dashboard/summary')

// ── Servers ───────────────────────────────────────────────────────────────────
export const listServers     = () => get<Server[]>('/api/v1/servers')
export const getServerSummary = (id: string) => get<ServerSummary>(`/api/v1/servers/${id}/summary`)

// ── Metrics ───────────────────────────────────────────────────────────────────
export function queryMetrics(
  serverId: string,
  metricName: string,
  interval = '5m',
  fromTime?: string,
): Promise<MetricPoint[]> {
  const params = new URLSearchParams({
    server_id: serverId, metric_name: metricName, interval, agg: 'avg',
    ...(fromTime ? { from_time: fromTime } : {}),
  })
  return get<MetricPoint[]>(`/api/v1/metrics?${params}`)
}

// ── Anomalies ─────────────────────────────────────────────────────────────────
export function listAnomalies(serverId?: string, limit = 50): Promise<Anomaly[]> {
  const params = new URLSearchParams({ limit: String(limit) })
  if (serverId) params.set('server_id', serverId)
  return get<Anomaly[]>(`/api/v1/anomalies?${params}`)
}

// ── AI Explanations ───────────────────────────────────────────────────────────
export function listExplanations(serverId?: string): Promise<Explanation[]> {
  const params = new URLSearchParams()
  if (serverId) params.set('server_id', serverId)
  return get<Explanation[]>(`/api/v1/ai/explanations?${params}`)
}

// ── Incidents (native anomaly incidents with AI analysis) ─────────────────────
export function listIncidents(params: {
  server_id?: string; severity?: string;
  from_time?: string; to_time?: string; limit?: number
} = {}): Promise<IncidentSummary[]> {
  const p = new URLSearchParams()
  if (params.server_id)  p.set('server_id',  params.server_id)
  if (params.severity)   p.set('severity',   params.severity)
  if (params.from_time)  p.set('from_time',  params.from_time)
  if (params.to_time)    p.set('to_time',    params.to_time)
  if (params.limit)      p.set('limit',      String(params.limit))
  return get<IncidentSummary[]>(`/api/v1/incidents?${p}`)
}

export const getIncident      = (id: string) => get<IncidentDetail>(`/api/v1/incidents/${id}`)
export const getIncidentStats = ()            => get<IncidentStats>(`/api/v1/incidents/stats`)

export async function submitFeedback(incidentId: string, rating: -1 | 0 | 1): Promise<void> {
  const res = await fetch(`/api/v1/incidents/${incidentId}/feedback`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ rating }),
  })
  if (res.status === 401) { window.location.href = '/login'; return }
  if (!res.ok) throw new Error(`Feedback failed: ${res.status}`)
}

// ── Runbooks ──────────────────────────────────────────────────────────────────
export function listRunbooks(anomaly_type?: string): Promise<RunbookSummary[]> {
  const p = new URLSearchParams()
  if (anomaly_type) p.set('anomaly_type', anomaly_type)
  return get<RunbookSummary[]>(`/api/v1/runbooks?${p}`)
}
export const getRunbook = (id: string) => get<RunbookDetail>(`/api/v1/runbooks/${id}`)

export async function createRunbook(data: {
  title: string; anomaly_type: string; content: string
}): Promise<RunbookDetail> {
  const res = await fetch('/api/v1/runbooks', {
    method: 'POST', headers: authHeaders(), body: JSON.stringify(data),
  })
  if (res.status === 401) { window.location.href = '/login'; throw new Error('Unauthorized') }
  if (!res.ok) throw new Error(`Create failed: ${res.status}`)
  return res.json()
}

export async function updateRunbook(id: string, data: {
  title?: string; anomaly_type?: string; content?: string
}): Promise<RunbookDetail> {
  const res = await fetch(`/api/v1/runbooks/${id}`, {
    method: 'PUT', headers: authHeaders(), body: JSON.stringify(data),
  })
  if (res.status === 401) { window.location.href = '/login'; throw new Error('Unauthorized') }
  if (!res.ok) throw new Error(`Update failed: ${res.status}`)
  return res.json()
}

export async function deleteRunbook(id: string): Promise<void> {
  const res = await fetch(`/api/v1/runbooks/${id}`, {
    method: 'DELETE', headers: authHeaders(),
  })
  if (res.status === 401) { window.location.href = '/login'; return }
  if (!res.ok) throw new Error(`Delete failed: ${res.status}`)
}

// ── Forecasts ─────────────────────────────────────────────────────────────────
export function listForecasts(limit = 100, serverId?: string): Promise<ForecastResponse[]> {
  const p = new URLSearchParams({ limit: String(limit) })
  if (serverId) p.set('server_id', serverId)
  return get<ForecastResponse[]>(`/api/v1/forecasts?${p}`)
}

// ── PDF Report ────────────────────────────────────────────────────────────────
export async function downloadServerReport(serverId: string, serverName: string): Promise<void> {
  const res = await fetch(`/api/v1/reports/pdf?server_id=${encodeURIComponent(serverId)}`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  })
  if (res.status === 401) { window.location.href = '/login'; return }
  if (!res.ok) throw new Error(`Report failed: ${res.status}`)
  const blob = await res.blob()
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href = url
  a.download = `caimp-report-${serverName.replace(/\s+/g, '-')}.pdf`
  document.body.appendChild(a); a.click()
  document.body.removeChild(a); URL.revokeObjectURL(url)
}
