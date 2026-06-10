# CAIMP Documentation

**CAIMP** — Cloud AI Monitoring Platform  
Multi-tenant server monitoring system with real-time metrics, anomaly detection, AI-powered explanations, predictive forecasting, and PDF reporting.

---

## Stack Overview

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + Vite, TypeScript, Recharts |
| Backend APIs | Python 3.12, FastAPI, asyncpg |
| Database | PostgreSQL 16 + TimescaleDB + pgvector |
| Cache | Redis 7.2 |
| Message Bus | NATS JetStream |
| LLM | Ollama (local) |
| Telemetry | OpenTelemetry Collector |
| Metrics | Prometheus + Grafana |
| Auth | JWT (HS256), bcrypt passwords |

---

## Local Services

| URL | Service | Function |
|-----|---------|----------|
| `http://localhost:3000` | Frontend (Nginx) | Main web UI — dashboard, server monitoring, export PDF |
| `http://localhost:3001` | Grafana | Metrics dashboards and visualization |
| `http://localhost:8001` | Admin API | User/org management, auth (`/auth/login`), agent enrollment |
| `http://localhost:8002` | Query API | Data queries — metrics, anomalies, forecasts, PDF reports |
| `http://localhost:8080` | WS Gateway | WebSocket server — live anomaly/event push to the frontend |
| `http://localhost:9090` | Prometheus | Metrics scraping and storage for service health |
| `http://localhost:4222` | NATS | Message broker — event bus between all backend services |
| `http://localhost:8222` | NATS Monitor | NATS web monitoring UI (streams, consumers, message rates) |
| `http://localhost:11434` | Ollama | Local LLM server — serves the AI model for anomaly explanations and forecast narratives |
| `http://localhost:8010` | AI Orchestrator | Receives Splunk anomaly webhooks; builds context → RAG → LLM → stores explanations; `POST /chat` SSE chat |
| `http://localhost:4317` | Splunk HEC Bridge | Receives OTLP from agents, translates to Splunk HEC format, writes live metrics to Redis |
| `http://localhost:4318` | OTel Collector (HTTP) | OTel Collector HTTP — disabled by default; enable with `--profile otel` |
| `http://localhost:8888` | OTel Collector metrics | OTel Collector Prometheus metrics — disabled by default; enable with `--profile otel` |
| `http://localhost:5432` | PostgreSQL | Main database — all persistent data (metrics, anomalies, forecasts, users) |
| `http://localhost:6379` | Redis | Cache layer — server summaries, dedup keys for forecast engine |
| `http://localhost:9091` | Telemetry Writer metrics | Prometheus metrics for the telemetry ingestion service |
| `http://localhost:9092` | AI Worker metrics | Prometheus metrics for the AI explanation worker |
| `http://localhost:9093` | Alert Engine metrics | Prometheus metrics for the alerting service |
| `http://localhost:9094` | Forecast Engine metrics | Prometheus metrics for the forecast/prediction service |

---

## Database

**Connection:**
```
Host:     localhost
Port:     5432
Database: caimp
User:     caimp
Password: caimp
```

**Seed credentials:**
```
Email:    admin@caimp.local
Password: Admin1234!
```

**Tables:**

| Table | Purpose |
|-------|---------|
| `organizations` | Multi-tenant orgs |
| `users` | User accounts with bcrypt passwords |
| `servers` | Registered monitored servers; optional `splunk_host` override for Splunk hostname mapping |
| `metrics` | TimescaleDB hypertable — raw metric points |
| `anomaly_events` | Detected anomalies with severity |
| `ai_explanations` | LLM-generated explanations for anomalies |
| `server_forecasts` | Holt-Winters predictions + LLM narratives |
| `rag_documents` | pgvector embeddings for RAG context |
| `alert_rules` | Configurable alerting thresholds |
| `notifications` | Alert notification log |
| `agent_certs` | TLS certs for monitoring agents |
| `enrollment_tokens` | One-time agent enrollment tokens |
| `audit_log` | Admin action audit trail |
| `refresh_token_blacklist` | Revoked JWT refresh tokens |
| `splunk_incidents` | Anomaly events received from Splunk webhooks |
| `splunk_ai_explanations` | LLM-generated root-cause explanations (pending→complete/error) |
| `ai_feedback` | Operator thumbs-up/down ratings on AI explanations |
| `org_config` | Per-org cloud LLM opt-in, Anthropic API key, Splunk credentials |
| `runbooks` | Operator-written diagnosis guides with pgvector embeddings |

**Migrations:** managed by `golang-migrate`, files in `infra/postgres/migrations/`. Current version: **15**.

---

## Architecture — Data Flow

```
Agent / OTel SDK
      |
      v
OTel Collector (4317/4318)
      |
      v
Telemetry Writer  ──────────────────> PostgreSQL (metrics, servers)
      |
      v
    NATS JetStream
    /      |      \
   /       |       \
AI Worker  Alert    Forecast Engine
(explanations) (alerts)  (Holt-Winters)
   \       |       /
    \      |      /
      PostgreSQL
          |
      Query API (8002)
          |
      Frontend (3000) <── WebSocket (8080)
```

---

## Services

### Frontend (`services/frontend` / `frontend/`)
React SPA served by Nginx. Proxies all API calls:
- `/auth/` → Admin API
- `/api/v1/` → Query API
- `/ws/` → WS Gateway

**Key pages:**
- `/login` — Login screen
- `/` — Dashboard: KPI cards, server grid, anomaly table
- `/servers/:id` — Server detail: gauges, metric charts, anomalies, AI explanations, **Splunk AI tab** (24h incident KPIs + Splunk-sourced incident table with AI status)
- `/incidents` — Splunk incidents table: KPI cards, filters, expandable rows with AI explanations + feedback
- `/runbooks` — Runbook management: create/edit/delete runbooks, filter by anomaly type, RAG embedding badge

### Admin API (`services/api-admin`, port 8001)
Handles auth and administration. Key routes:
- `POST /auth/login` — returns JWT access + refresh tokens
- `POST /auth/refresh` — refresh access token
- User and org CRUD

### Query API (`services/api-query`, port 8002)
Read-only data API for the frontend. Key routes:
- `GET /servers` — list all servers
- `GET /servers/:id/summary` — live CPU/RAM/disk + anomaly count (cached 30s)
- `GET /servers/:id/splunk` — Splunk AI health: 24h incident counts, critical count, last AI explanation status, 10 most recent Splunk incidents with AI summary (cached 60s)
- `GET /metrics` — time-series metric query
- `GET /anomalies` — anomaly event list
- `GET /ai/explanations` — LLM explanation list
- `GET /forecasts` — latest Holt-Winters predictions per server/metric
- `GET /reports/pdf` — generate and download a full PDF intelligence report

### Forecast Engine (`services/forecast-engine`)
Background worker. Runs two loops:
- **Forecast loop** (every 30 min): fetches last 6h of metrics, runs Holt-Winters double exponential smoothing, generates LLM narrative via Ollama, saves to `server_forecasts`, publishes `ForecastCritical` NATS event if `time_to_critical <= 6h`.
- **Evaluate loop** (every 60 min): scores past forecasts against actual values, stores `actual_mae` + `accuracy_score` back to DB for learning feedback.

### AI Worker (`services/ai-worker`, port 9092)
Listens on NATS for anomaly events, calls Ollama for root-cause explanation + recommended action, saves to `ai_explanations`.

### Alert Engine (`services/alert-engine`, port 9093)
Evaluates metric streams against `alert_rules`, publishes alerts to NATS.

### WS Gateway (`services/ws-gateway`, port 8080)
Subscribes to NATS anomaly and explanation events, pushes them to connected browser clients over WebSocket.

### Telemetry Writer (`services/telemetry-writer`, port 9091)
Receives metrics from OTel Collector via OTLP, writes to TimescaleDB.

---

## PDF Report

**Endpoint:** `GET /api/v1/reports/pdf`

**Query params:**
| Param | Type | Description |
|-------|------|-------------|
| `server_id` | UUID (optional) | Filter report to a single server |
| `from_time` | ISO datetime (optional) | Report window start |
| `to_time` | ISO datetime (optional) | Report window end |

**Sections:** Cover page, Executive Summary KPIs, Server Health table, Predictive Forecasts + AI Narratives, Anomaly Log, AI Insights cards.

**Frontend:** Each server card on the Dashboard has a "↓ PDF" button. The Server Detail page has an "↓ Export PDF" button in the header.

**Branding:** The cover page and per-page header render a faithful replica of the Logo.tsx SVG icon — network nodes (teal highlight on the top-left node, navy/white for others) plus the ECG heartbeat polyline — matching the exact node positions and line weights from the component. The "CAIMP" wordmark is followed by "Infrastructure Monitor" in muted white (`rgba(255,255,255,0.55)`), matching the Logo.tsx light-variant subtitle color. Brand colors: navy `#1a3d5c`, teal `#2ea99f`.

