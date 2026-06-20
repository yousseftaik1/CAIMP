from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

import jwt
from jwt import PyJWTError


@dataclass
class TokenData:
    sub: str  # user_id or server_id (UUID string)
    org_id: str  # org_id (UUID string)
    role: str  # admin | devops | viewer | agent
    jti: str  # JWT ID — used for blacklisting
    token_type: str  # access | refresh


class RefreshTokenResult(NamedTuple):
    token: str
    jti: str


def issue_access_token(
    user_id: str,
    org_id: str,
    role: str,
    secret: str,
    expire_minutes: int = 15,
) -> str:
    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub": user_id,
        "org_id": org_id,
        "role": role,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=expire_minutes),
        "type": "access",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def issue_refresh_token(
    user_id: str,
    org_id: str,
    secret: str,
    expire_days: int = 7,
) -> RefreshTokenResult:
    now = datetime.now(tz=timezone.utc)
    jti = str(uuid.uuid4())
    payload = {
        "sub": user_id,
        "org_id": org_id,
        "jti": jti,
        "iat": now,
        "exp": now + timedelta(days=expire_days),
        "type": "refresh",
    }
    return RefreshTokenResult(
        token=jwt.encode(payload, secret, algorithm="HS256"), jti=jti
    )


def decode_token(token: str, secret: str) -> TokenData:
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except PyJWTError as exc:
        raise ValueError(f"Invalid token: {exc}") from exc
    return TokenData(
        sub=payload["sub"],
        org_id=payload.get("org_id", ""),
        role=payload.get("role", "viewer"),
        jti=payload["jti"],
        token_type=payload.get("type", "access"),
    )
