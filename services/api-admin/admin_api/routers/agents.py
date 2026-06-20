from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

from caimp_auth.jwt_utils import issue_access_token
from caimp_auth.pki import CAManager

from ..config import settings
from ..db import get_conn

router = APIRouter(prefix="/agents", tags=["agents"])


class EnrollRequest(BaseModel):
    token: str
    csr_pem: str


class EnrollResponse(BaseModel):
    cert_pem: str
    ca_cert_pem: str
    expires_at: str


class AgentTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/enroll", response_model=EnrollResponse)
async def enroll_agent(body: EnrollRequest):
    async with get_conn() as conn:
        tok = await conn.fetchrow(
            "SELECT server_id, org_id, expires_at, used_at FROM enrollment_tokens WHERE token = $1",
            body.token,
        )
        if not tok:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid enrollment token",
            )
        if tok["used_at"] is not None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Token already used"
            )
        if tok["expires_at"] < datetime.now(tz=timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired"
            )

        server_id = str(tok["server_id"])
        org_id = str(tok["org_id"])

        ca_row = await conn.fetchrow(
            "SELECT cert_pem, encrypted_key FROM ca_config ORDER BY created_at DESC LIMIT 1"
        )
        if not ca_row:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="CA not initialised",
            )

        ca_mgr = CAManager(settings.ca_key_passphrase)
        cert_pem, serial_hex, fingerprint = ca_mgr.sign_csr(
            body.csr_pem,
            ca_row["cert_pem"],
            bytes(ca_row["encrypted_key"]),
            org_id,
            server_id,
        )
        expires_at = datetime.now(tz=timezone.utc) + timedelta(days=365)

        async with conn.transaction():
            await conn.execute(
                "INSERT INTO agent_certs (server_id, org_id, cert_pem, serial_number, fingerprint, expires_at) "
                "VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6)",
                server_id,
                org_id,
                cert_pem,
                serial_hex,
                fingerprint,
                expires_at,
            )
            await conn.execute(
                "UPDATE enrollment_tokens SET used_at = now() WHERE token = $1",
                body.token,
            )

    return EnrollResponse(
        cert_pem=cert_pem,
        ca_cert_pem=ca_row["cert_pem"],
        expires_at=expires_at.isoformat(),
    )


@router.post("/auth/token", response_model=AgentTokenResponse)
async def agent_auth_token(
    x_client_cert: str | None = Header(default=None, alias="X-Client-Cert"),
):
    """
    Exchange an mTLS client certificate for a JWT.
    nginx must forward the verified PEM via the X-Client-Cert header.
    """
    if not x_client_cert:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No client certificate"
        )

    cert_pem = unquote(x_client_cert)
    ca_mgr = CAManager(settings.ca_key_passphrase)

    spiffe_uri = ca_mgr.extract_spiffe_san(cert_pem)
    if not spiffe_uri:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No SPIFFE SAN in certificate",
        )

    parsed = ca_mgr.parse_spiffe_uri(spiffe_uri)
    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed SPIFFE URI"
        )

    org_id, server_id = parsed

    async with get_conn() as conn:
        cert_row = await conn.fetchrow(
            "SELECT revoked_at FROM agent_certs "
            "WHERE server_id = $1::uuid AND org_id = $2::uuid "
            "ORDER BY issued_at DESC LIMIT 1",
            server_id,
            org_id,
        )
        if not cert_row:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Certificate not found"
            )
        if cert_row["revoked_at"]:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Certificate revoked"
            )

        revoked = await conn.fetchrow(
            "SELECT id FROM revoked_agents WHERE server_id = $1::uuid AND org_id = $2::uuid",
            server_id,
            org_id,
        )
        if revoked:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Agent revoked"
            )

    token = issue_access_token(
        user_id=server_id,
        org_id=org_id,
        role="agent",
        secret=settings.jwt_secret,
        expire_minutes=settings.jwt_access_expire_minutes,
    )
    return AgentTokenResponse(access_token=token)