---

## Forecasting

Algorithm: **Holt-Winters double exponential smoothing** (pure NumPy, no external ML library).

| Parameter | Value |
|-----------|-------|
| Level smoothing (α) | 0.3 |
| Trend smoothing (β) | 0.1 |
| Confidence intervals | ±1.28σ (~80% coverage) |
| Horizon | 24 hours |
| Confidence rating | `high` if n≥48, `medium` if n≥24, else `low` |
| Critical threshold | 0.9 (90%) |

Accuracy feedback: after each 24h horizon elapses, MAE is computed against actual values and stored. The LLM prompt for the next forecast includes past accuracy so narratives are calibrated to model confidence.

---

## Changelog

### 2026-06-10 (Report — added demo metrics, VM monitoring, and dashboard access sections to LaTeX chapters)

**Files changed:** `report/en/chapters/08_deployment.tex`, `report/fr/chapters/08_deploiement.tex`

Added three new sections to both the English and French deployment chapters:
- **Generating Demo Metrics**: step-by-step instructions to run `demo_agent.py` with `pip install psutil requests`, plus three-terminal simulation with `CAIMP_CPU=99` / `CAIMP_RAM=97` overrides for triggering critical alerts; full env-var override table.
- **Monitoring a Real Virtual Machine**: 4-step workflow — generate enrollment token via Admin API (`POST /api/v1/admin/servers/enroll`), `scp` agent to target, run `install.sh --token <token> --url http://<host>`, verify with `systemctl status caimp-agent`.
- **Accessing the Admin and Monitoring Dashboards**: table of all web UIs (`http://localhost` for CAIMP, `http://localhost:3001` for Grafana), how to substitute a server IP for remote access, default credentials, and development vs. production guidance.

### 2026-06-10 (Bug fix — chatbot "TypeError: network error" on slow CPU inference)

**Root cause:** Ollama on CPU-only hardware takes 90-130+ seconds per generate request (ai-worker and ai-orchestrator compete for the same Ollama instance). During the wait, no data flows from ai-orchestrator → nginx → browser. Nginx eventually closes the connection, causing `fetch()` to throw `TypeError: network error` in the browser.

**Fix — SSE keep-alive heartbeat (`services/ai-orchestrator/main.py`):**
- The `event_stream()` generator now runs `stream_ollama` in a background asyncio task and reads tokens from a queue via `asyncio.wait_for(..., timeout=5.0)`.
- If no token arrives within 5 seconds, it yields `: keep-alive\n\n` (an SSE comment, ignored by browsers) which resets nginx's `proxy_read_timeout` timer.
- This keeps the connection alive across the full 2-3 minute Ollama inference time. Once tokens start arriving they stream normally.
- No change to the SSE event protocol — the frontend receives the same `intent`, `token`, and `done` events.

### 2026-06-10 (Bug fixes — WebSocket token expiry + container healthchecks)

**WebSocket re-authentication**
- `frontend/src/useWebSocket.ts`: Moved `getToken()` call inside `connect()` so each WebSocket reconnect reads the latest JWT from `localStorage`. Previously the token was captured once at mount time; after the 15-minute JWT TTL, every reconnect used the expired token and got a permanent 403 Forbidden, showing "offline" in the live badge forever. Now: when the HTTP API auto-refreshes the token (via `/auth/refresh`), the next 3-second WebSocket reconnect picks up the fresh token and reconnects automatically.

**Container healthchecks**
- `docker-compose.yml` (frontend): Changed `wget http://localhost:3000` → `wget http://127.0.0.1:3000/health`. The Alpine nginx container did not resolve `localhost` to `127.0.0.1` on the loopback, causing the healthcheck to fail with "Connection refused" since container start (583 consecutive failures) despite nginx serving pages correctly. Using the explicit IP + `/health` endpoint fixes it.
- `docker-compose.yml` (ws-gateway): Changed healthcheck from `wget` → `python3 -c "import urllib.request; urllib.request.urlopen(...)"`. The ws-gateway Python image does not include `wget`; using Python's built-in `urllib.request` avoids the dependency. ws-gateway had been marked "unhealthy" since start despite working correctly.

### 2026-06-09 (Demo agent — local metrics injection for immediate dashboard data)
- Created `services\agent\demo_agent.py` — zero-install demo agent that reads real CPU/RAM/disk from the host machine via `psutil` and POSTs to the telemetry-writer's `/v1/metrics/raw` endpoint every 20 seconds.
- Uses seed identities by default: org `00000000-0000-0000-0000-000000000001`, server `demo-server-01` (`00000000-0000-0000-0000-000000000011`).
- Configurable via env vars: `CAIMP_TW_URL`, `CAIMP_ORG_ID`, `CAIMP_SERVER_ID`, `CAIMP_SERVER_NAME`, `CAIMP_INTERVAL`.
- Install deps and run: `pip install psutil requests && python services/agent/demo_agent.py`
- Root cause for "No metrics" on all server cards: servers in DB are just records — no running agent means no data in the `metrics` TimescaleDB table. This script is the fastest way to populate it locally.

### 2026-06-09 (Frontend — live 20-second auto-refresh on all metric pages)
- `frontend/src/pages/MetricsDashboard.tsx`: Added 20-second `setInterval` auto-refresh (quiet, no spinner). Navbar live indicator now shows countdown: `live · refresh in Ns`.
- `frontend/src/pages/Dashboard.tsx`: Same 20-second auto-refresh. Navbar shows `live · Ns`.
- `frontend/src/pages/ServerDetail.tsx`: Same 20-second auto-refresh for summary gauges, anomaly list, and metric charts. Header live indicator shows countdown.
- All pages use a 1-second tick to decrement the countdown and reset it to 20 on each successful refresh.

### 2026-06-09 (Bug fixes — real metrics pipeline + AI explanation flow)

**Agent**
- `services/agent/caimp_agent/config.py`: Changed default `CAIMP_INTERVAL` from `30` → `20` seconds so metrics are sent every 20 s

**Telemetry Writer (Go)**
- `services/telemetry-writer/internal/detector/detector.go`: Fixed threshold detector — OTel utilization values are 0–1 fractions but thresholds were 0–100 percentages; added `valuePct := p.Value * 100` before comparison. Also added `filesystem` to disk metric name matching.
- `services/telemetry-writer/internal/writer/anomaly_store.go` *(new)*: Added `PersistAnomalies()` that INSERTs detected anomaly events into `anomaly_events` table with `incident_id`; telemetry writer was previously only publishing to NATS without writing to the DB.
- `services/telemetry-writer/cmd/main.go`: Called `writer.PersistAnomalies()` in the anomaly detection goroutine before publishing to NATS.

**Database**
- `infra/postgres/migrations/000015_fix_anomaly_pipeline.up.sql` *(new)*:
  - Added `incident_id TEXT` column to `anomaly_events` so the AI worker's compound key can be stored and used for JOIN
  - Fixed `detector` CHECK constraint to include `'threshold'` (Go emits this; DB only allowed `'static'`)
  - Fixed `ai_explanations.severity` CHECK to include `'warning'` (Go emits `'warning'`; DB only allowed `'low'/'medium'/'high'/'critical'`)

**Query API**
- `services/api-query/query_api/routers/incidents.py`: Fixed broken JOIN — changed `ax.incident_id = ae.id::text` → `ax.incident_id = ae.incident_id`; `ae.id` is a UUID primary key while `ax.incident_id` stores the compound string from the NATS event, so the old join never matched, causing AI explanations to never appear on incidents.
- `services/api-query/query_api/routers/dashboard.py`: Fixed metric name lookup — dashboard was querying for `cpu_percent`/`memory_percent`/`disk_percent` but the OTel agent sends `system.cpu.utilization`/`system.memory.utilization`/`system.filesystem.utilization`; server health gauges were always showing 0%.



### 2026-06-02 (Strategic pivot — AI SRE for Small Teams)

**Identity**
- Platform renamed from "Centralized AI Monitoring Platform" → "The DevOps Engineer Your Small Team Doesn't Have"
- Login page tagline and feature bullets updated to reflect the new positioning
- README.md updated with new tagline, answers-first philosophy, and change correlation as the killer feature

**New services**
- `services/change-tracker/` — new Python/FastAPI service (port 8011):
  - `POST /ingest` — generic change event from agent (deployment, config, restart, package, cron, SSH)
  - `POST /ingest/docker` — Docker daemon events from agent
  - `POST /webhooks/github` — GitHub push / deployment / workflow_run webhooks (HMAC signature verified)
  - `POST /webhooks/gitlab` — GitLab push / pipeline / deployment webhooks
  - Writes to `change_events` TimescaleDB hypertable; publishes `change.detected.{org_id}` to NATS
  - Exposed via Nginx at `/api/changes/`
