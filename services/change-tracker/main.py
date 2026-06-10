"""
CAIMP Change Tracker — port 8011

Receives change events from:
  - GitHub / GitLab / Bitbucket webhooks  (POST /webhooks/github, /webhooks/gitlab)
  - Docker daemon events from agents      (POST /ingest/docker)
  - Generic agent events                  (POST /ingest)

Writes to change_events (TimescaleDB) and publishes change.detected.{org_id} to NATS.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

import asyncpg
import nats
import uvicorn
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("change-tracker")

DATABASE_URL  = os.getenv("DATABASE_URL", "")
NATS_URL      = os.getenv("NATS_URL", "nats://nats:4222")
NATS_USER     = os.getenv("NATS_USER", "caimp")
NATS_PASSWORD = os.getenv("NATS_PASSWORD", "")
JWT_SECRET    = os.getenv("JWT_SECRET", "")
GH_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")
PORT          = int(os.getenv("PORT", "8011"))

app = FastAPI(title="CAIMP Change Tracker", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_pool: asyncpg.Pool | None = None
_nc: Any = None
_js: Any = None


# ── Lifecycle ─────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    global _pool, _nc, _js
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    log.info("PostgreSQL pool ready")
    creds = {}
    if NATS_USER and NATS_PASSWORD:
        creds = {"user": NATS_USER, "password": NATS_PASSWORD}
    try:
        _nc = await nats.connect(NATS_URL, **creds, connect_timeout=5)
        _js = _nc.jetstream()
        log.info("NATS connected")
    except Exception as exc:
        log.warning("NATS unavailable (%s) — will skip publishing", exc)


@app.on_event("shutdown")
async def shutdown():
    if _pool:  await _pool.close()
    if _nc and not _nc.is_closed:  await _nc.drain()


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _org_id_from_token(token: str) -> str | None:
    """Extract org_id from JWT without full validation (change-tracker is internal)."""
    try:
        from jose import jwt as jose_jwt
        payload = jose_jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload.get("org_id")
    except Exception:
        return None


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    return authorization[7:]


# ── Core write ────────────────────────────────────────────────────────────────

async def _save_change(
    org_id: str,
    server_id: str | None,
    change_type: str,
    source: str,
    actor: str | None,
    description: str | None,
    payload: dict,
    git_sha: str | None = None,
    image_sha: str | None = None,
    occurred_at: datetime | None = None,
) -> str:
    occurred_at = occurred_at or datetime.now(tz=timezone.utc)
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO change_events
              (org_id, server_id, occurred_at, change_type, source,
               actor, description, payload, git_sha, image_sha)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING id
            """,
            org_id, server_id, occurred_at, change_type, source,
            actor, description, json.dumps(payload), git_sha, image_sha,
        )
    change_id = str(row["id"])
    if _js:
        try:
            msg = json.dumps({
                "id":          change_id,
                "org_id":      org_id,
                "server_id":   server_id,
                "occurred_at": occurred_at.isoformat(),
                "change_type": change_type,
                "source":      source,
                "description": description,
            }).encode()
            await _js.publish(f"change.detected.{org_id}", msg)
        except Exception as exc:
            log.warning("NATS publish failed: %s", exc)
    log.info("change_event[%s] %s via %s on server=%s", change_id, change_type, source, server_id)
    return change_id


# ── Models ────────────────────────────────────────────────────────────────────

class GenericChangeEvent(BaseModel):
    server_id:   str | None = None
    change_type: str
    source:      str = "agent"
    actor:       str | None = None
    description: str | None = None
    payload:     dict = {}
    git_sha:     str | None = None
    image_sha:   str | None = None
    occurred_at: datetime | None = None


class DockerEvent(BaseModel):
    server_id:  str | None = None
    event_type: str          # start | stop | restart | pull | die
    image:      str | None = None
    container:  str | None = None
    image_sha:  str | None = None
    occurred_at: datetime | None = None


# ── Routes ────────────────────────────────────────────────────────────────────

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok", "service": "change-tracker"}


@router.post("/ingest", status_code=202)
async def ingest_generic(
    evt: GenericChangeEvent,
    authorization: str | None = Header(default=None),
):
    """Generic change event from the monitoring agent."""
    token  = _bearer(authorization)
    org_id = _org_id_from_token(token)
    if not org_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    change_id = await _save_change(
        org_id=org_id,
        server_id=evt.server_id,
        change_type=evt.change_type,
        source=evt.source,
        actor=evt.actor,
        description=evt.description,
        payload=evt.payload,
        git_sha=evt.git_sha,
        image_sha=evt.image_sha,
        occurred_at=evt.occurred_at,
    )
    return {"change_id": change_id}


