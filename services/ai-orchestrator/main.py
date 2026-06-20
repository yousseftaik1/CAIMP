"""
CAIMP AI Orchestrator — conversational chat endpoint.

Provides the SSE chat endpoint used by the floating chat panel in the
frontend. Classifies user intent, gathers context from the database,
calls Ollama, and streams the response token by token.

POST /chat  → StreamingResponse (text/event-stream)
GET  /health
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import asyncpg
import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from jose import JWTError, jwt
from pydantic import BaseModel

from chat import classify_intent, gather_chat_context, build_chat_prompt, stream_ollama

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","service":"ai-orchestrator","event":"%(message)s"}',
)
log = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b-instruct-q4_K_M")
JWT_SECRET = os.environ.get("JWT_SECRET", "")

db_pool: asyncpg.Pool | None = None
http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool, http_client
    db_pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=2,
        max_size=10,
        command_timeout=30,
        init=lambda conn: conn.execute("SET ROLE caimp_service"),
    )
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5, read=90, write=10, pool=5)
    )
    log.info("AI Orchestrator started (chat mode)")
    yield
    await db_pool.close()
    await http_client.aclose()


app = FastAPI(title="CAIMP AI Orchestrator", version="2.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


# ── Auth helper ───────────────────────────────────────────────────────────────


def _get_org(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        payload = jwt.decode(authorization[7:], JWT_SECRET, algorithms=["HS256"])
        return payload.get("org_id")
    except JWTError:
        return None


# ── Chat request model ────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str
    host_hint: str | None = None
    org_id: str | None = None  # sent by the frontend as fallback
    # frontend calls this field conversation_history; accept both names
    history: list[dict] = []
    conversation_history: list[dict] = []

    def effective_history(self) -> list[dict]:
        return self.history or self.conversation_history


# ── Chat endpoint ─────────────────────────────────────────────────────────────


@app.post("/chat")
async def chat(
    req: ChatRequest,
    authorization: str | None = Header(default=None),
):
    """
    Stream an AI response to a natural-language question.

    Events emitted:
      data: {"type":"intent","intent":"<name>"}
      data: {"type":"token","content":"<word>"}
      data: {"type":"done"}
    """
    # Prefer JWT org_id; fall back to body-supplied org_id (used by the frontend)
    org_id = _get_org(authorization) or req.org_id
    if JWT_SECRET and not org_id:
        raise HTTPException(status_code=401, detail="Missing or invalid Bearer token")

    intent, entities = classify_intent(req.message, req.host_hint)
    context = await gather_chat_context(
        intent, entities, org_id or "", db_pool, splunk=None
    )
    prompt = build_chat_prompt(req.message, req.effective_history(), context, intent)

    async def event_stream():
        yield f'data: {{"type":"intent","intent":"{intent}"}}\n\n'

        # Feed Ollama tokens into a queue so we can interleave keep-alive
        # comments while waiting for slow CPU inference.
        q: asyncio.Queue[str | None] = asyncio.Queue()

        async def _feed() -> None:
            try:
                async for token in stream_ollama(
                    prompt, http_client, OLLAMA_URL, OLLAMA_MODEL
                ):
                    await q.put(token)
            finally:
                await q.put(None)  # sentinel

        task = asyncio.create_task(_feed())
        try:
            while True:
                try:
                    token = await asyncio.wait_for(q.get(), timeout=5.0)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if token is None:
                    break
                safe = token.replace('"', '\\"').replace("\n", "\\n")
                yield f'data: {{"type":"token","content":"{safe}"}}\n\n'
        finally:
            task.cancel()

        yield 'data: {"type":"done"}\n\n'

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@app.get("/health")
def health():
    return {"status": "ok", "service": "ai-orchestrator"}