- `services/correlation-engine/` — new Python service (port 9095):
  - Subscribes to `anomaly.detected.>` NATS stream
  - For each anomaly, queries `change_events` in the T-30min window before it
  - Scores each candidate change: temporal proximity (exponential decay) × change-type weight
    (deployment=1.0, config=0.9, package=0.8, docker_pull=0.75, restart=0.7, cron=0.5, ssh=0.3)
  - Calls Ollama with plain-language prompt targeting small-team developers
  - Saves to `root_cause_analyses` with confidence score, correlated changes list, narrative, and fix steps
  - Publishes `rootcause.ready.{org_id}` to NATS → WS Gateway → browser

**Database (migration 000014)**
- New TimescaleDB hypertable `change_events` — every recorded change on a server
  - Columns: `id`, `org_id`, `server_id`, `occurred_at`, `change_type`, `source`, `actor`, `description`, `payload`, `git_sha`, `image_sha`
  - Indexes on `(server_id, occurred_at)`, `(org_id, occurred_at)`, `(org_id, change_type, occurred_at)`
  - RLS tenant isolation policy
- New table `root_cause_analyses` — correlation engine output
  - Columns: `id`, `org_id`, `anomaly_event_id`, `server_id`, `likely_cause`, `confidence (NUMERIC 0–1)`, `correlated_changes (JSONB)`, `narrative`, `recommended_actions (JSONB)`, `window_start`, `window_end`, `created_at`
  - RLS tenant isolation policy

**NATS streams**
- Added `CHANGES` stream (`change.detected.>`) — 7-day retention
- Added `ROOT_CAUSE` stream (`rootcause.ready.>`) — 30-day retention

**Docker Compose**
- Added `change-tracker` service (port 8011, depends on postgres + nats + migrate)
- Added `correlation-engine` service (port 9095, depends on postgres + nats + ollama + migrate)
- Added `change_tracker` upstream to Nginx; `/api/changes/` location block

**Frontend — answers-first dashboard**
- New `frontend/src/pages/Dashboard.tsx` — answers-first default view at `/`:
  - Top section: "All Systems Healthy" / "Action Required" status banner with server count
  - Potential Issues list: forecasts at risk, anomaly clusters, root-cause analyses, offline servers
  - Recommended Actions: numbered ordered fix steps with plain-English reasons
  - Right sidebar: server mini-grid with CPU/RAM/Disk bars + quick navigation links
  - Live WebSocket events trigger a debounced refresh
- Old metrics dashboard moved to `frontend/src/pages/MetricsDashboard.tsx`, accessible at `/metrics`
- `App.tsx` updated: `/` → new Dashboard, `/metrics` → MetricsDashboard
- Navbar updated across all pages: added "Metrics" link pointing to `/metrics`
- New types added to `types.ts`: `DashboardSummary`, `PotentialIssue`, `RecommendedAction`, `ServerHealth`, `ChangeEvent`
- New API function added to `api.ts`: `getDashboardSummary()` → `GET /api/v1/dashboard/summary`

**Query API**
- New router `services/api-query/query_api/routers/dashboard.py`
  - `GET /api/v1/dashboard/summary` — aggregates servers, anomalies, forecasts, AI explanations, root_cause_analyses into structured answers-first summary with `overall_status`, `potential_issues`, and `recommended_actions`

**LLM prompts rewrite** (small-team voice)
- `services/ai-worker/ai_worker/prompt_builder.py` — rewrote system prompt:
  - Target audience explicitly set: "startup developer with no DevOps background"
  - Anomaly values formatted as percentages (not raw 0–1 decimals)
  - Instructs LLM to explain technical terms in one sentence if used
  - Caps response under 150 words for readability
- `services/ai-orchestrator/prompts.py` — rewrote all prompts:
  - `ANOMALY_TYPE_LABELS` labels changed to plain English ("CPU spike", "memory problem", "disk running full")
  - `_FOCUS_HINTS` rewritten to avoid jargon and target actionable causes a developer can fix
  - `OUTPUT_SCHEMA` prefixed with small-team voice instruction
  - `build_prompt()` opening rewritten: "A small team's server just triggered…"

**Alert deduplication**
- `services/alert-engine/alert_engine/worker.py`:
  - Added `_is_duplicate()`: Redis NX key `dedup:{org_id}:{server_id}:{metric}:{detector}` with 15-min TTL — suppresses re-fires of the same anomaly within the window
  - Added burst detection: tracks distinct metrics firing on the same server within 60s; logs when 3+ metrics burst together
  - Added Prometheus counter `alert_engine_anomalies_suppressed_total`
  - Wired `redis` instance into `_handle_anomaly()` handler

