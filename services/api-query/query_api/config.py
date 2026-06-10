from __future__ import annotations
import os


class _Settings:
    @property
    def postgres_dsn(self) -> str:
        return os.environ["POSTGRES_DSN"]

    @property
    def redis_url(self) -> str:
        return os.getenv("REDIS_URL", "redis://redis:6379")

    @property
    def redis_password(self) -> str:
        return os.getenv("REDIS_PASSWORD", "")

    @property
    def jwt_secret(self) -> str:
        return os.environ["JWT_SECRET"]

    @property
    def log_level(self) -> str:
        return os.getenv("LOG_LEVEL", "INFO").lower()

    @property
    def ollama_url(self) -> str:
        return os.getenv("OLLAMA_URL", "http://ollama:11434")

    @property
    def ollama_embed_model(self) -> str:
        return os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")


settings = _Settings()
