from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from caimp_auth.password import hash_password

from ..auth import get_current_user, require_admin
from ..db import get_tenant_conn

router = APIRouter(prefix="/users", tags=["users"])


class UserCreate(BaseModel):
    email: str
    password: str
    role: str = "viewer"


class PasswordChange(BaseModel):
    password: str


class UserResponse(BaseModel):
    id: str
    org_id: str
    email: str
    role: str
    created_at: datetime


@router.get("", response_model=list[UserResponse])
async def list_users(user=Depends(get_current_user)):
    async with get_tenant_conn(user.org_id) as conn:
        rows = await conn.fetch(
            "SELECT id, org_id, email, role, created_at FROM users ORDER BY created_at DESC"
        )
    return [
        UserResponse(
            id=str(r["id"]), org_id=str(r["org_id"]),
            email=r["email"], role=r["role"], created_at=r["created_at"],
        )
        for r in rows
    ]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, user=Depends(require_admin)):
    async with get_tenant_conn(user.org_id) as conn:
        row = await conn.fetchrow(
            "INSERT INTO users (org_id, email, password_hash, role) "
            "VALUES ($1::uuid, $2, $3, $4) "
            "RETURNING id, org_id, email, role, created_at",
            user.org_id, body.email, hash_password(body.password), body.role,
        )
    return UserResponse(
        id=str(row["id"]), org_id=str(row["org_id"]),
        email=row["email"], role=row["role"], created_at=row["created_at"],
    )


@router.patch("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(user_id: str, body: PasswordChange, user=Depends(require_admin)):
    async with get_tenant_conn(user.org_id) as conn:
        result = await conn.execute(
            "UPDATE users SET password_hash=$1, updated_at=now() WHERE id=$2::uuid",
            hash_password(body.password), user_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: str, user=Depends(require_admin)):
    async with get_tenant_conn(user.org_id) as conn:
        result = await conn.execute("DELETE FROM users WHERE id = $1::uuid", user_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
