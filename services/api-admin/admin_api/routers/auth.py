from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from caimp_auth.jwt_utils import decode_token, issue_access_token, issue_refresh_token
from caimp_auth.password import verify_password

from ..config import settings
from ..db import get_conn
from ..redis_client import get_redis

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "SELECT id, org_id, password_hash, role FROM users WHERE email = $1",
            body.email,
        )
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

    user_id = str(row["id"])
    org_id = str(row["org_id"])

    access_token = issue_access_token(
        user_id,
        org_id,
        row["role"],
        settings.jwt_secret,
        settings.jwt_access_expire_minutes,
    )
    refresh_result = issue_refresh_token(
        user_id, org_id, settings.jwt_secret, settings.jwt_refresh_expire_days
    )

    ttl = settings.jwt_refresh_expire_days * 86400
    await get_redis().setex(f"rt:{refresh_result.jti}", ttl, user_id)

    return TokenResponse(access_token=access_token, refresh_token=refresh_result.token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest):
    try:
        token_data = decode_token(body.refresh_token, settings.jwt_secret)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    if token_data.token_type != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token required"
        )

    redis = get_redis()
    if not await redis.get(f"rt:{token_data.jti}"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked or expired"
        )

    async with get_conn() as conn:
        row = await conn.fetchrow(
            "SELECT role FROM users WHERE id = $1::uuid", token_data.sub
        )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )

    await redis.delete(f"rt:{token_data.jti}")

    access_token = issue_access_token(
        token_data.sub,
        token_data.org_id,
        row["role"],
        settings.jwt_secret,
        settings.jwt_access_expire_minutes,
    )
    refresh_result = issue_refresh_token(
        token_data.sub,
        token_data.org_id,
        settings.jwt_secret,
        settings.jwt_refresh_expire_days,
    )
    await redis.setex(
        f"rt:{refresh_result.jti}",
        settings.jwt_refresh_expire_days * 86400,
        token_data.sub,
    )

    return TokenResponse(access_token=access_token, refresh_token=refresh_result.token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshRequest):
    try:
        token_data = decode_token(body.refresh_token, settings.jwt_secret)
        await get_redis().delete(f"rt:{token_data.jti}")
    except ValueError:
        pass  # already expired — nothing to revoke
