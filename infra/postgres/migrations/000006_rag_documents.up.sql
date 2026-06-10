-- RAG index: embeddings of past incident summaries and runbook docs.
-- Uses pgvector HNSW index for approximate nearest-neighbour search.
-- Embedding model: nomic-embed-text (768 dimensions).

CREATE TABLE rag_documents (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id      UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    doc_type    TEXT        NOT NULL CHECK (doc_type IN ('incident', 'runbook', 'server_profile')),
    source_id   UUID,                           -- incident_id / server_id / null
    title       TEXT,
    content     TEXT        NOT NULL,
    embedding   VECTOR(768),                    -- nomic-embed-text via Ollama
    metadata    JSONB       NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- HNSW index for cosine similarity search (best for embedding models)
CREATE INDEX ON rag_documents USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX ON rag_documents (org_id, doc_type);
CREATE INDEX ON rag_documents (source_id) WHERE source_id IS NOT NULL;
