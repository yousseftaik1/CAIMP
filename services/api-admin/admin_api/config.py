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
    def jwt_access_expire_minutes(self) -> int:
        return int(os.getenv("JWT_ACCESS_EXPIRE_MINUTES", "15"))

    @property
    def jwt_refresh_expire_days(self) -> int:
        return int(os.getenv("JWT_REFRESH_EXPIRE_DAYS", "7"))

    @property
    def ca_key_passphrase(self) -> str:
        return os.environ["CA_KEY_PASSPHRASE"]

    @property
    def log_level(self) -> str:
        return os.getenv("LOG_LEVEL", "INFO").lower()


settings = _Settings()
