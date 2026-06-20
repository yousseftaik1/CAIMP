"""
GET /dashboard/summary — Answers-first dashboard view.

Returns a structured summary that directly answers:
  "Is anything broken, and if so, what do I do?"

Aggregates from: servers, anomalies, forecasts, ai_explanations, root_cause_analyses.
Cached 30 seconds in Redis.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import get_current_user
from ..db import get_tenant_conn

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_CACHE_TTL = 30  # seconds


# ── Response models ───────────────────────────────────────────────────────────


class PotentialIssue(BaseModel):
    server_id: str
    server_name: str
    type: str  # 'forecast_risk' | 'anomaly_cluster' | 'root_cause' | 'high_usage'
    title: str
    detail: str
    severity: str  # 'critical' | 'warning' | 'info'


class RecommendedAction(BaseModel):
    priority: int
    server_name: str
    action: str
    reason: str


class ServerHealth(BaseModel):
    id: str
    name: str
    hostname: str
    status: str
    cpu_pct: float | None
    ram_pct: float | None
    disk_pct: float | None
    issues_24h: int


class DashboardSummary(BaseModel):
    overall_status: str  # 'healthy' | 'warning' | 'critical'
    overall_message: str
    server_count: int
    online_count: int
    servers: list[ServerHealth]
    potential_issues: list[PotentialIssue]
    recommended_actions: list[RecommendedAction]
    generated_at: str


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.get("/summary", response_model=DashboardSummary)
async def dashboard_summary(user=Depends(get_current_user)):
    """
    Aggregated answers-first view. Powers the new default dashboard.
    Combines forecasts, anomaly clusters, AI recommendations, and root-cause analyses
    into a plain-language summary with ordered action items.
    """
    async with get_tenant_conn(user.org_id) as conn:
        return await _build_summary(conn, user.org_id)


async def _build_summary(conn, org_id: str) -> DashboardSummary:
    now = datetime.now(tz=timezone.utc)
    since_5m = now - timedelta(minutes=5)
    since_24h = now - timedelta(hours=24)

    # ── 1. Servers ────────────────────────────────────────────────────────────
    servers_raw = await conn.fetch(
        "SELECT id, name, hostname, status FROM servers WHERE org_id = $1::uuid ORDER BY name",
        org_id,
    )
    server_ids = [str(r["id"]) for r in servers_raw]

    # Latest metrics per server
    srv_metrics: dict[str, dict] = {
        sid: {"cpu_pct": None, "ram_pct": None, "disk_pct": None} for sid in server_ids
    }
    if server_ids:
        m_rows = await conn.fetch(
            """
            SELECT DISTINCT ON (server_id, metric_name) server_id, metric_name, value
            FROM metrics
            WHERE org_id = $1::uuid
              AND metric_name = ANY($2::text[])
              AND time >= $3
            ORDER BY server_id, metric_name, time DESC
            """,
            org_id,
            [
                "system.cpu.utilization",
                "system.memory.utilization",
                "system.filesystem.utilization",
            ],
            since_5m,
        )
        _key_map = {
            "system.cpu.utilization": "cpu_pct",
            "system.memory.utilization": "ram_pct",
            "system.filesystem.utilization": "disk_pct",
        }
        for mr in m_rows:
            sid = str(mr["server_id"])
            key = _key_map.get(mr["metric_name"])
            if sid in srv_metrics and key:
                srv_metrics[sid][key] = round(float(mr["value"]) * 100, 1)

    # Anomaly counts per server (24h)
    an_counts: dict[str, int] = {sid: 0 for sid in server_ids}
    if server_ids:
        an_rows = await conn.fetch(
            "SELECT server_id, count(*) AS cnt FROM anomaly_events "
            "WHERE org_id = $1::uuid AND time >= $2 GROUP BY server_id",
            org_id,
            since_24h,
        )
        for ar in an_rows:
            sid = str(ar["server_id"])
            if sid in an_counts:
                an_counts[sid] = int(ar["cnt"])

    # Servers with metrics in the last 24h — only these get issues raised
    active_server_ids: set[str] = set()
    if server_ids:
        active_rows = await conn.fetch(
            "SELECT DISTINCT server_id FROM metrics WHERE org_id = $1::uuid AND time >= $2",
            org_id,
            since_24h,
        )
        active_server_ids = {str(r["server_id"]) for r in active_rows}

    # Only show servers that have sent metrics in the last 5 minutes
    servers_out = [
        ServerHealth(
            id=str(r["id"]),
            name=r["name"],
            hostname=r["hostname"],
            status=r["status"],
            cpu_pct=srv_metrics[str(r["id"])]["cpu_pct"],
            ram_pct=srv_metrics[str(r["id"])]["ram_pct"],
            disk_pct=srv_metrics[str(r["id"])]["disk_pct"],
            issues_24h=an_counts[str(r["id"])],
        )
        for r in servers_raw
        if str(r["id"]) in active_server_ids
        or srv_metrics[str(r["id"])]["cpu_pct"] is not None
    ]
    server_name_map = {str(r["id"]): r["name"] for r in servers_raw}
    online_count = sum(1 for r in servers_raw if r["status"] == "online")

    # ── 2. Potential issues ───────────────────────────────────────────────────
    issues: list[PotentialIssue] = []
    actions: list[RecommendedAction] = []

    # 2a. Forecasts at risk (breach within 24h)
    fc_rows = await conn.fetch(
        """
        SELECT DISTINCT ON (server_id, metric_name)
            server_id, metric_name, trend_slope, time_to_critical, forecast_points
        FROM server_forecasts
        WHERE org_id = $1::uuid
        ORDER BY server_id, metric_name, forecasted_at DESC
        """,
        org_id,
    )
    _metric_label = {
        "cpu_percent": "CPU",
        "memory_percent": "Memory",
        "disk_percent": "Disk",
        "system.cpu.utilization": "CPU",
        "system.memory.utilization": "Memory",
        "system.filesystem.utilization": "Disk",
    }
    for fc in fc_rows:
        if str(fc["server_id"]) not in active_server_ids:
            continue  # skip seeded forecasts for servers that never had an agent
        ttc = fc["time_to_critical"]
        name = server_name_map.get(str(fc["server_id"]), str(fc["server_id"]))
        ml = _metric_label.get(fc["metric_name"], fc["metric_name"])
        slope = fc["trend_slope"] or 0.0
        pts = fc["forecast_points"] or []
        if isinstance(pts, str):
            import json as _json

            pts = _json.loads(pts)
        p24 = f"{pts[23]['predicted'] * 100:.0f}%" if len(pts) >= 24 else "?"

        if ttc is not None and ttc <= 6:
            h = int(ttc)
            issues.append(
                PotentialIssue(
                    server_id=str(fc["server_id"]),
                    server_name=name,
                    type="forecast_risk",
                    title=f"{name}: {ml} will hit critical in ~{h} hour{'s' if h != 1 else ''}",
                    detail=f"Predicted to reach 90% in {h}h. Currently rising — needs attention now.",
                    severity="critical",
                )
            )
            actions.append(
                RecommendedAction(
                    priority=1,
                    server_name=name,
                    action=f"Investigate {ml.lower()} usage on {name} immediately",
                    reason=f"Forecast shows critical threshold breach in ~{h} hour{'s' if h != 1 else ''}",
                )
            )
        elif ttc is not None and ttc <= 24:
            h = int(ttc)
            issues.append(
                PotentialIssue(
                    server_id=str(fc["server_id"]),
                    server_name=name,
                    type="forecast_risk",
                    title=f"{name}: {ml} reaching {p24} by tomorrow",
                    detail=f"Trending upward — expected to hit 90% in ~{h} hours if nothing changes.",
                    severity="warning",
                )
            )
            actions.append(
                RecommendedAction(
                    priority=2,
                    server_name=name,
                    action=f"Plan to reduce {ml.lower()} on {name} within the next {h} hours",
                    reason=f"At current trend, {ml} will breach critical threshold by tomorrow",
                )
            )
        elif slope > 0.003:
            issues.append(
                PotentialIssue(
                    server_id=str(fc["server_id"]),
                    server_name=name,
                    type="forecast_risk",
                    title=f"{name}: {ml} is climbing — watch this",
                    detail=f"Not critical yet, but rising steadily. Predicted at {p24} in 24h.",
                    severity="info",
                )
            )

    # 2b. High anomaly clusters — server with 5+ anomalies in 24h
    for srv in servers_out:
        if srv.issues_24h >= 5:
            issues.append(
                PotentialIssue(
                    server_id=srv.id,
                    server_name=srv.name,
                    type="anomaly_cluster",
                    title=f"{srv.name}: {srv.issues_24h} unusual readings in the last 24 hours",
                    detail="Multiple anomalies suggest something is wrong — may need investigation.",
                    severity="warning" if srv.issues_24h < 10 else "critical",
                )
            )
            actions.append(
                RecommendedAction(
                    priority=2,
                    server_name=srv.name,
                    action=f"Check the anomaly log for {srv.name}",
                    reason=f"{srv.issues_24h} anomalies detected in the last 24 hours",
                )
            )

    # 2c. Root-cause analyses (recent, from correlation engine)
    try:
        rca_rows = await conn.fetch(
            """
            SELECT r.id, r.server_id, r.likely_cause, r.confidence, r.narrative,
                   r.recommended_actions, r.created_at
            FROM   root_cause_analyses r
            WHERE  r.org_id = $1::uuid
              AND  r.created_at >= $2
            ORDER  BY r.confidence DESC, r.created_at DESC
            LIMIT  5
            """,
            org_id,
            since_24h,
        )
        for rca in rca_rows:
            name = server_name_map.get(str(rca["server_id"]), str(rca["server_id"]))
            if rca["confidence"] >= 0.5:
                issues.append(
                    PotentialIssue(
                        server_id=str(rca["server_id"]),
                        server_name=name,
                        type="root_cause",
                        title=f"{name}: AI found likely cause — {rca['likely_cause']}",
                        detail=rca["narrative"][:180] + "…"
                        if len(rca["narrative"]) > 180
                        else rca["narrative"],
                        severity="warning",
                    )
                )
                rca_actions = rca["recommended_actions"] or []
                if isinstance(rca_actions, str):
                    import json as _json

                    rca_actions = _json.loads(rca_actions)
                for ra in rca_actions[:2]:
                    actions.append(
                        RecommendedAction(
                            priority=ra.get("priority", 3),
                            server_name=name,
                            action=ra.get("action", ""),
                            reason=ra.get("reason", ""),
                        )
                    )
    except Exception:
        pass  # root_cause_analyses table may not exist yet (migration pending)

    # 2d. Latest AI recommendations from ai_explanations
    ai_rows = await conn.fetch(
        """
        SELECT server_id, recommended_action, severity
        FROM   ai_explanations
        WHERE  org_id = $1::uuid
          AND  created_at >= $2
          AND  recommended_action IS NOT NULL
          AND  recommended_action != ''
        ORDER  BY created_at DESC
        LIMIT  5
        """,
        org_id,
        since_24h,
    )
    for ai in ai_rows:
        name = server_name_map.get(str(ai["server_id"]), str(ai["server_id"]))
        if not any(a.server_name == name for a in actions):
            actions.append(
                RecommendedAction(
                    priority=3 if ai["severity"] != "critical" else 1,
                    server_name=name,
                    action=ai["recommended_action"],
                    reason=f"AI-recommended action based on {ai['severity']} anomaly on {name}",
                )
            )

    # 2e. Recent critical anomalies (last 1h) — show immediately on the dashboard
    since_1h = now - timedelta(hours=1)
    if active_server_ids:
        crit_rows = await conn.fetch(
            """
            SELECT DISTINCT ON (ae.server_id, ae.metric_name)
                ae.id, ae.server_id, ae.metric_name, ae.value, ae.time, ae.incident_id,
                ax.explanation, ax.recommended_action
            FROM   anomaly_events ae
            LEFT   JOIN ai_explanations ax
                       ON  ax.server_id   = ae.server_id
                       AND ax.org_id      = ae.org_id
                       AND ax.anomaly_type = ae.metric_name
                       AND ax.created_at  >= ae.time - interval '10 minutes'
                       AND ax.created_at  <= ae.time + interval '10 minutes'
            WHERE  ae.org_id = $1::uuid
              AND  ae.severity = 'critical'
              AND  ae.time >= $2
            ORDER  BY ae.server_id, ae.metric_name, ae.time DESC
            """,
            org_id,
            since_1h,
        )
        _ml = {
            "system.cpu.utilization": "CPU",
            "system.memory.utilization": "Memory",
            "system.filesystem.utilization": "Disk",
        }
        seen_crit: set[str] = set()
        for cr in crit_rows:
            sid = str(cr["server_id"])
            if sid not in active_server_ids:
                continue
            key = f"{sid}:{cr['metric_name']}"
            if key in seen_crit:
                continue
            seen_crit.add(key)
            name = server_name_map.get(sid, sid)
            ml = _ml.get(cr["metric_name"], cr["metric_name"])
            expl = cr["explanation"] or "AI analysis in progress…"
            issues.append(
                PotentialIssue(
                    server_id=sid,
                    server_name=name,
                    type="anomaly_cluster",
                    title=f"{name}: {ml} critical — {cr['value'] * 100:.0f}%",
                    detail=expl[:180],
                    severity="critical",
                )
            )
            actions.append(
                RecommendedAction(
                    priority=1,
                    server_name=name,
                    action=cr["recommended_action"]
                    or f"Investigate {ml.lower()} on {name} immediately",
                    reason=f"Critical {ml} anomaly detected at {cr['value'] * 100:.0f}%",
                )
            )

    # ── 3. Deduplicate and sort ───────────────────────────────────────────────
    # Only show critical issues on the dashboard
    issues = [i for i in issues if i.severity == "critical"]
    # Sort issues: critical first, then warning, then info
    _sev_order = {"critical": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda x: _sev_order.get(x.severity, 3))
    issues = issues[:8]  # cap at 8 issues

    # Sort actions by priority (deduplicate by server+action text)
    seen_actions: set[str] = set()
    deduped_actions: list[RecommendedAction] = []
    for a in sorted(actions, key=lambda x: x.priority):
        key = f"{a.server_name}:{a.action[:40]}"
        if key not in seen_actions and a.action:
            seen_actions.add(key)
            deduped_actions.append(a)
    deduped_actions = deduped_actions[:6]
    # Re-number priorities sequentially
    for i, a in enumerate(deduped_actions, 1):
        a.priority = i

    # ── 4. Overall status ─────────────────────────────────────────────────────
    has_critical = any(i.severity == "critical" for i in issues)
    has_warning = any(i.severity == "warning" for i in issues)
    # Only count a server as offline if it ever had an active agent
    any_offline = any(
        r["status"] in ("offline", "degraded") and str(r["id"]) in active_server_ids
        for r in servers_raw
    )

    if has_critical or any_offline:
        overall_status = "critical"
        overall_message = f"{sum(1 for i in issues if i.severity == 'critical')} critical issue(s) need your attention now."
    elif has_warning:
        overall_status = "warning"
        overall_message = f"{len(issues)} potential issue(s) detected — nothing is broken yet, but worth a look."
    else:
        overall_status = "healthy"
        overall_message = f"All {len(servers_raw)} server(s) look healthy. No action needed right now."

    return DashboardSummary(
        overall_status=overall_status,
        overall_message=overall_message,
        server_count=len(servers_raw),
        online_count=online_count,
        servers=servers_out,
        potential_issues=issues,
        recommended_actions=deduped_actions,
        generated_at=now.isoformat(),
    )
