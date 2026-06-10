"""
Pytest fixtures for CAIMP integration tests.

Assumes the following services are already running (via docker compose up):
  - admin-api  on localhost:8001
  - query-api  on localhost:8002
  - ws-gateway on localhost:8080

In CI these are started by the ci.yml workflow before pytest is invoked.
Locally, run `make up` first, then `pytest tests/integration/`.
"""
import os

import httpx
import pytest

ADMIN_API = os.getenv("ADMIN_API_URL", "http://localhost:8001")
QUERY_API = os.getenv("QUERY_API_URL", "http://localhost:8002")
WS_GW     = os.getenv("WS_GW_URL",    "http://localhost:8080")

SEED_EMAIL    = os.getenv("SEED_ADMIN_EMAIL",    "admin@caimp.local")
SEED_PASSWORD = os.getenv("SEED_ADMIN_PASSWORD", "Admin1234!")


@pytest.fixture(scope="session")
def http() -> httpx.Client:
    with httpx.Client(timeout=15) as client:
        yield client


@pytest.fixture(scope="session")
def admin_token(http: httpx.Client) -> str:
    resp = http.post(
        f"{ADMIN_API}/auth/login",
        json={"email": SEED_EMAIL, "password": SEED_PASSWORD},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


@pytest.fixture(scope="session")
def auth_headers(admin_token: str) -> dict:
    return {"Authorization": f"Bearer {admin_token}"}
