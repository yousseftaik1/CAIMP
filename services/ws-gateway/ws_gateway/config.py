from __future__ import annotations

import os


class _Settings:
    @property
    def jwt_secret(self) -> str:
        return os.environ["JWT_SECRET"]

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
    def log_level(self) -> str:
        return os.getenv("LOG_LEVEL", "INFO")


settings = _Settings()
