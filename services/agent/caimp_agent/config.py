"""Agent runtime configuration — loaded from env / defaults."""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgentConfig:
    # ---- Platform endpoints ------------------------------------------------
    admin_api_url: str = field(
        default_factory=lambda: os.getenv("CAIMP_ADMIN_URL", "http://localhost:8001")
    )
    otelcol_endpoint: str = field(
        default_factory=lambda: os.getenv("CAIMP_OTELCOL_ENDPOINT", "otelcol:4317")
    )
    use_tls: bool = field(
        default_factory=lambda: os.getenv("CAIMP_TLS", "true").lower() == "true"
    )

    # ---- Identity ----------------------------------------------------------
    data_dir: Path = field(
        default_factory=lambda: Path(os.getenv("CAIMP_DATA_DIR", "/etc/caimp-agent"))
    )
    server_name: str = field(
        default_factory=lambda: os.getenv("CAIMP_SERVER_NAME", socket.getfqdn())
    )

    # ---- Collection --------------------------------------------------------
    collection_interval_secs: int = field(
        default_factory=lambda: int(os.getenv("CAIMP_INTERVAL", "20"))
    )

    # ---- JWT ---------------------------------------------------------------
    jwt_refresh_secs: int = 12 * 60  # refresh at 12 min (before 15 min expiry)

    # ---- Buffer ------------------------------------------------------------
    buffer_max_mb: int = field(
        default_factory=lambda: int(os.getenv("CAIMP_BUFFER_MAX_MB", "50"))
    )
    buffer_max_hours: int = field(
        default_factory=lambda: int(os.getenv("CAIMP_BUFFER_MAX_HOURS", "24"))
    )

    # ---- Derived paths -----------------------------------------------------
    @property
    def key_path(self) -> Path:
        return self.data_dir / "agent.key"

    @property
    def cert_path(self) -> Path:
        return self.data_dir / "agent.crt"

    @property
    def ca_path(self) -> Path:
        return self.data_dir / "ca.crt"

    @property
    def token_path(self) -> Path:
        return self.data_dir / "jwt.token"

    @property
    def buffer_path(self) -> Path:
        return self.data_dir / "buffer.db"

    def ensure_data_dir(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
