#!/usr/bin/env python3
"""
CAIMP Splunk integration smoke test.

Fires a test webhook at the ai-orchestrator and then polls the query-api until
the full pipeline (context → RAG → LLM → validate → store → cache → NATS)
completes.  Also exercises the runbook CRUD endpoints end-to-end.

Requires only Python 3.9+ stdlib — no extra packages needed.

Usage
-----
    python scripts/smoke_test_splunk.py [options]

Options
-------
    --ai-url    URL   ai-orchestrator base URL   (default: http://localhost:8010)
    --api-url   URL   query-api base URL         (default: http://localhost:8002)
    --admin-url URL   admin-api base URL         (default: http://localhost:8001)
    --org-id    UUID  organisation UUID          (default: 00000000-0000-0000-0000-000000000001)
    --email     STR   admin login email          (default: admin@caimp.local)
    --password  STR   admin login password       (default: Admin1234!)
    --timeout   INT   pipeline poll timeout (s)  (default: 120)
    --severity  STR   anomaly severity           (default: high)
    --no-color        disable ANSI colour output
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

# ── ANSI colours ──────────────────────────────────────────────────────────────

_USE_COLOR = sys.stdout.isatty()

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text

def ok(msg: str)   -> None: print(f"  {_c('32', '✓')} {msg}")
def fail(msg: str) -> None: print(f"  {_c('31', '✗')} {msg}", file=sys.stderr)
def info(msg: str) -> None: print(f"  {_c('2',  '·')} {msg}")
def hdr(msg: str)  -> None: print(f"\n{_c('1', msg)}")


# ── HTTP helpers (stdlib only) ────────────────────────────────────────────────

def _req(url: str, method: str = "GET", body: dict | None = None,
         token: str | None = None, timeout: int = 15) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req  = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read()
            return exc.code, (json.loads(raw) if raw else {})
        except Exception:
            return exc.code, {}
    except Exception as exc:
        return 0, {"_error": str(exc)}


def get(url: str, **kw)  -> tuple[int, Any]: return _req(url, "GET",    **kw)
def post(url: str, body: dict, **kw) -> tuple[int, Any]: return _req(url, "POST", body=body, **kw)
def put(url: str, body: dict, **kw)  -> tuple[int, Any]: return _req(url, "PUT",  body=body, **kw)

def delete(url: str, token: str | None = None, timeout: int = 10) -> int:
    code, _ = _req(url, "DELETE", token=token, timeout=timeout)
    return code


# ── checks ────────────────────────────────────────────────────────────────────

def _pass(failures: list[str], tag: str, cond: bool, msg_ok: str, msg_fail: str) -> bool:
    if cond:
        ok(msg_ok)
    else:
        fail(msg_fail)
        failures.append(tag)
    return cond


# ── main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ai-url",    default="http://localhost:8010")
    parser.add_argument("--api-url",   default="http://localhost:8002")
    parser.add_argument("--admin-url", default="http://localhost:8001")
    parser.add_argument("--org-id",    default="00000000-0000-0000-0000-000000000001")
    parser.add_argument("--email",     default="admin@caimp.local")
    parser.add_argument("--password",  default="Admin1234!")
    parser.add_argument("--timeout",   type=int, default=120,
                        help="seconds to wait for pipeline completion")
    parser.add_argument("--severity",  default="high",
                        choices=["low", "medium", "high", "critical"])
    parser.add_argument("--no-color",  action="store_true")
    args = parser.parse_args(argv)

    if args.no_color:
        global _USE_COLOR
        _USE_COLOR = False

    AI  = args.ai_url.rstrip("/")
    API = args.api_url.rstrip("/")
    ADM = args.admin_url.rstrip("/")

    failures: list[str] = []
    t0 = time.time()

    # ── 1. Health checks ──────────────────────────────────────────────────────
    hdr("1/7  Health checks")

    status, body = get(f"{AI}/health")
    _pass(failures, "ai-orchestrator health",
          status == 200 and body.get("status") == "ok",
          f"ai-orchestrator healthy  ({AI})",
          f"ai-orchestrator unreachable — status={status}  response={body}")

    status, body = get(f"{API}/health")
    _pass(failures, "query-api health",
          status == 200 and body.get("status") == "ok",
          f"query-api healthy        ({API})",
          f"query-api unreachable — status={status}  response={body}")

    # ── 2. Auth ───────────────────────────────────────────────────────────────
    hdr("2/7  Auth")

    token: str | None = None
    status, body = post(f"{ADM}/auth/login",
                        {"email": args.email, "password": args.password})
    if status == 200 and "access_token" in body:
        token = body["access_token"]
        ok(f"Login succeeded  (email={args.email})")
    else:
        info(f"Login failed (status={status}) — query-api calls may fail if JWT is enforced")
        failures.append("auth/login")

    # ── 3. Webhook ────────────────────────────────────────────────────────────
    hdr("3/7  Webhook  POST /webhook/anomaly")

    webhook_payload = {
        "host":               "smoke-test-host-01",
        "org_id":             args.org_id,
        "metric_name":        "system.cpu.utilization",
        "anomaly_type":       "cpu_saturation",
        "severity":           args.severity,
        "value":              0.93,
        "score":              8.7,
        "timestamp":          datetime.now(tz=timezone.utc).isoformat(),
        "splunk_search_name": "CAIMP_CPU_MLTK_SmokeTest",
    }
    info(
        f"host={webhook_payload['host']}  "
        f"type={webhook_payload['anomaly_type']}  "
        f"severity={webhook_payload['severity']}"
    )

    status, body = post(f"{AI}/webhook/anomaly", webhook_payload, timeout=20)
    incident_id: str | None = None
    if _pass(failures, "webhook POST",
             status == 202 and "incident_id" in body,
             f"Webhook accepted  →  incident_id={body.get('incident_id')}",
             f"Webhook rejected — status={status}  body={body}"):
        incident_id = body["incident_id"]

    if incident_id is None:
        hdr("Aborting — no incident_id to poll")
        return _summary(failures, t0)

    # ── 4. Pipeline completion poll ───────────────────────────────────────────
    hdr(f"4/7  Pipeline poll  (timeout={args.timeout}s)")

    deadline    = time.time() + args.timeout
    explanation: dict | None = None
    last_status: str | None  = None
    poll_start  = time.time()

    while time.time() < deadline:
        status, body = get(f"{API}/incidents/{incident_id}", token=token)

        if status == 200:
            expl        = body.get("explanation") or {}
            expl_status = expl.get("status")

            if expl_status != last_status:
                info(f"explanation.status = {expl_status or '(none yet)'}")
                last_status = expl_status

            if expl_status in ("complete", "error"):
                explanation = expl
                break

        elif status == 404:
            info("incident not yet visible in query-api, retrying…")
        else:
            info(f"query-api returned {status}, retrying…")

        time.sleep(3)

    elapsed = round(time.time() - poll_start, 1)

    if explanation is None:
        fail(f"Pipeline did not complete within {args.timeout}s")
        failures.append("pipeline timeout")
    elif explanation.get("status") == "error":
        _pass(failures, "pipeline status",
              False, "",
              f"Pipeline error after {elapsed}s: {explanation.get('error_message', '(no detail)')}")
    else:
        ok(f"Pipeline complete in {elapsed}s  (status=complete)")

    # ── 5. Explanation field validation ───────────────────────────────────────
    hdr("5/7  Explanation field validation")

    if explanation and explanation.get("status") == "complete":
        required_fields = [
            "severity", "explanation", "root_cause",
            "recommended_action", "confidence", "llm_provider",
        ]
        for field in required_fields:
            val = explanation.get(field)
            _pass(failures, f"explanation.{field}",
                  bool(val),
                  f"{field:<26}= {str(val)[:70]}",
                  f"{field} is missing or empty")

        queries = explanation.get("evidence_spl_queries") or []
        if isinstance(queries, list) and queries:
            ok(f"{'evidence_spl_queries':<26}= {len(queries)} quer{'y' if len(queries) == 1 else 'ies'}")
        else:
            info("evidence_spl_queries is empty "
                 "(expected when Splunk is not configured)")
    else:
        info("Skipping field validation — explanation not complete")

    # ── 6. Incidents stats ────────────────────────────────────────────────────
    hdr("6/7  GET /incidents/stats")

    status, body = get(f"{API}/incidents/stats", token=token)
    _pass(failures, "incidents/stats",
          status == 200 and "total" in body,
          f"total={body.get('total', '?')}  "
          f"by_severity={body.get('by_severity', {})}  "
          f"pending={body.get('pending_explanations', '?')}",
          f"Stats endpoint returned {status}: {body}")

    # ── 7. Runbook CRUD ───────────────────────────────────────────────────────
    hdr("7/7  Runbook CRUD round-trip")

    runbook_content = (
        "## Symptoms\n"
        "CPU utilization sustained above 90% for more than 5 minutes.\n\n"
        "## Diagnosis\n"
        "1. Identify top CPU consumers: `ps aux --sort=-%cpu | head -20`\n"
        "2. Check for runaway cron jobs: `crontab -l && journalctl -u cron --since -1h`\n"
        "3. Review recent deployments: `journalctl -u app.service --since -2h`\n\n"
        "## Remediation\n"
        "1. Kill or renice offending processes: `renice -n 10 <PID>`\n"
        "2. Scale horizontally if load is legitimate.\n"
        "3. Open an incident ticket if cause is unknown.\n"
    )

    runbook_id: str | None = None

    # Create
    status, body = post(
        f"{API}/runbooks",
        {
            "title":        "Smoke Test — CPU Saturation Runbook",
            "anomaly_type": "cpu_saturation",
            "content":      runbook_content,
        },
        token=token,
        timeout=30,
    )
    if _pass(failures, "runbook create",
             status == 200 and "id" in body,
             f"CREATE  id={body.get('id')}  "
             f"{'embedded' if body.get('has_embedding') else 'no embedding (Ollama unavailable)'}",
             f"CREATE failed — status={status}  body={body}"):
        runbook_id = body["id"]

    # Read
    if runbook_id:
        status, body = get(f"{API}/runbooks/{runbook_id}", token=token)
        _pass(failures, "runbook GET",
              status == 200 and body.get("id") == runbook_id,
              f"GET     title='{body.get('title', '')}'",
              f"GET failed — status={status}")

    # Update
    if runbook_id:
        status, body = put(
            f"{API}/runbooks/{runbook_id}",
            {"title": "Smoke Test — CPU Saturation Runbook (updated)"},
            token=token,
            timeout=30,
        )
        _pass(failures, "runbook PUT",
              status == 200 and "updated" in body.get("title", ""),
              f"PUT     title='{body.get('title', '')}'",
              f"PUT failed — status={status}  body={body}")

    # List with filter
    status, body = get(f"{API}/runbooks?anomaly_type=cpu_saturation", token=token)
    _pass(failures, "runbook list",
          status == 200 and isinstance(body, list) and len(body) >= 1,
          f"LIST    {len(body) if isinstance(body, list) else '?'} runbook(s) for cpu_saturation",
          f"LIST failed — status={status}")

    # Delete
    if runbook_id:
        code = delete(f"{API}/runbooks/{runbook_id}", token=token)
        _pass(failures, "runbook DELETE",
              code == 204,
              "DELETE  204 No Content",
              f"DELETE failed — status={code}")

        # Confirm gone
        status, _ = get(f"{API}/runbooks/{runbook_id}", token=token)
        _pass(failures, "runbook 404 after delete",
              status == 404,
              "GET after DELETE → 404 (confirmed gone)",
              f"Runbook still accessible after delete — status={status}")

    # ── Summary ───────────────────────────────────────────────────────────────
    return _summary(failures, t0)


def _summary(failures: list[str], t0: float) -> int:
    elapsed = round(time.time() - t0, 1)
    hdr("Summary")
    print(f"  Elapsed: {elapsed}s")
    if not failures:
        print(f"  {_c('32;1', 'All checks passed.')}")
        return 0
    print(f"  {_c('31;1', f'{len(failures)} check(s) failed:')}")
    for f in failures:
        print(f"    {_c('31', '–')} {f}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
