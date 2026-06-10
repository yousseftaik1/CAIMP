# =============================================================================
# CAIMP v2 — Demo Data Seed Script (PowerShell)
# Seeds realistic demo data and optionally fires a live AI pipeline test.
#
# Usage: .\scripts\seed_demo.ps1
# =============================================================================

$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host " CAIMP Demo Data Seeder" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: Inject demo SQL ───────────────────────────────────────────────────
Write-Host "[1/3] Seeding database with demo data..." -ForegroundColor Yellow

$sqlFile = Join-Path $PSScriptRoot "seed_demo.sql"
if (-not (Test-Path $sqlFile)) {
    Write-Host "ERROR: seed_demo.sql not found at $sqlFile" -ForegroundColor Red
    exit 1
}

Get-Content $sqlFile -Raw | docker exec -i caimp-postgres psql -U caimp -d caimp
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: SQL seed failed. Is caimp-postgres running?" -ForegroundColor Red
    Write-Host "Run: docker compose ps" -ForegroundColor Gray
    exit 1
}

Write-Host "[1/3] Database seeded." -ForegroundColor Green

# ── Step 2: Fire a live anomaly through the AI pipeline ───────────────────────
Write-Host ""
Write-Host "[2/3] Firing live anomaly webhook (this triggers the full AI pipeline)..." -ForegroundColor Yellow

$payload = @{
    host               = "web-01.prod.local"
    org_id             = "00000000-0000-0000-0000-000000000001"
    metric_name        = "system.cpu.utilization"
    anomaly_type       = "cpu_saturation"
    severity           = "high"
    value              = 0.91
    score              = 8.3
    timestamp          = (Get-Date -Format "o")
    splunk_search_name = "CAIMP_Demo_LiveTest"
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri "http://localhost:8010/webhook/anomaly" `
        -Method POST `
        -Body $payload `
        -ContentType "application/json" `
        -TimeoutSec 20
    $incidentId = $response.incident_id
    Write-Host "[2/3] Webhook accepted! incident_id = $incidentId" -ForegroundColor Green
    Write-Host "      The AI pipeline is now running in the background." -ForegroundColor Gray
    Write-Host "      It will fetch context, search RAG, call Ollama, validate, and store." -ForegroundColor Gray
} catch {
    Write-Host "[2/3] Webhook call failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "      This is OK — the SQL seed data is still loaded." -ForegroundColor Gray
    $incidentId = $null
}

# ── Step 3: Verify via Query API ──────────────────────────────────────────────
Write-Host ""
Write-Host "[3/3] Verifying data via Query API..." -ForegroundColor Yellow

# Login
try {
    $loginBody = @{ email = "admin@caimp.local"; password = "Admin1234!" } | ConvertTo-Json
    $loginResp = Invoke-RestMethod -Uri "http://localhost:8001/auth/login" `
        -Method POST -Body $loginBody -ContentType "application/json" -TimeoutSec 10
    $token = $loginResp.access_token
    Write-Host "  Login: OK" -ForegroundColor Green
} catch {
    Write-Host "  Login failed: $($_.Exception.Message)" -ForegroundColor Red
    $token = $null
}

# Count incidents
if ($token) {
    try {
        $headers = @{ Authorization = "Bearer $token" }
        $stats = Invoke-RestMethod -Uri "http://localhost:8002/incidents/stats" `
            -Headers $headers -TimeoutSec 10
        Write-Host "  Incidents total : $($stats.total)" -ForegroundColor Green
        Write-Host "  By severity     : critical=$($stats.by_severity.critical) high=$($stats.by_severity.high) medium=$($stats.by_severity.medium) low=$($stats.by_severity.low)" -ForegroundColor Green
    } catch {
        Write-Host "  Could not fetch incident stats: $($_.Exception.Message)" -ForegroundColor Red
    }

    # Count servers
    try {
        $servers = Invoke-RestMethod -Uri "http://localhost:8002/servers" `
            -Headers $headers -TimeoutSec 10
        Write-Host "  Servers         : $($servers.Count)" -ForegroundColor Green
    } catch {
        Write-Host "  Could not fetch servers: $($_.Exception.Message)" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host " Done! Open the dashboard:" -ForegroundColor Cyan
Write-Host "   React App  : http://localhost:3000" -ForegroundColor White
Write-Host "   Admin HTML : http://localhost:3000/admin.html" -ForegroundColor White
Write-Host "   Admin API  : http://localhost:8001/docs" -ForegroundColor White
Write-Host "   Query API  : http://localhost:8002/docs" -ForegroundColor White
Write-Host ""
Write-Host " Login: admin@caimp.local / Admin1234!" -ForegroundColor White
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

if ($incidentId) {
    Write-Host "Live incident $incidentId is processing." -ForegroundColor DarkGray
    Write-Host "Poll: http://localhost:8002/incidents/$incidentId" -ForegroundColor DarkGray
    Write-Host ""
}