@router.post("/ingest/docker", status_code=202)
async def ingest_docker(
    evt: DockerEvent,
    authorization: str | None = Header(default=None),
):
    """Docker daemon event from the monitoring agent's docker-events collector."""
    token  = _bearer(authorization)
    org_id = _org_id_from_token(token)
    if not org_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    type_map = {
        "pull":    "docker_pull",
        "start":   "restart",
        "restart": "restart",
        "stop":    "restart",
        "die":     "restart",
    }
    change_type = type_map.get(evt.event_type, "restart")
    desc = f"Docker {evt.event_type}: {evt.container or evt.image or 'unknown'}"

    change_id = await _save_change(
        org_id=org_id,
        server_id=evt.server_id,
        change_type=change_type,
        source="docker_events",
        actor="docker",
        description=desc,
        payload={"event_type": evt.event_type, "image": evt.image, "container": evt.container},
        image_sha=evt.image_sha,
        occurred_at=evt.occurred_at,
    )
    return {"change_id": change_id}


@router.post("/webhooks/github", status_code=202)
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
):
    """GitHub webhook — push, deployment, workflow_run events."""
    body = await request.body()

    # Verify signature if secret is configured
    if GH_WEBHOOK_SECRET:
        expected = "sha256=" + hmac.new(
            GH_WEBHOOK_SECRET.encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, x_hub_signature_256 or ""):
            raise HTTPException(status_code=401, detail="Invalid GitHub signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Extract org_id from custom header or repository description (configurable)
    # For simplicity, use a query param or default org — in production configure per-repo webhook
    org_id = request.query_params.get("org_id")
    if not org_id:
        return {"status": "skipped", "reason": "org_id query param required"}

    event = x_github_event or "push"
    repo  = payload.get("repository", {}).get("full_name", "unknown")
    sha   = payload.get("after") or payload.get("head_commit", {}).get("id")
    actor = payload.get("pusher", {}).get("name") or payload.get("sender", {}).get("login")

    if event == "push":
        branch = payload.get("ref", "").replace("refs/heads/", "")
        desc   = f"Git push to {repo}/{branch} by {actor}"
        change_type = "deployment"
    elif event == "deployment":
        env    = payload.get("deployment", {}).get("environment", "unknown")
        desc   = f"GitHub deployment to {env} on {repo} by {actor}"
        change_type = "deployment"
    elif event == "workflow_run":
        status = payload.get("workflow_run", {}).get("conclusion", "unknown")
        name   = payload.get("workflow_run", {}).get("name", "workflow")
        desc   = f"GitHub Actions {name} {status} on {repo}"
        change_type = "deployment"
    else:
        return {"status": "skipped", "event": event}

    change_id = await _save_change(
        org_id=org_id,
        server_id=None,
        change_type=change_type,
        source="github_webhook",
        actor=actor,
        description=desc,
        payload=payload,
        git_sha=sha,
    )
    return {"change_id": change_id, "event": event}


@router.post("/webhooks/gitlab", status_code=202)
async def gitlab_webhook(
    request: Request,
    x_gitlab_event: str | None = Header(default=None),
    x_gitlab_token: str | None = Header(default=None),
):
    """GitLab webhook — push, pipeline, deployment events."""
    body = await request.body()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    org_id = request.query_params.get("org_id")
    if not org_id:
        return {"status": "skipped", "reason": "org_id query param required"}

    event = x_gitlab_event or ""
    sha   = payload.get("checkout_sha") or payload.get("commit", {}).get("id")
    actor = payload.get("user_username") or payload.get("user_name")

    if "Push Hook" in event:
        branch = payload.get("ref", "").replace("refs/heads/", "")
        desc   = f"GitLab push to {payload.get('project', {}).get('name','?')}/{branch}"
        change_type = "deployment"
    elif "Pipeline Hook" in event:
        status = payload.get("object_attributes", {}).get("status", "unknown")
        desc   = f"GitLab pipeline {status}"
        change_type = "deployment"
    elif "Deployment Hook" in event:
        env    = payload.get("environment", "unknown")
        desc   = f"GitLab deployment to {env}"
        change_type = "deployment"
    else:
        return {"status": "skipped", "event": event}

    change_id = await _save_change(
        org_id=org_id, server_id=None,
        change_type=change_type, source="gitlab_webhook",
        actor=actor, description=desc, payload=payload, git_sha=sha,
    )
    return {"change_id": change_id, "event": event}


app.include_router(router)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, log_level="info")
