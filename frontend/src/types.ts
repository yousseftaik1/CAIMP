export type ServerStatus = 'online' | 'degraded' | 'offline' | 'pending'

export interface Server {
  id: string
  name: string
  hostname: string
  status: ServerStatus
  agent_version: string | null
  last_heartbeat: string | null
}

export interface ServerSummary {
  id: string
  name: string
  hostname: string
  status: ServerStatus
  cpu_pct: number
  ram_pct: number
  disk_pct: number
  anomaly_count_24h: number
}

export interface MetricPoint {
  time: string
  metric_name: string
  value: number
  avg: number | null
  max: number | null
  min: number | null
}

export interface Anomaly {
  id: string
  time: string
  server_id: string
  metric_name: string
  value: number
  threshold: number | null
  detector: string
  severity: 'warning' | 'critical'
}

export interface Explanation {
  id: string
  server_id: string
  incident_id: string
  anomaly_type: string
  severity: string
  explanation: string
  root_cause: string | null
  recommended_action: string | null
  confidence: 'low' | 'medium' | 'high'
  model: string
  created_at: string
}

export interface WsEvent {
  _event: 'anomaly' | 'explanation'
  [key: string]: unknown
}

// ── Native anomaly incidents ──────────────────────────────────────────────────

export interface AIExplanation {
  id:                 string
  explanation:        string | null
  root_cause:         string | null
  recommended_action: string | null
  confidence:         'low' | 'medium' | 'high' | null
  model:              string | null
  created_at:         string | null
}

export interface IncidentSummary {
  id:          string
  server_id:   string
  server_name: string
  metric_name: string
  value:       number
  threshold:   number | null
  detector:    string
  severity:    'warning' | 'critical'
  time:        string
  ai_status:   'complete' | 'pending' | 'none'
  ai_severity: string | null
}

export interface IncidentDetail {
  id:          string
  server_id:   string
  server_name: string
  metric_name: string
  value:       number
  threshold:   number | null
  detector:    string
  severity:    string
  time:        string
  explanation: AIExplanation | null
}

export interface IncidentStats {
  total:               number
  critical:            number
  warning:             number
  with_ai_explanation: number
  pending_ai:          number
}

// ── Forecasts ─────────────────────────────────────────────────────────────────

export interface ForecastPoint {
  hour:      number
  predicted: number
  lower:     number
  upper:     number
}

export interface ForecastResponse {
  id:                 string
  server_id:          string
  metric_name:        string
  forecasted_at:      string
  horizon_hours:      number
  trend_slope:        number | null
  time_to_critical:   number | null
  critical_threshold: number
  ml_model:           string
  llm_narrative:      string | null
  llm_confidence:     'low' | 'medium' | 'high' | null
  accuracy_score:     number | null
  points:             ForecastPoint[]
}

// ── Dashboard summary (answers-first) ────────────────────────────────────────

export interface ServerHealth {
  id:         string
  name:       string
  hostname:   string
  status:     ServerStatus
  cpu_pct:    number | null
  ram_pct:    number | null
  disk_pct:   number | null
  issues_24h: number
}

export interface PotentialIssue {
  server_id:   string
  server_name: string
  type:        'forecast_risk' | 'anomaly_cluster' | 'root_cause' | 'high_usage'
  title:       string
  detail:      string
  severity:    'critical' | 'warning' | 'info'
}

export interface RecommendedAction {
  priority:    number
  server_name: string
  action:      string
  reason:      string
}

export interface DashboardSummary {
  overall_status:      'healthy' | 'warning' | 'critical'
  overall_message:     string
  server_count:        number
  online_count:        number
  servers:             ServerHealth[]
  potential_issues:    PotentialIssue[]
  recommended_actions: RecommendedAction[]
  generated_at:        string
}

// ── Change events ─────────────────────────────────────────────────────────────

export interface ChangeEvent {
  id:          string
  server_id:   string | null
  occurred_at: string
  change_type: string
  source:      string
  actor:       string | null
  description: string | null
}

// ── Runbooks ──────────────────────────────────────────────────────────────────

export interface RunbookSummary {
  id:            string
  title:         string
  anomaly_type:  string
  created_at:    string
  updated_at:    string
  has_embedding: boolean
}

export interface RunbookDetail {
  id:            string
  title:         string
  anomaly_type:  string
  content:       string
  created_by:    string | null
  created_at:    string
  updated_at:    string
  has_embedding: boolean
}
