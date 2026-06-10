from __future__ import annotations

import os


class _Settings:
    @property
    def postgres_dsn(self) -> str:
        return os.environ["POSTGRES_DSN"]

    @property
    def nats_url(self) -> str:
        return os.getenv("NATS_URL", "nats://nats:4222")

    @property
    def nats_user(self) -> str:
        return os.getenv("NATS_USER", "")

    @property
    def nats_password(self) -> str:
        return os.getenv("NATS_PASSWORD", "")

    @property
    def redis_url(self) -> str:
        return os.getenv("REDIS_URL", "redis://redis:6379")

    @property
    def redis_password(self) -> str:
        return os.getenv("REDIS_PASSWORD", "")

    @property
    def ollama_base_url(self) -> str:
        return os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")

    @property
    def llm_model(self) -> str:
        return os.getenv("OLLAMA_LLM_MODEL", "llama3.1:8b-instruct-q4_K_M")

    @property
    def embed_model(self) -> str:
        return os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

    @property
    def worker_concurrency(self) -> int:
        return int(os.getenv("AI_WORKER_CONCURRENCY", "2"))

    @property
    def log_level(self) -> str:
        return os.getenv("LOG_LEVEL", "INFO")


settings = _Settings()
