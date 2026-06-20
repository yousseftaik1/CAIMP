"""
LLM Router — calls the appropriate language model for anomaly analysis.

Routing logic (evaluated in order):
  1. Look up org_config for the org: anthropic_api_key + use_cloud_llm flag.
  2. If severity=critical AND cloud LLM enabled AND API key present → Anthropic.
  3. Everything else (or Anthropic failure) → local Ollama.

Both callers return the raw text from the model (should be the JSON defined
in OUTPUT_SCHEMA). Validation happens in output_validator.py (Step 15).
"""

from __future__ import annotations

import logging
import os

import asyncpg
import httpx

log = logging.getLogger(__name__)

_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
_OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b-instruct-q4_K_M")

_ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_MODEL = "claude-sonnet-4-20250514"


# ── Ollama ────────────────────────────────────────────────────────────────────


async def call_ollama(
    prompt: str,
    http: httpx.AsyncClient,
    ollama_url: str = _OLLAMA_URL,
    model: str = _OLLAMA_MODEL,
) -> str:
    """
    POST to Ollama /api/generate with JSON-mode output.
    temperature=0.2 for deterministic analysis; num_predict=600 matches schema size.
    """
    resp = await http.post(
        f"{ollama_url}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_predict": 600,
            },
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json().get("response", "")


# ── Anthropic ─────────────────────────────────────────────────────────────────


async def call_anthropic(
    prompt: str,
    api_key: str,
    http: httpx.AsyncClient,
    model: str = _ANTHROPIC_MODEL,
) -> str:
    """
    POST to Anthropic Messages API.
    Returns the text content of the first content block.
    """
    resp = await http.post(
        _ANTHROPIC_API_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 600,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60.0,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


# ── Router ────────────────────────────────────────────────────────────────────


async def route_and_call(
    prompt: str,
    anomaly: dict,
    db: asyncpg.Connection,
    http: httpx.AsyncClient,
    ollama_url: str = _OLLAMA_URL,
    model: str = _OLLAMA_MODEL,
) -> tuple[str, str]:
    """
    Select the right LLM and call it.

    Returns (raw_response_text, provider) where provider is "anthropic" or "ollama".
    On Anthropic failure the function logs a warning and retries with Ollama —
    RAG + context are already assembled so the fallback is cheap.
    """
    severity = anomaly.get("severity", "low")
    org_id = anomaly.get("org_id", "")

    # ── look up per-org cloud-LLM config ──────────────────────────────────────
    api_key = None
    use_cloud = False
    try:
        row = await db.fetchrow(
            "SELECT anthropic_api_key, use_cloud_llm FROM org_config WHERE org_id = $1",
            org_id,
        )
        if row:
            api_key = row["anthropic_api_key"]
            use_cloud = bool(row["use_cloud_llm"])
    except Exception as exc:
        log.warning(f"org_config lookup failed (will use Ollama): {exc}")

    # ── route ─────────────────────────────────────────────────────────────────
    if severity == "critical" and use_cloud and api_key:
        try:
            log.info(f"Routing to Anthropic | org={org_id}")
            text = await call_anthropic(prompt, api_key, http)
            return text, "anthropic"
        except Exception as exc:
            log.warning(f"Anthropic call failed, falling back to Ollama: {exc}")

    log.info(f"Routing to Ollama | org={org_id} severity={severity}")
    text = await call_ollama(prompt, http, ollama_url=ollama_url, model=model)
    return text, "ollama"
