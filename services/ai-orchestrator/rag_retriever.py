"""
RAG Retriever — retrieves similar past incidents and matching runbooks
from pgvector before the LLM call.

Two sources:
  rag_documents — org-scoped embeddings of past incidents and general docs
  runbooks      — operator-written diagnosis guides, indexed by anomaly_type

Both use cosine similarity via pgvector (<=> operator).
Similarity thresholds: 0.6 for incidents, 0.55 for runbooks (slightly
lower because runbook titles may not closely match the anomaly signature).
"""
from __future__ import annotations

import logging

import asyncpg
import httpx

log = logging.getLogger(__name__)

_INCIDENT_SIMILARITY_THRESHOLD = 0.6
_RUNBOOK_SIMILARITY_THRESHOLD  = 0.55
_INCIDENT_LIMIT = 3
_RUNBOOK_LIMIT  = 2


# ── embedding ─────────────────────────────────────────────────────────────────

async def get_embedding(
    text: str,
    http: httpx.AsyncClient,
    ollama_url: str,
    embed_model: str,
) -> list[float]:
    """Call Ollama nomic-embed-text to get a 768-dim embedding vector."""
    resp = await http.post(
        f"{ollama_url}/api/embeddings",
        json={"model": embed_model, "prompt": text},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]


def _vec_literal(embedding: list[float]) -> str:
    """Format a float list as a pgvector literal string."""
    return "[" + ",".join(str(x) for x in embedding) + "]"


# ── retrieval ─────────────────────────────────────────────────────────────────

async def retrieve_rag_context(
    anomaly: dict,
    db: asyncpg.Connection,
    http: httpx.AsyncClient,
    ollama_url: str,
    embed_model: str,
) -> dict:
    """
    Embed the anomaly signature then query pgvector for similar incidents
    and relevant runbooks. Returns formatted text ready for prompt injection.

    On any failure (Ollama down, pgvector error) returns empty strings so
    the LLM call still proceeds — RAG is enhancement, not a hard requirement.
    """
    signature = (
        f"{anomaly.get('anomaly_type', '')} "
        f"{anomaly.get('metric_name', '')} "
        f"severity={anomaly.get('severity', '')}"
    )

    # ── embed ─────────────────────────────────────────────────────────────────
    try:
        embedding = await get_embedding(text=signature, http=http,
                                        ollama_url=ollama_url,
                                        embed_model=embed_model)
        vec = _vec_literal(embedding)
    except Exception as exc:
        log.warning(f"Embedding failed — skipping RAG: {exc}")
        return {
            "similar_incidents_text": "  (embedding unavailable)",
            "runbook_text":           "  (embedding unavailable)",
            "docs_used":              [],
        }

    # ── past incidents from rag_documents ────────────────────────────────────
    try:
        incident_rows = await db.fetch(
            f"""
            SELECT content, doc_type, source_id,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM rag_documents
            WHERE org_id = $2
              AND doc_type IN ('incident', 'runbook')
              AND 1 - (embedding <=> $1::vector) > $3
            ORDER BY embedding <=> $1::vector
            LIMIT $4
            """,
            vec,
            anomaly["org_id"],
            _INCIDENT_SIMILARITY_THRESHOLD,
            _INCIDENT_LIMIT,
        )
    except Exception as exc:
        log.warning(f"rag_documents query failed: {exc}")
        incident_rows = []

    # ── runbooks table ────────────────────────────────────────────────────────
    try:
        runbook_rows = await db.fetch(
            f"""
            SELECT content, title, anomaly_type,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM runbooks
            WHERE org_id = $2
              AND 1 - (embedding <=> $1::vector) > $3
            ORDER BY embedding <=> $1::vector
            LIMIT $4
            """,
            vec,
            anomaly["org_id"],
            _RUNBOOK_SIMILARITY_THRESHOLD,
            _RUNBOOK_LIMIT,
        )
    except Exception as exc:
        log.warning(f"runbooks query failed: {exc}")
        runbook_rows = []

    # ── format for prompt ─────────────────────────────────────────────────────
    incidents_text = "\n".join(
        f"  Past incident (similarity={r['similarity']:.2f}): "
        f"{r['content'][:300]}"
        for r in incident_rows
    ) or "  (no similar past incidents found)"

    runbooks_text = "\n".join(
        f"  Runbook '{r['title']}' (covers: {r['anomaly_type']}): "
        f"{r['content'][:300]}"
        for r in runbook_rows
    ) or "  (no matching runbooks found)"

    docs_used = [
        str(r["source_id"])
        for r in incident_rows
        if r.get("source_id")
    ]

    log.info(
        f"RAG retrieved | incidents={len(incident_rows)} "
        f"runbooks={len(runbook_rows)} "
        f"host={anomaly.get('host')} type={anomaly.get('anomaly_type')}"
    )

    return {
        "similar_incidents_text": incidents_text,
        "runbook_text":           runbooks_text,
        "docs_used":              docs_used,
    }
