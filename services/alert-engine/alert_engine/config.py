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
    def rules_cache_ttl(self) -> int:
        return int(os.getenv("ALERT_RULES_CACHE_TTL", "60"))

    @property
    def log_level(self) -> str:
        return os.getenv("LOG_LEVEL", "INFO")


settings = _Settings()
