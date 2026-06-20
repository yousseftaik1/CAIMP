from __future__ import annotations

import logging

import asyncpg

from .ollama_client import embed

log = logging.getLogger(__name__)


def _vec_literal(embedding: list[float]) -> str:
    return "[" + ",".join(str(v) for v in embedding) + "]"


async def retrieve_similar(
    pool: asyncpg.Pool,
    org_id: str,
    query_text: str,
    top_k: int = 3,
) -> list[dict]:
    """Cosine-similarity search over rag_documents for the org."""
    try:
        vec = await embed(query_text)
    except Exception as exc:
        log.warning("Embedding failed, skipping RAG: %s", exc)
        return []

    rows = await pool.fetch(
        """SELECT title, content, doc_type
           FROM rag_documents
           WHERE org_id = $1::uuid AND embedding IS NOT NULL
           ORDER BY embedding <=> $2::vector
           LIMIT $3""",
        org_id,
        _vec_literal(vec),
        top_k,
    )
    return [
        {"title": r["title"], "content": r["content"], "type": r["doc_type"]}
        for r in rows
    ]


async def store_incident(
    pool: asyncpg.Pool,
    org_id: str,
    incident_id: str,
    content: str,
) -> None:
    """Index a resolved incident for future RAG retrieval."""
    try:
        vec = await embed(content)
    except Exception as exc:
        log.warning("Embedding failed, skipping RAG store: %s", exc)
        return

    await pool.execute(
        """INSERT INTO rag_documents (org_id, doc_type, title, content, embedding)
           VALUES ($1::uuid, 'incident', $2, $3, $4::vector)""",
        org_id,
        f"Incident {incident_id[:16]}",
        content,
        _vec_literal(vec),
    )
