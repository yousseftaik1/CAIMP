from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


class CAManager:
    """Platform root CA: generation, encryption at rest, and CSR signing."""

    _NONCE_LEN = 12  # AES-GCM 96-bit nonce

    def __init__(self, passphrase: str) -> None:
        # Derive 32-byte key from passphrase (SHA-256); good enough for a
        # single-tenant platform CA whose passphrase is an ops secret.
        self._aesgcm = AESGCM(hashlib.sha256(passphrase.encode()).digest())

    # ------------------------------------------------------------------
    # CA lifecycle
    # ------------------------------------------------------------------

    def generate_ca(self) -> tuple[str, bytes]:
        """Return (cert_pem, encrypted_key_bytes) for a new self-signed root CA."""
        key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name(
            [
                x509.NameAttribute(NameOID.COMMON_NAME, "CAIMP Root CA"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "CAIMP Platform"),
            ]
        )
        now = datetime.now(tz=timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + timedelta(days=3650))
            .add_extension(
                x509.BasicConstraints(ca=True, path_length=None), critical=True
            )
            .add_extension(
                x509.KeyUsage(
                    key_cert_sign=True,
                    crl_sign=True,
                    digital_signature=False,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .sign(key, hashes.SHA256())
        )
        return (
            cert.public_bytes(serialization.Encoding.PEM).decode(),
            self._encrypt_key(key),
        )

    def sign_csr(
        self,
        csr_pem: str,
        ca_cert_pem: str,
        encrypted_ca_key: bytes,
        org_id: str,
        server_id: str,
        validity_days: int = 365,
    ) -> tuple[str, str, str]:
        """
        Sign a CSR. Returns (cert_pem, serial_number_hex, sha256_fingerprint_hex).
        Embeds a SPIFFE URI SAN: spiffe://caimp/org/{org_id}/server/{server_id}
        """
        csr = x509.load_pem_x509_csr(csr_pem.encode())
        ca_cert = x509.load_pem_x509_certificate(ca_cert_pem.encode())
        ca_key = self._decrypt_key(encrypted_ca_key)

        now = datetime.now(tz=timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(csr.subject)
            .issuer_name(ca_cert.subject)
            .public_key(csr.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + timedelta(days=validity_days))
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None), critical=True
            )
            .add_extension(
                x509.SubjectAlternativeName(
                    [
                        x509.UniformResourceIdentifier(
                            f"spiffe://caimp/org/{org_id}/server/{server_id}"
                        ),
                    ]
                ),
                critical=False,
            )
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    key_agreement=True,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]),
                critical=False,
            )
            .sign(ca_key, hashes.SHA256())
        )

        der = cert.public_bytes(serialization.Encoding.DER)
        return (
            cert.public_bytes(serialization.Encoding.PEM).decode(),
            format(cert.serial_number, "x"),
            hashlib.sha256(der).hexdigest(),
        )

    # ------------------------------------------------------------------
    # SPIFFE helpers
    # ------------------------------------------------------------------

    @staticmethod
    def extract_spiffe_san(cert_pem: str) -> str | None:
        """Return the first SPIFFE URI SAN from the cert, or None."""
        cert = x509.load_pem_x509_certificate(cert_pem.encode())
        try:
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            for uri in san.value.get_values_for_type(x509.UniformResourceIdentifier):
                if uri.startswith("spiffe://"):
                    return uri
        except x509.ExtensionNotFound:
            pass
        return None

    @staticmethod
    def parse_spiffe_uri(uri: str) -> tuple[str, str] | None:
        """
        Parse spiffe://caimp/org/{org_id}/server/{server_id}.
        Returns (org_id, server_id) or None on mismatch.
        """
        prefix = "spiffe://caimp/org/"
        if not uri.startswith(prefix):
            return None
        parts = uri[len(prefix) :].split("/server/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return None
        return parts[0], parts[1]

    # ------------------------------------------------------------------
    # Crypto internals
    # ------------------------------------------------------------------

    def _encrypt_key(self, key: ec.EllipticCurvePrivateKey) -> bytes:
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        nonce = os.urandom(self._NONCE_LEN)
        return nonce + self._aesgcm.encrypt(nonce, pem, None)

    def _decrypt_key(self, data: bytes) -> ec.EllipticCurvePrivateKey:
        nonce, ct = data[: self._NONCE_LEN], data[self._NONCE_LEN :]
        pem = self._aesgcm.decrypt(nonce, ct, None)
        key = serialization.load_pem_private_key(pem, password=None)
        assert isinstance(key, ec.EllipticCurvePrivateKey)
        return key