**Agent change reporters** (`services/agent/caimp_agent/change_reporters.py`)
- New module with four background task classes started at agent startup:
  - `DockerEventsReporter` — streams `docker events --format json`, reports `docker_pull` and `restart` events
  - `PackageWatcher` — tails `/var/log/dpkg.log`, `/var/log/yum.log`, `/var/log/apt/history.log` for package installs/removals
  - `AuthWatcher` — tails `/var/log/auth.log` for SSH login/logout events
  - `CronWatcher` — tails `/var/log/syslog` for CRON CMD entries
  - All reporters POST to `change-tracker /api/changes/ingest` via mTLS JWT auth
  - Failures are non-fatal (graceful degradation when log files don't exist)
- `services/agent/main.py` updated: starts all reporters as background asyncio tasks after enrollment

### 2026-06-02 (README.md — architecture, communication, deployment guide)
- Created `README.md` at project root with:
  - Full architecture ASCII diagram showing all containers and how they connect
  - Step-by-step data flow: agent → OTLP → Telemetry Writer → NATS → AI Worker / Alert Engine / Forecast Engine → DB → WebSocket → browser
  - Splunk integration pipeline (webhook → AI Orchestrator → RAG → LLM → HEC writeback → NATS)
  - NATS JetStream streams table (subjects, producers, consumers)
  - Services reference table (all 17 containers, ports, roles)
  - Complete deployment guide: prerequisites, clone, `.env` setup, `make up`, pull Ollama models, seed demo data, enroll a monitoring agent
  - Low-RAM (4 GB) mode instructions
  - Useful `make` commands reference
  - Environment variables reference table
  - Database schema key tables
  - Troubleshooting section (unhealthy services, missing AI explanations, no metrics, forecast issues, disk space)
  - Splunk integration setup instructions
  - Security notes (mTLS, JWT, encrypted Splunk passwords, TLS)
  - Full tech stack table

### 2026-06-06 (LaTeX reports — remove dedication & acknowledgements pages; fix figure structure)
- Removed dedication page (`frontmatter/dedicace` / `frontmatter/dedication`) from both FR and EN `main.tex`
- Removed acknowledgements page (`frontmatter/remerciements` / `frontmatter/acknowledgements`) from both FR and EN `main.tex`
- EN report: added missing `\label` to 12 tables across chapters 4, 6, 7, 8, 9 so they can be cross-referenced with `\ref`
- EN report: added testing pyramid `figure` environment with tikzpicture to `07_testing.tex` (matching the FR version)

### 2026-06-06 (PDF report — rebrand to navy/teal palette matching the UI logo)
- Updated PDF report color palette from warm-brown to CAIMP's actual navy/teal brand:
  - `BRAND` `#3d2b1f` → `#1a3d5c` (navy, matching `--brand` CSS variable and Logo.tsx)
  - `BRAND2` `#5c4033` → `#2c5282` (lighter navy, matching `--brand-lt`)
  - `ACCENT` `#c49a6c` → `#2ea99f` (teal, matching Logo.tsx teal node color)
  - `LGRY` `#fdf8f5` → `#e8f0f8` (pale blue, matching `--brand-pale`)
  - `MGRY` `#e8ddd5` → `#d6e0ec` (blue-grey border, matching `--border`)
  - `DGRY` `#7a6a5e` → `#5a7a96` (muted blue, matching `--muted`)
  - `ORANGE` `#ea580c` → `#d97706` (matching `--warning`)
- Cover page: decorative background circles updated from warm-brown variants to dark navy variants
- Cover page: logo badge changed from white box with "C" letter to teal rounded rect with a drawn network+ECG icon (matching Logo.tsx icon layout)
- Cover page: metadata text color updated from warm muted `#b09080` → `#8aadc8` (matching `--muted-lt`)
- Cover page: bottom strip background `#1a110a` → `#0f1e2e` (matching `--text`), strip text `#7a6a5e` → `#5a7a96`
- Inner page header: small badge changed from white box to teal (`ACCENT`) background with white "C" text
- File: `services/api-query/query_api/routers/reports.py`

### 2026-05-29 (PDF report redesign — logo, cover page, plain-English language)
- Added a full-bleed cover page drawn with ReportLab canvas: dark-brown background, decorative circles, CAIMP logo (white rounded-square badge with "C" + "CAIMP" wordmark + "Infrastructure Monitor" subtitle), report title, tagline, and metadata
- Replaced navy/blue color palette with warm brand palette: `#3d2b1f` primary, `#c49a6c` accent, `#fdf8f5` light background
- Page header on every subsequent page: small "C" badge logo + "CAIMP · Infrastructure Health Report" + generation date
- Section renamed: "Executive Summary" → "At a Glance"; "Server Health Overview" → "Your Servers Right Now"; "Predictive Forecasts" → "What's Coming — Next 24 Hours"; "Anomaly Log" → "Issues Detected"; "AI-Generated Insights" → "AI Analysis & Recommendations"
- Forecast table columns: "+6 h" → "In 6 Hours", "+24 h" → "In 24 Hours", "Time to Critical" → "Risk Window"
- Forecast trend column: replaced `↑ +0.012/h` notation with plain labels: "Rising fast", "Rising", "Stable", "Easing down", "Falling" (color-coded)
- Risk Window values: "None in 24 h" → "No risk today"; numeric hours shown as "Less than 1 hour" / "About N hours" / "~N hours away"
- Anomaly values: utilization metrics shown as percentages (`87.6%`) instead of raw decimals (`0.876`)
- AI insight card labels: "Analysis" → "What happened"; "Root Cause" → "Why it happened"; "Action" → "What to do" (green color for action text)
- Status labels: "OK" → "Healthy"; added plain-English callout box when metrics are at risk within 6 hours
- Each section includes a plain-English subtitle explaining what the section contains
- File: `services/api-query/query_api/routers/reports.py`

### 2026-05-29 (Dark mode / light mode via system preference)
- Added `color-scheme: light dark` to `:root` so browser chrome (inputs, scrollbars) follows the system
- Added `@media (prefers-color-scheme: dark)` block in `index.css` with a warm dark palette:
  - Surfaces: `#0f0d0b` → `#1e1915` (dark warm brown, not cold gray)
  - Text: `#ede0d4` (warm cream) / muted `#8a7a6e`
  - Brand: `#c49a6c` (golden amber — readable on dark bg, cohesive with `#3d2b1f` light brand)
  - Semantic: brightened success/warning/danger/info for dark-bg contrast
- Added dark mode overrides for all hardcoded light-hex CSS classes: `.badge-*`, `.badge-conf-*`, `.data-table-row--critical/warning`
- Added CSS variables for colours previously hardcoded in React inline styles:
  - `--event-anomaly/ai/conn/metric-bg/fg` — event feed rows in Dashboard
  - `--error-banner-bg/border` — error banners in Incidents/Runbooks/Login
  - `--tooltip-bg` — Recharts tooltip backgrounds
- Patched inline styles in Dashboard, Incidents, Runbooks, Login, SplunkAIExplanation, ServerDetail to use CSS variables instead of hardcoded hex
- No JavaScript theme toggle — purely driven by `prefers-color-scheme`

### 2026-05-29 (Replace all emoji with SVG icons)
- Created `frontend/src/components/Icons.tsx` — zero-dependency inline SVG icon library:
  - `Spinner`, `Check`, `AlertTriangle`, `Close`, `ChevronUp/Down/Right`, `ArrowUp/Down/Left/Right`
  - `TrendingUp`, `TrendingDown`, `Minus`, `Download`, `RefreshCw`, `FileText`, `BarChart`
  - `Bot`, `ThumbsUp`, `ThumbsDown`, `Monitor`, `Search`, `BookOpen`, `MessageCircle`
  - All icons use `currentColor`, configurable `size` prop, inline-block layout
- Replaced every emoji/Unicode special character across all frontend source files:
  - Dashboard.tsx: `⟳`→Spinner, `⚠`→AlertTriangle, `✓`→Check, `→`→ArrowRight, `↓ PDF`→Download
  - Incidents.tsx: `▲▼`→ChevronUp/Down, `⟳`→Spinner, `✓`→Check, pipeline `→`→SVG arrow
  - Runbooks.tsx: `⟳`→Spinner, `📋`→FileText, `✕`→Close, pipeline `→` and `›`→SVG arrows
  - Forecasts.tsx: `⟳`→Spinner, `📊`→BarChart, trend arrows→TrendingUp/Down/Minus, `⚠`→AlertTriangle, `✓`→Check, `▸▾`→ChevronRight/Down, `↻`→RefreshCw
  - ServerDetail.tsx: `⟳`→Spinner, `←`→ArrowLeft, `↓ Export PDF`→Download, `✓`→Check
  - SplunkAIExplanation.tsx: `⟳`→Spinner, `✕`→Close, `▸▾`→ChevronRight/Down, `✓`→Check, `👍👎`→ThumbsUp/Down
  - ChatPanel.tsx: `🤖`→Bot, `✕`→Close, `↑`→ArrowUp, `⟳`→Spinner, intent `emoji`→typed SVG icon components
  - Login.tsx: `⚠`→AlertTriangle, `→`→ArrowRight

### 2026-05-29 (Forecasts page — server health predictions for the next hour)
- Created `frontend/src/pages/Forecasts.tsx` — new React page at `/forecasts`:
  - KPI strip: Monitored / Critical (breach <6h) / At Risk (breach 6-24h) / Healthy
  - Per-server `ServerForecastCard`: health verdict banner, 3 metric rows (CPU/RAM/Disk), AI narrative (collapsible)
  - `MetricRow`: progress bar, predicted value for next hour, trend arrow (↑↑/↑/→/↓/↓↓), time-to-critical badge; click to expand 24h sparkline with confidence band + 90% threshold reference line
  - `SparkLine`: Recharts `AreaChart` with stacked confidence band (lower/upper) + predicted line + red dashed threshold
  - Cards sorted by severity (CRITICAL → AT RISK → HEALTHY); color-coded border and badge
  - Legend strip explaining health levels and indicators
- Updated `frontend/src/App.tsx` — added `/forecasts` route
- Updated `frontend/src/types.ts` — added `ForecastPoint` and `ForecastResponse` interfaces
- Updated `frontend/src/api.ts` — added `listForecasts(limit, serverId?)` calling `GET /api/v1/forecasts`
- Updated navbar in Dashboard, Incidents, Runbooks to include **Forecasts** link
- Updated `scripts/seed_demo.sql`:
  - Fixed disk metric name: `system.disk.utilization` → `system.filesystem.utilization` (matches query API)
  - Added `server_forecasts` seed (15 rows, 5 servers × 3 metrics) with realistic Holt-Winters forecast points generated via `generate_series`; produces health mix: db-primary=CRITICAL (disk 5h, RAM 12h), web-server-01/worker-01=AT RISK, demo-server-01/cache-01=HEALTHY
- **Forecast engine metric names**: engine uses `cpu_percent` / `memory_percent` / `disk_percent`; dashboard gauges use `system.cpu.utilization` / `system.memory.utilization` / `system.filesystem.utilization` — these are separate metric name spaces; the Forecasts page reads from `server_forecasts` table (populated by engine or seed)

### 2026-05-29 (Demo data seed — populate dashboard with realistic data)
- Created `scripts/seed_demo.sql` — PostgreSQL seed script for demo data:
  - **Servers**: adds 5 additional servers (web-server-01, db-primary, worker-01, cache-01, api-gateway) with statuses (online/degraded/offline), IPs, versions, labels; updates demo-server-01 to online
  - **Incidents**: 20 `splunk_incidents` spread over 7 days — 4 critical, 6 high, 7 medium, 3 low; types: `cpu_saturation`, `memory_leak`, `disk_pressure`, `network_anomaly`, `io_wait`, `process_crash`
  - **AI analyses**: 19 `splunk_ai_explanations` with complete `explanation`, `root_cause`, `recommended_action`, `evidence_spl_queries`, `confidence`, `llm_provider`; 1 pending (api-gateway outage)
  - **Metrics**: ~10k rows (7 days × 15-min intervals × 5 servers × 3 metrics: cpu/memory/disk); realistic time-series with spikes matching incident timestamps
  - **Anomaly events**: 15 `anomaly_events` matching incident windows (detectors: static/zscore/rate_of_change)
  - **Runbooks**: 5 operational runbooks (cpu_saturation, memory_leak, disk_pressure, network_anomaly, process_crash) with full diagnosis/remediation content
  - **Notifications**: 7 historical alert notifications
- Created `scripts/seed_demo.ps1` — PowerShell runner:
  - Pipes SQL to `caimp-postgres` container via `docker exec -i`
  - Fires a live webhook to `POST /webhook/anomaly` on the AI orchestrator (triggers real LLM pipeline)
  - Logs in and verifies incident/server counts via Query API
- **Usage**: `.\scripts\seed_demo.ps1` (from project root, after stack is running)

### 2026-05-24 (Low-RAM test mode — 4 GB Ubuntu VM)
- Fixed `docker-compose.yml` bug: removed `otelcol` (profile-gated) and `grafana` from `nginx.depends_on` — nginx previously failed to start without `--profile otel` active
- Created `docker-compose.test.yml` (compose override for ≤ 4 GB RAM):
  - Moves `ollama`, `prometheus`, `grafana`, `splunk-hec-bridge` to `profiles: [full]` — excluded by default, start with `--profile full` if needed
  - Switches Ollama model to `llama3.2:1b` (~1.3 GB) when Ollama IS used (vs default `llama3.1:8b` at ~5 GB)
  - Hard `mem_limit` on every container (postgres 512 m, redis 192 m, FastAPI services 256 m each, etc.)
  - Drops `AI_WORKER_CONCURRENCY` to 1; lowers anomaly thresholds to 70% so test traffic triggers events
- Created `scripts/start-test.sh` — one-command VM startup:
  - Creates 4 GB `/swapfile` if not present (sets `vm.swappiness=10`, persists in `/etc/fstab`)
  - Installs Docker if missing (via `get.docker.com`)
  - Auto-generates `.env` from `.env.example` with a real `JWT_SECRET` if `.env` doesn't exist
  - Builds images, starts test stack, prints access URLs and memory usage
- **Usage on VM**: `bash scripts/start-test.sh`
- **Estimated RAM**: ~2.3 GB with test override (leaves 1.7 GB headroom on a 4 GB VM)
- **Estimated RAM with `--profile full` + llama3.2:1b**: ~3.5 GB + 4 GB swap

### 2026-05-24 (AdminPro dashboard — admin.html linked to backend)
- Created `frontend/public/admin.html` — self-contained single-file dashboard (no build step):
  - **Login overlay**: JWT auth via `POST /auth/login`; credentials pre-filled with dev defaults; token stored in `localStorage`
  - **Sidebar navigation**: Overview / Servers / Incidents / Runbooks — JS hash-routing, no page reload
  - **Service health strip** in sidebar: live probes to `/api/v1/health`, `/api/ai/health`, `/ws/events`
  - **Overview**: 4 KPI cards (Total Servers, Online, Total Incidents, Pending AI); 7-day SVG area chart (anomaly timeline); severity donut chart; recent incidents table
  - **Servers view**: server table with color-coded progress bars (CPU/RAM/Disk), status dot, anomaly count
  - **Incidents view**: stats KPI row; full incidents table (60 rows); click-to-expand AI analysis panel (root cause, recommended action, SPL queries, 👍/👎 feedback)
  - **Runbooks view**: KPI row (total, RAG-indexed, types covered, missing embed); runbook card grid with pgvector badge and type color
  - **WebSocket**: live reconnect on `/ws/events?org_id=…`; triggers data refresh on anomaly/explanation events
  - **Auto-refresh**: every 30 s + manual refresh button
  - Accessible at `http://localhost:3000/admin.html` (served as static file by Nginx via React container)
- Updated `infra/nginx/nginx.conf` CSP: added `unsafe-eval` + `cdn.tailwindcss.com` to `script-src`; Google Fonts to `style-src`/`font-src`; to allow Tailwind Play CDN + Material Symbols used by admin.html

### 2026-05-24 (Frontend refinement — backend pipeline visibility)
- **Incidents page** (`frontend/src/pages/Incidents.tsx`) redesigned:
  - Navbar uses `.nav-link` / `.nav-link--active` CSS classes (consistent with Dashboard)
  - `MiniPipeline` component: 7-dot pipeline strip (WH → CTX → RAG → LLM → VAL → STO → NTF) per incident row, coloured by stage state (done=green, active=yellow/glow, error=red, wait=border); status label below in JetBrains Mono
  - AI Pipeline context bar at page top: horizontal breadcrumb (Splunk MLTK → Webhook recv → Context build → RAG retrieve → LLM call → Validate → Store → NATS notify) with pending/complete counts in JetBrains Mono
  - Table header column renamed "AI Pipeline" (was "AI Status")
  - Metric/host/time values use JetBrains Mono; severity badge uses uppercase + tight letter-spacing
  - Loading states use `.spin` class; expanded row detail card has `boxShadow: var(--shadow)`
- **Runbooks page** (`frontend/src/pages/Runbooks.tsx`) redesigned:
  - Navbar uses `.nav-link` / `.nav-link--active` CSS classes
  - RAG pipeline context bar at page top: horizontal flow (Runbook text → Ollama /embed → pgvector store → Cosine similarity → Inject into LLM ctx) with indexed/missing counts in JetBrains Mono
  - `RagBadge` component: green pgvector badge or amber "no embed" badge with status dot
  - `RunbookCard` now shows a 5-stage RAG flow strip inline, dimming downstream stages when embedding is missing
  - KPI numbers use Syne font via `.kpi-value` class; heading uses `fontFamily: 'Syne, sans-serif'`
  - Content textarea uses JetBrains Mono for command-oriented input clarity
  - Filter pill active state shows brand border; all border radii use `var(--radius)`
- **Design system alignment** (all pages now consistent):
  - DM Sans body, JetBrains Mono for metrics/code/timestamps, Syne for display/headings
  - `.nav-link` / `.nav-link--active` classes on all navbar links
  - `.spin` class for loading spinners; `var(--border)`, `var(--radius)` tokens throughout
  - Pipeline stage visibility pattern: every AI-touched resource shows its pipeline position

### 2026-05-21 (Splunk module — Phase 6: Server detail AI tab)
- **TASK-S20** — Added **Splunk AI tab** to `frontend/src/pages/ServerDetail.tsx`:
  - New `splunk-ai` tab alongside existing Anomalies and AI Explanations tabs
  - KPI strip: Total Incidents (24h), Critical (24h), Last AI Status
  - Incident table: detected time, anomaly type, metric, value, severity badge, AI status, root cause preview
  - Loads via `getServerSplunkHealth(id)` — gracefully hides tab content when Splunk is not configured (404 → no data message)
  - Splunk health loaded in parallel with main data; failures silently ignored so the rest of the page still renders
- Updated `frontend/src/types.ts` — added `SplunkIncidentBrief` and `ServerSplunkHealth` interfaces
- Updated `frontend/src/api.ts` — added `getServerSplunkHealth(id)` calling `GET /api/v1/servers/{id}/splunk`
- All other Phase 6 tasks confirmed complete from prior sessions: Incidents page (Step 20), SplunkAIExplanation component (Step 20), ConversationalChat panel (Step 21), Runbooks management page (Step 22), smoke test (Step 23); docker-compose required no additions (all env vars already present)

### 2026-05-21 (Splunk module — Phase 5: Postgres schema + Query API)
- **TASK-S14** — Created `infra/postgres/migrations/000013_server_splunk_link.up.sql`:
  - Adds nullable `splunk_host TEXT` column to `servers` table — allows mapping a registered server to a different Splunk host name (falls back to `servers.hostname` when NULL)
  - Creates `idx_servers_splunk_host` partial index on `(org_id, splunk_host)` for non-NULL values
  - Creates `v_server_splunk_health` view: aggregates 24h Splunk incident counts, critical counts, last incident time, and last AI explanation status per server by joining `servers → splunk_incidents → splunk_ai_explanations` (via `COALESCE(splunk_host, hostname)`)
  - Created `infra/postgres/migrations/000013_server_splunk_link.down.sql`
- **TASK-S15** — Extended `services/api-query/query_api/routers/servers.py` with `GET /servers/{server_id}/splunk`:
  - Returns `ServerSplunkHealth`: aggregate stats from `v_server_splunk_health` + 10 most recent Splunk incidents with AI explanation status
  - Cached 60 s; 404 when server not found
  - New Pydantic models: `SplunkIncidentBrief`, `ServerSplunkHealth`

### 2026-05-21 (Splunk module — Phase 4: Chat module enhancements)
- **TASK-S13** — Extended `services/ai-orchestrator/chat.py`:
  - Added `spl_explain` intent — detected when message contains SPL pipe commands (`| stats`, `| eval`, `| mstats`, etc.), `index=`/`sourcetype=` assignments, or explicit "explain this query/search" phrasing; checked before `anomaly_query` to avoid collisions with anomaly explanations that reference SPL
  - New patterns: `_SPL_PIPE_CMD`, `_SPL_ASSIGN`, `_SPL_EXPLAIN`
  - `gather_chat_context()` for `spl_explain`: passes the raw SPL snippet (up to 600 chars) as context and returns early (no DB queries needed)
  - `gather_chat_context()` for `anomaly_query`: after DB fetch, optionally runs a live `mstats` oneshot query against Splunk for the host's CPU utilization (last 15 min, 5 data points); appended to context when Splunk is configured; failures silently ignored
  - `build_chat_prompt()` for `spl_explain`: injects extra system instruction to walk through each pipe command in order and summarise the search's purpose
  - Intent docstring updated to list all 5 intents in priority order
  - Intent names: `spl_explain` (new), `host_query`, `anomaly_query` (= spec's `anomaly_question`), `runbook_query`, `general`
  - Frontend `ChatPanel.tsx` `spl_explain` badge wired via existing intent color map (falls through to grey `general` style — no frontend change required)

### 2026-05-21 (Splunk module — Phase 3: LLM pipeline)
- **TASK-S09** — `services/ai-orchestrator/prompts.py` confirmed: `ANOMALY_TYPE_LABELS`, `_FOCUS_HINTS`, `OUTPUT_SCHEMA`, `build_prompt()` — all complete from prior session
- **TASK-S10** — `services/ai-orchestrator/llm.py` confirmed: `call_ollama()`, `call_anthropic()`, `route_and_call()` — all complete from prior session
- **TASK-S11** — `services/ai-orchestrator/output_validator.py` + `process_anomaly()` in `main.py` confirmed: full 9-step pipeline (context → RAG → prompt → LLM → validate → DB persist → Redis cache → HEC writeback → NATS) — all complete from prior session
- **TASK-S12** — Slack + PagerDuty notification:
  - Created `infra/postgres/migrations/000012_org_config_alert_channels.up.sql` — adds `alert_channels JSONB DEFAULT '{}'` and `auto_remediate BOOLEAN DEFAULT false` to `org_config`
  - Created `infra/postgres/migrations/000012_org_config_alert_channels.down.sql`
  - Added `send_notification(incident_id, anomaly, parsed)` to `services/ai-orchestrator/main.py`:
    - Reads `alert_channels` JSONB from `org_config` (acquires own pool connection)
    - Posts to Slack webhook if `alert_channels.slack_webhook` is set
    - Posts to PagerDuty Events API v2 if `alert_channels.pagerduty_key` is set and severity is `critical` or `high`
    - All failures logged at WARNING level — non-fatal
  - Wired as `asyncio.create_task(send_notification(...))` at step 10 of `process_anomaly()` (after NATS publish)
  - DB schema: `alert_channels = {"slack_webhook": "https://...", "pagerduty_key": "..."}`

### 2026-05-21 (Splunk module — Phase 0: Time-series layer)
- **TASK-S00** — `splunk/props.conf` + `splunk/transforms.conf` confirmed correct (metric schema for `caimp:metrics` sourcetype; `METRIC_SCHEMA_LOOKUP` binds to `caimp_metric_schema` so `mstats` can read the metric index)
- **TASK-S00b** — `splunk/indexes.conf` confirmed with all 7 stanzas: `caimp_metrics` (metric, 7 d), `caimp_logs`, `caimp_anomalies`, `caimp_ai` (event, 90 d each), plus rollup tiers `caimp_metrics_5m` (90 d), `caimp_metrics_1h` (1 yr), `caimp_metrics_1d` (3 yr)
- **TASK-S00c** — `splunk/rollup_searches.conf` confirmed with 3 scheduled `collect` searches: 5-min rollup (every 5 min), 1-hour rollup (hourly at :05), 1-day rollup (daily at 01:00 UTC)
- **TASK-S00d** — `splunk/collections.conf` confirmed (KV Store schema for `caimp_baselines`); 24 h baseline compute search (`CAIMP - 24h Baseline Compute`) confirmed in `rollup_searches.conf`; `splunk/README.md` includes KV Store setup instructions
- **TASK-S00e** — Added `GET /metrics/splunk/live` endpoint to `services/api-query/query_api/routers/splunk_metrics.py`:
  - Query params: `server_id`, `metric_name`
  - Reads Redis key `live:{org_id}:{server_id}:{metric_name}` (written by HEC bridge with TTL=90 s)
  - Computes `age_seconds = 90 - ttl_remaining` via pipeline `GET` + `TTL`
  - Returns `{"metric": str, "value": float|null, "age_seconds": int}` — null + age 999 when no data in last 90 s
  - Splunk historical proxy (`GET /metrics/splunk`) was already in place from Step 18
- **TASK-S00f** — Confirmed complete: `services/splunk-hec-bridge/main.py` already writes `live:{org_id}:{server_id}:{metric_name}` TTL=90 s to Redis after every successful HEC batch; `redis[asyncio]` in requirements; `REDIS_URL` in docker-compose

### 2026-05-21 (Splunk module — Step 23)
- Created `scripts/smoke_test_splunk.py` — end-to-end integration smoke test (stdlib only, no extra packages):
  - **Step 1 — Health checks:** `GET /health` on ai-orchestrator (8010) and query-api (8002)
  - **Step 2 — Auth:** `POST /auth/login` on admin-api (8001) to acquire JWT; used as Bearer token for all subsequent query-api calls
  - **Step 3 — Webhook:** `POST /webhook/anomaly` to ai-orchestrator with a `cpu_saturation / high` test payload; asserts HTTP 202 + `incident_id` in response
  - **Step 4 — Pipeline poll:** polls `GET /incidents/{id}` on query-api every 3 s until `explanation.status` is `complete` or `error` (configurable timeout, default 120 s); prints live status transitions
  - **Step 5 — Field validation:** asserts all 6 required explanation fields (`severity`, `explanation`, `root_cause`, `recommended_action`, `confidence`, `llm_provider`) are non-empty; notes empty `evidence_spl_queries` as expected when Splunk is not configured
  - **Step 6 — Stats:** `GET /incidents/stats` — asserts HTTP 200 + `total` key
  - **Step 7 — Runbook CRUD:** create → GET → PUT → list (with `anomaly_type` filter) → DELETE → verify 404
  - CLI flags: `--ai-url`, `--api-url`, `--admin-url`, `--org-id`, `--email`, `--password`, `--timeout`, `--severity`, `--no-color`
  - Exit code 0 = all checks passed; non-zero = one or more failures (failures listed in summary)

### 2026-05-21 (Splunk module — Step 22)
- Created `frontend/src/pages/Runbooks.tsx` — full runbook management page:
  - Stats strip: Total Runbooks, CPU Saturation, Memory Pressure, Disk Fill KPI cards
  - Filter pills by anomaly type (All / CPU Saturation / Memory Pressure / Disk Fill / Network Anomaly / Security Event)
  - `RunbookCard` component: colored left border per type, title, anomaly-type badge, RAG badge (`has_embedding`), Edit / Delete buttons
  - `RunbookForm` component: title input + anomaly-type select + multiline content textarea; inline create/edit toggle
  - CRUD: `handleCreate()`, `startEdit()` (prefills form), `handleEdit()`, `handleDelete()` (window.confirm guard)
  - When unfiltered, runbooks are grouped by anomaly type; when filtered, flat list
- Added `DELETE /runbooks/{runbook_id}` (HTTP 204) to `services/api-query/query_api/routers/incidents.py`
- Updated `frontend/src/api.ts` — added `listRunbooks`, `getRunbook`, `createRunbook`, `updateRunbook`, `deleteRunbook`
- Updated `frontend/src/types.ts` — added `RunbookSummary`, `RunbookDetail` types
- Updated `frontend/src/App.tsx` — added `/runbooks` route (auth-guarded)
- Updated `frontend/src/pages/Dashboard.tsx` — added Runbooks nav link to navbar
- Updated `frontend/src/pages/Incidents.tsx` — added Runbooks nav link to navbar

### 2026-05-21 (Splunk module — Step 21)
- Created `frontend/src/components/ChatPanel.tsx` — floating SSE chat widget:
  - Fixed bottom-right 💬 button toggles a 380×520 px panel
  - Messages sent via `POST /api/ai/chat`; response streamed token-by-token using Fetch `ReadableStream`
  - SSE frame parsing: `intent` event → badge on assistant bubble; `token` events → appended live; `done` finalises the message
  - Intent badges color-coded: host_query (blue), anomaly_query (red), runbook_query (green), general (grey)
  - Enter to send, Shift+Enter for newline; streaming cursor blink animation
- Updated `frontend/src/App.tsx` — `ChatOverlay` renders `ChatPanel` on all authenticated pages (hidden on `/login`)
- Updated `infra/nginx/nginx.conf`:
  - Added `upstream ai_orchestrator { server ai-orchestrator:8010 }`
  - Added `location /api/ai/` → ai-orchestrator with `proxy_buffering off` + `proxy_cache off` for SSE streaming
- Updated `docker-compose.yml` — Step 21 cutover:
  - `otelcol` moved to `profiles: [otel]` (disabled by default); re-enable with `--profile otel`
  - `ai-orchestrator` removed from `profiles: [splunk]` — now always-on default service
  - `splunk-hec-bridge` removed from `profiles: [splunk]` — now always-on default service
  - Added `NATS_URL: nats://nats:4222` and `nats` dependency to `ai-orchestrator`
- Updated `DOCUMENTATION.md` — Local services table: `http://localhost:8010` AI Orchestrator now default (not splunk profile)

### 2026-05-21 (Splunk module — Step 20)
- Created `frontend/src/components/SplunkAIExplanation.tsx`:
  - Renders pending/error/complete states; for complete: explanation text, root_cause + recommended_action side-by-side cards, SPL verification queries in dark monospace blocks
  - Confidence and severity color-coded; LLM provider badge
  - Inline 👍/👎 feedback buttons calling `POST /incidents/{id}/feedback`
- Created `frontend/src/pages/Incidents.tsx`:
  - Stats row: Total Incidents, Critical, High, Pending AI Analysis KPI cards
  - Filter bar: host text input, severity dropdown, anomaly type dropdown
  - Incidents table with expandable rows — clicking a row fetches `GET /incidents/{id}` and renders `SplunkAIExplanation` inline; detail cached client-side to avoid re-fetching
  - Nav: Dashboard / Incidents links
- Updated `frontend/src/App.tsx` — added `/incidents` route
- Updated `frontend/src/pages/Dashboard.tsx` — added Dashboard / Incidents nav links to navbar
- Updated `frontend/src/api.ts` — added `listIncidents`, `getIncident`, `getIncidentExplanation`, `getIncidentStats`, `submitFeedback`
- Updated `frontend/src/types.ts` — added `IncidentSummary`, `ExplanationDetail`, `IncidentDetail`, `IncidentStats` types

### 2026-05-21 (Splunk module — Step 19)
- Created `services/api-query/query_api/routers/incidents.py` — 9 new routes:
  - `GET  /incidents` — paginated list with filters (host, severity, anomaly_type, from/to, limit); LEFT JOINs explanation status
  - `GET  /incidents/stats` — aggregate counts `{total, by_severity, by_anomaly_type, pending_explanations}`; cached 30s
  - `GET  /incidents/{id}` — full incident detail with nested `ExplanationDetail` (evidence_spl_queries decoded from JSONB)
  - `GET  /incidents/{id}/explanation` — explanation only
  - `POST /incidents/{id}/feedback` — inserts `ai_feedback` row with `rating` (-1/0/1) + optional `comment`; 404 if no complete explanation exists
  - `GET  /runbooks` — list with optional `anomaly_type` filter; includes `has_embedding` flag
  - `GET  /runbooks/{id}` — single runbook detail
  - `POST /runbooks` — creates runbook + best-effort Ollama embedding (stores NULL vector if Ollama unavailable)
  - `PUT  /runbooks/{id}` — updates fields + re-embeds if any field changed
- Updated `services/api-query/query_api/config.py` — added `ollama_url` and `ollama_embed_model` settings
- Updated `services/api-query/query_api/main.py` — registered `incidents` router
- Updated `docker-compose.yml` — added `OLLAMA_URL` + `OLLAMA_EMBED_MODEL` env vars to `query-api` service

### 2026-05-21 (Splunk module — Step 18)
- Created `services/api-query/query_api/splunk.py` — `SplunkMetricsClient`:
  - `select_index_and_span(hours)` — mirrors context_builder tier logic (≤1h raw, ≤12h 5m, ≤72h summary-5m, ≤720h summary-1h, else summary-1d)
  - `query_metrics(metric_name, host, org_id, index, span, earliest, latest)` — oneshot mstats export via `POST /services/search/jobs/export`; parses newline-delimited JSON; returns `[{time, value}]`
- Created `services/api-query/query_api/routers/splunk_metrics.py`:
  - `GET /metrics/splunk?host=&metric_name=&from_time=&to_time=` — queries Splunk mstats with auto-selected index/span; same `MetricPoint` response shape as TimescaleDB `/metrics`; cached 30s for live data, 5min for historical
  - `GET /metrics/splunk/status` — returns `{"configured": true/false}`
  - Returns HTTP 503 when Splunk is not configured
- Updated `services/api-query/query_api/config.py` — added `splunk_host`, `splunk_username`, `splunk_password`, `splunk_verify_tls` settings
- Updated `services/api-query/query_api/main.py` — initialises `SplunkMetricsClient` on startup if `SPLUNK_HOST` set; registers `splunk_metrics` router
- Added `httpx==0.27.0` to `services/api-query/requirements.txt`
- Updated `docker-compose.yml` — added `SPLUNK_HOST/USERNAME/PASSWORD/VERIFY_TLS` env vars to `query-api` service

### 2026-05-21 (Splunk module — Step 17)
- Created `infra/postgres/migrations/000011_splunk_tables.up.sql` — 5 new tables:
  - `splunk_incidents` — raw anomaly events from Splunk webhook; indexed on `(org_id, detected_at)`, `(org_id, host)`, `(org_id, severity)` for high/critical
  - `splunk_ai_explanations` — LLM output: `status` (pending|complete|error), all 6 schema fields + `llm_provider`, `error_message`, `completed_at`; indexed on `incident_id` and pending-status partial index
  - `ai_feedback` — operator rating (`-1/0/1`) + optional comment per explanation; linked to `splunk_ai_explanations`
  - `org_config` — per-org cloud LLM config: `use_cloud_llm` (bool), `anthropic_api_key`, Splunk credentials (`splunk_password_enc` stored AES-256-GCM encrypted)
  - `runbooks` — diagnosis guides: `title`, `anomaly_type`, `content`, `embedding VECTOR(768)` with HNSW cosine index for RAG; linked to `users` via `created_by`
- Created `infra/postgres/migrations/000011_splunk_tables.down.sql` — drops tables in reverse FK order
- All 5 tables have RLS `tenant_isolation` policies using `current_org_id()` and `GRANT ALL TO caimp_service`
- Migration auto-applied on next `docker compose up` (volume-mounted at `/migrations`)

### 2026-05-21 (Splunk module — Step 16)
- Created `services/ai-orchestrator/chat.py` — conversational chat engine:
  - `classify_intent(message, host_hint)` — regex-based classifier returning `host_query | anomaly_query | runbook_query | general` + extracted entities (host, incident UUID)
  - `gather_chat_context(intent, entities, org_id, db, splunk)` — fetches DB context per intent: recent incidents + AI explanations for host queries; stored explanation for anomaly queries; runbook excerpts for runbook queries; gracefully degrades on DB errors
  - `build_chat_prompt(message, history, context, intent)` — assembles system prompt (with injected context) + last 3 history turns into a single Ollama-compatible string
  - `stream_ollama(prompt, http, ollama_url, model)` — async generator that POSTs to `/api/generate` with `stream: true` and yields individual tokens
- Added `POST /chat` route to `main.py` — returns `StreamingResponse` (`text/event-stream`):
  - Verifies Bearer JWT (skipped when `JWT_SECRET` unset for internal/dev use)
  - Classifies intent, gathers context, streams SSE events: `{"type":"intent"}` → `{"type":"token","content":"..."}` (per token) → `{"type":"done"}`
  - Sets `X-Accel-Buffering: no` header to disable Nginx proxy buffering
- Added `JWT_SECRET` env var to `main.py`

### 2026-05-21 (Splunk module — Step 15)
- Created `services/ai-orchestrator/output_validator.py`:
  - `validate_and_parse(raw)` — strips markdown fences, parses JSON, enforces required keys, normalises `severity` and `confidence` enums, caps `evidence_spl_queries` at 5 items; raises `ValueError` on unrecoverable failures
- Completed `process_anomaly()` in `main.py` — full 9-step pipeline:
  1. Splunk context (`build_context`)
  2. RAG retrieval (`retrieve_rag_context`)
  3. Prompt assembly (`build_prompt`)
  4. LLM call (`route_and_call`)
  5. Output validation (`validate_and_parse`) — marks explanation `error` and returns early on failure
  6. DB persist — UPDATE `splunk_ai_explanations` with all 7 LLM fields + `completed_at`
  7. Redis cache — `ai:explanation:{incident_id}` with 24h TTL
  8. Splunk HEC writeback — POSTs explanation event to `caimp_ai` index (skipped if HEC not configured)
  9. NATS publish — `SPLUNK.ai_explanation` subject for WS gateway (skipped if NATS unavailable)
- Added NATS client (`nats-py==2.7.2`) to `main.py` lifespan; graceful degradation if NATS unreachable
- Added `NATS_URL` env var (default: `nats://nats:4222`)
- Added `nats-py==2.7.2` to `requirements.txt`

### 2026-05-21 (Splunk module — Step 14)
- Created `services/ai-orchestrator/llm.py` — LLM router with two callers:
  - `call_ollama(prompt, http)` — POST to Ollama `/api/generate` with `format: "json"`, `temperature=0.2`, `num_predict=600`
  - `call_anthropic(prompt, api_key, http)` — POST to Anthropic Messages API (`claude-sonnet-4-20250514`), max 600 tokens
  - `route_and_call(prompt, anomaly, db, http)` — looks up `org_config` for `anthropic_api_key` + `use_cloud_llm`; routes critical anomalies to Anthropic if enabled, falls back to Ollama on failure or for all other severities; returns `(raw_response, provider)`
- Wired `build_prompt()` + `route_and_call()` into `process_anomaly()` in `main.py` after RAG step

### 2026-05-21 (Splunk module — Step 13)
- Created `services/ai-orchestrator/prompts.py` — prompt template assembly:
  - `ANOMALY_TYPE_LABELS` — maps 5 anomaly types to alert labels, metric names, value fields
  - `_FOCUS_HINTS` — per-type diagnostic focus strings (runaway processes, memory leaks, etc.)
  - `OUTPUT_SCHEMA` — enforces 6-key JSON shape: `severity`, `explanation`, `root_cause`, `recommended_action`, `evidence_spl_queries`, `confidence`
  - `build_prompt(anomaly, context, rag)` — assembles all 8 prompt sections into a single LLM-ready string

### 2026-05-20 (Splunk module — Step 12)
- Created `services/ai-orchestrator/rag_retriever.py`:
  - `get_embedding()` — calls Ollama `nomic-embed-text` to embed anomaly signature (`anomaly_type + metric_name + severity`)
  - `retrieve_rag_context()` — queries `rag_documents` (cosine similarity > 0.6, top 3) and `runbooks` (cosine similarity > 0.55, top 2) via pgvector; returns formatted text for prompt injection; gracefully degrades if Ollama or pgvector unavailable
- Wired `retrieve_rag_context()` into `process_anomaly()` in `main.py` after context building

### 2026-05-20 (Splunk module — Step 11)
- Created `services/ai-orchestrator/context_builder.py` — fires 5 SPL queries concurrently via `asyncio.gather()`:
  - `metric_trend` — last 1h, 1-min buckets, raw index
  - `correlated_metrics` — CPU + memory + disk last 30min timechart
  - `error_logs` — ERROR/CRITICAL log lines from `caimp_logs` last 1h
  - `past_anomalies` — last 7 days from `caimp_anomalies`
  - `ai_history` — last 30 days of prior AI explanations from `caimp_ai`
- Added `select_index_and_span()` — auto-selects raw vs summary index based on time range
- Wired `build_context()` into `process_anomaly()` in `main.py`
- Added `GET /test/context?host=<host>` debug route to verify Splunk connectivity

### 2026-05-20 (Splunk module — Step 10)
- Created `services/ai-orchestrator/splunk_client.py` — Splunk REST API client with three methods:
  - `run_search()` — two-phase: POST job → poll until done (max 30s) → GET results
  - `run_search_oneshot()` — single export POST, newline-delimited JSON parsing, faster for context queries
  - `get_baseline()` — reads 24h rolling stats from `caimp_baselines` KV Store lookup
- Wired `SplunkClient` into `main.py` as a shared global; initialised on startup if `SPLUNK_HOST` + `SPLUNK_PASSWORD` are set; gracefully skipped with a warning if not configured

### 2026-05-20 (Splunk module — Step 9)
- Created `services/ai-orchestrator/` — new Python/FastAPI service (port 8010)
  - `main.py` — `POST /webhook/anomaly` validates payload, inserts `splunk_incidents` + `splunk_ai_explanations` rows, dispatches `process_anomaly()` background task (stub, filled in Steps 10–15); `GET /health`
  - `requirements.txt` — fastapi, uvicorn, asyncpg, httpx, pydantic, redis, python-jose
  - `Dockerfile` — python:3.11-slim, port 8010
- Added `ai-orchestrator` service to `docker-compose.yml` under `profiles: [splunk]`

### 2026-05-20 (Splunk module — Step 8)
- Created `splunk/bin/caimp_webhook.py` — Splunk custom alert action script; reads result row from stdin, infers metric name from search name, POSTs structured anomaly JSON to AI Orchestrator; logs to `/var/log/splunk/caimp_webhook.log`
- Created `splunk/alert_actions.conf` — registers `caimp_webhook` as a Python 3 alert action with configurable endpoint parameter
- Created `splunk/metadata/default.meta` — grants read access to all users, write to admins
- Updated `splunk/README.md` — added installation steps, manual test command, and payload example

### 2026-05-20 (Splunk module — Step 7)
- Added 4 anomaly detection scoring searches to `splunk/savedsearches.conf`:
  - `CAIMP - CPU Anomaly Detection` — applies `cpu_density_model` every 1 min, fires on `IsOutlier=1` or cpu > 95%
  - `CAIMP - Memory Anomaly Detection` — applies `mem_density_model` every 1 min, fires on `IsOutlier=1` or mem > 90%
  - `CAIMP - Disk Anomaly Detection` — threshold only (no model), fires on disk > 85%, every 5 min
  - `CAIMP - Network Traffic Forecast` — `StateSpaceForecast` 95% CI, fires on traffic outside bounds, every 5 min
- All searches use `caimp_webhook` alert action → `http://ai-orchestrator:8010/webhook/anomaly`
- Updated `splunk/README.md` — added anomaly detection table and verify command

### 2026-05-20 (Splunk module — Step 6)
- Created `splunk/savedsearches.conf` with 2 MLTK training searches:
  - `CAIMP - Train CPU Density Model` — fits `DensityFunction` on 7d of `system.cpu.utilization`, saves as `app:cpu_density_model`, runs weekly Sunday 02:00 UTC
  - `CAIMP - Train Memory Density Model` — same pattern for `system.memory.utilization`, saves as `app:mem_density_model`, runs weekly Sunday 03:00 UTC
- Updated `splunk/README.md` — added MLTK training section with manual first-run instructions and verify commands

### 2026-05-20 (Splunk module — Step 5)
- Created `services/splunk-hec-bridge/` — new Python/FastAPI service (port 4317)
  - `main.py` — receives OTLP protobuf or JSON, translates to Splunk HEC batch format, POSTs to `caimp_metrics` index; writes live metric values to Redis (TTL 90s) after each successful HEC post; handles `/v1/metrics` and `/v1/logs`
  - `requirements.txt` — fastapi, uvicorn, httpx, opentelemetry-proto, protobuf, redis[asyncio]
  - `Dockerfile` — python:3.11-slim, port 4317
- Added `splunk-hec-bridge` service to `docker-compose.yml` under `profiles: [splunk]` (disabled by default; enable by running `docker compose --profile splunk up`)
- Port conflict note: otelcol also uses port 4317 — disable otelcol before activating this service (handled in Step 21)

### 2026-05-20 (Splunk module — Step 4)
- Added `splunk/collections.conf` — KV Store schema for `caimp_baselines` lookup table (9 fields: host, org_id, metric_name, avg/stddev/min/max/p5/p95 + computed_at)
- Added `CAIMP - 24h Baseline Compute` search to `splunk/rollup_searches.conf` — runs every 5 min, computes rolling 24h statistics per host+metric, writes to `caimp_baselines` KV Store
- Updated `splunk/README.md` — added KV Store setup section with copy path, verify command, and Python usage example

### 2026-05-20 (Splunk module — Step 3)
- Added `splunk/rollup_searches.conf` — 3 scheduled SPL searches that aggregate raw metrics into summary indexes:
  - 5-min rollup: runs every 5 min, writes `avg/max/min/count` to `caimp_metrics_5m`
  - 1-hour rollup: runs every hour at :05, adds `stddev` to `caimp_metrics_1h`
  - 1-day rollup: runs daily at 01:00 UTC, adds `p95` to `caimp_metrics_1d`
- Updated `splunk/README.md` — added rollup schedule table and verify command

### 2026-05-20 (Splunk module — Step 1)
- Added `splunk/indexes.conf` — 7 indexes: `caimp_metrics` (metric, 7d raw), `caimp_logs`, `caimp_anomalies`, `caimp_ai` (90d), `caimp_metrics_5m` (90d), `caimp_metrics_1h` (1y), `caimp_metrics_1d` (3y)
- Added `splunk/inputs.conf` — 3 HEC token stanzas for metrics, logs, and AI writeback (tokens must be replaced with real values from Splunk Settings → Data Inputs → HEC)
- Updated `splunk/README.md` — added index reference table and HEC token creation instructions

### 2026-05-20 (Splunk module — Step 0)
- Created `splunk/` directory with Splunk configuration files
- Added `splunk/transforms.conf` — declares `caimp_metric_schema` dimension/measure schema so `mstats` queries work on the `caimp_metrics` index
- Added `splunk/props.conf` — binds schema to `caimp:metrics` sourcetype; sets JSON parsing, timestamp format (`%s%3N`), no line-merge
- Added `splunk/README.md` — full installation guide: file copy locations, HEC token creation, verify commands, KV Store setup, rollup index verification

### 2026-05-20 (CAIMP v2 baseline)
- Added **Forecast Engine** service with Holt-Winters predictions and LLM narratives
- Added **forecast accuracy feedback loop** — `server_forecasts` extended with `evaluated_at`, `actual_mae`, `accuracy_score`, `nats_published` columns (migration 000010)
- Added **FORECASTS** NATS stream and `ForecastCritical` message model
- Added `GET /forecasts` endpoint in Query API
- Added **PDF Report** endpoint (`GET /reports/pdf`) with 6-section ReportLab report
- Added **Export PDF** button to Dashboard server cards and Server Detail page header
- Added `reportlab>=4.2.0` to Query API dependencies
