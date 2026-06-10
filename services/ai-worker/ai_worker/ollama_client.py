from __future__ import annotations

import logging

import httpx

from .config import settings

log = logging.getLogger(__name__)

_EMBED_TIMEOUT = 30.0
_GENERATE_TIMEOUT = 180.0


async def embed(text: str) -> list[float]:
    async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=_EMBED_TIMEOUT) as client:
        resp = await client.post(
            "/api/embeddings",
            json={"model": settings.embed_model, "prompt": text},
        )
        resp.raise_for_status()
        return resp.json()["embedding"]


async def generate(prompt: str) -> str:
    async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=_GENERATE_TIMEOUT) as client:
        resp = await client.post(
            "/api/generate",
            json={
                "model": settings.llm_model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.2, "num_predict": 150, "num_ctx": 512},
            },
        )
        resp.raise_for_status()
        return resp.json()["response"]


async def is_ready() -> bool:
    try:
        async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=5.0) as client:
            resp = await client.get("/")
            return resp.status_code == 200
    except Exception:
        return False
