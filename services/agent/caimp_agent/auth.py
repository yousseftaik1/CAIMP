"""
Agent identity, enrollment, and JWT lifecycle.

Enrollment flow:
  1. Generate ECDSA P-256 keypair (private key stays on host).
  2. Build a CSR and POST to /agents/enroll with the one-time token.
  3. Persist the signed X.509 client cert.
  4. Exchange mTLS handshake for a short-lived JWT via /agents/auth/token.
  5. Auto-refresh JWT 3 minutes before expiry.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from .config import AgentConfig

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------


def generate_keypair(key_path: Path) -> ec.EllipticCurvePrivateKey:
    """Generate ECDSA P-256 keypair and persist private key (chmod 600)."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path.write_bytes(pem)
    os.chmod(key_path, 0o600)
    log.info("Generated ECDSA P-256 keypair → %s", key_path)
    return private_key


def load_or_generate_key(key_path: Path) -> ec.EllipticCurvePrivateKey:
    if key_path.exists():
        pem = key_path.read_bytes()
        return serialization.load_pem_private_key(pem, password=None)
    return generate_keypair(key_path)


# ---------------------------------------------------------------------------
# CSR
# ---------------------------------------------------------------------------


def build_csr(
    private_key: ec.EllipticCurvePrivateKey,
    server_name: str,
) -> bytes:
    """Build a PEM-encoded CSR for the agent identity."""
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, server_name)]))
        .sign(private_key, hashes.SHA256())
    )
    return csr.public_bytes(serialization.Encoding.PEM)


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------


class EnrollmentManager:
    def __init__(self, cfg: AgentConfig) -> None:
        self.cfg = cfg

    def is_enrolled(self) -> bool:
        return self.cfg.cert_path.exists() and self.cfg.ca_path.exists()

    def enroll(self, enrollment_token: str) -> None:
        """Submit CSR to Admin API and persist the signed cert + CA cert."""
        private_key = load_or_generate_key(self.cfg.key_path)
        csr_pem = build_csr(private_key, self.cfg.server_name)

        url = f"{self.cfg.admin_api_url}/agents/enroll"
        log.info("Enrolling agent at %s …", url)

        resp = requests.post(
            url,
            json={
                "enrollment_token": enrollment_token,
                "csr_pem": csr_pem.decode(),
                "server_name": self.cfg.server_name,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        self.cfg.cert_path.write_text(data["cert_pem"])
        self.cfg.ca_path.write_text(data["ca_cert_pem"])
        log.info("Enrolled successfully — cert expires %s", data.get("expires_at"))

    def cert_needs_renewal(self) -> bool:
        """Return True if cert expires within 25% of its lifetime (≈ 22 days for 90-day cert)."""
        if not self.is_enrolled():
            return False
        pem = self.cfg.cert_path.read_bytes()
        cert = x509.load_pem_x509_certificate(pem)
        total = (cert.not_valid_after_utc - cert.not_valid_before_utc).total_seconds()
        remain = cert.not_valid_after_utc.timestamp() - time.time()
        return remain < total * 0.25

    def renew_cert(self) -> None:
        """Renew the agent cert by re-enrolling with a fresh CSR."""
        private_key = load_or_generate_key(self.cfg.key_path)
        csr_pem = build_csr(private_key, self.cfg.server_name)

        resp = requests.post(
            f"{self.cfg.admin_api_url}/agents/renew",
            json={"csr_pem": csr_pem.decode()},
            cert=(str(self.cfg.cert_path), str(self.cfg.key_path)),
            verify=str(self.cfg.ca_path),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self.cfg.cert_path.write_text(data["cert_pem"])
        log.info("Cert renewed — new expiry %s", data.get("expires_at"))


# ---------------------------------------------------------------------------
# JWT manager
# ---------------------------------------------------------------------------


class JWTManager:
    def __init__(self, cfg: AgentConfig) -> None:
        self.cfg = cfg
        self._token: str | None = None
        self._expires_at: float = 0.0

    def _fetch_token(self) -> str:
        """Exchange mTLS handshake for a short-lived JWT."""
        resp = requests.post(
            f"{self.cfg.admin_api_url}/agents/auth/token",
            cert=(str(self.cfg.cert_path), str(self.cfg.key_path)),
            verify=str(self.cfg.ca_path),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._expires_at = time.time() + data.get("expires_in", 900) - 60
        self.cfg.token_path.write_text(self._token)
        log.debug("JWT refreshed, valid for %ds", data.get("expires_in", 900))
        return self._token

    def get_token(self) -> str:
        if self._token is None or time.time() >= self._expires_at:
            self._token = self._fetch_token()
        return self._token

    async def refresh_loop(self) -> None:
        """Background coroutine that refreshes the JWT every jwt_refresh_secs."""
        while True:
            try:
                self._fetch_token()
            except Exception as exc:
                log.warning("JWT refresh failed: %s", exc)
            await asyncio.sleep(self.cfg.jwt_refresh_secs)

    # Graceful no-op when API is unreachable (dev / pre-enrollment)
    def get_token_or_none(self) -> str | None:
        try:
            return self.get_token()
        except Exception:
            return None
