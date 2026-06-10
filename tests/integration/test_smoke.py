"""
Smoke tests — verify all API services are alive, auth works,
and the primary read paths return valid shapes.
"""
import httpx
import pytest

from conftest import ADMIN_API, QUERY_API, WS_GW


# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------

class TestHealth:
    def test_admin_api_health(self, http: httpx.Client):
        r = http.get(f"{ADMIN_API}/health")
        assert r.status_code == 200

    def test_query_api_health(self, http: httpx.Client):
        r = http.get(f"{QUERY_API}/health")
        assert r.status_code == 200

    def test_ws_gateway_health(self, http: httpx.Client):
        r = http.get(f"{WS_GW}/health")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class TestAuth:
    def test_login_success(self, http: httpx.Client):
        r = http.post(
            f"{ADMIN_API}/auth/login",
            json={"email": "admin@caimp.local", "password": "Admin1234!"},
        )
        assert r.status_code == 200
        body = r.json()
        assert "access_token" in body
        assert "refresh_token" in body

    def test_login_wrong_password(self, http: httpx.Client):
        r = http.post(
            f"{ADMIN_API}/auth/login",
            json={"email": "admin@caimp.local", "password": "wrong"},
        )
        assert r.status_code in (401, 422)

    def test_protected_route_without_token(self, http: httpx.Client):
        r = http.get(f"{QUERY_API}/api/v1/servers")
        assert r.status_code == 401

    def test_protected_route_with_token(self, http: httpx.Client, auth_headers: dict):
        r = http.get(f"{QUERY_API}/api/v1/servers", headers=auth_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_token_refresh(self, http: httpx.Client):
        login = http.post(
            f"{ADMIN_API}/auth/login",
            json={"email": "admin@caimp.local", "password": "Admin1234!"},
        )
        login.raise_for_status()
        refresh_token = login.json()["refresh_token"]

        r = http.post(
            f"{ADMIN_API}/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert r.status_code == 200
        assert "access_token" in r.json()


# ---------------------------------------------------------------------------
# Admin API — CRUD smoke
# ---------------------------------------------------------------------------

class TestAdminAPI:
    def test_list_servers(self, http: httpx.Client, auth_headers: dict):
        r = http.get(f"{ADMIN_API}/admin/v1/servers", headers=auth_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_alert_rules(self, http: httpx.Client, auth_headers: dict):
        r = http.get(f"{ADMIN_API}/admin/v1/alert-rules", headers=auth_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_and_delete_server(self, http: httpx.Client, auth_headers: dict):
        payload = {
            "name":     "smoke-test-server",
            "hostname": "smoke.local",
        }
        create = http.post(
            f"{ADMIN_API}/admin/v1/servers",
            json=payload,
            headers=auth_headers,
        )
        assert create.status_code in (200, 201)
        server = create.json()
        assert "id" in server
        assert "enrollment_token" in server

        delete = http.delete(
            f"{ADMIN_API}/admin/v1/servers/{server['id']}",
            headers=auth_headers,
        )
        assert delete.status_code in (200, 204)


# ---------------------------------------------------------------------------
# Query API — read paths
# ---------------------------------------------------------------------------

class TestQueryAPI:
    def test_list_servers(self, http: httpx.Client, auth_headers: dict):
        r = http.get(f"{QUERY_API}/api/v1/servers", headers=auth_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_anomalies(self, http: httpx.Client, auth_headers: dict):
        r = http.get(f"{QUERY_API}/api/v1/anomalies", headers=auth_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_ai_explanations(self, http: httpx.Client, auth_headers: dict):
        r = http.get(f"{QUERY_API}/api/v1/ai/explanations", headers=auth_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_metrics_missing_params_returns_422(self, http: httpx.Client, auth_headers: dict):
        r = http.get(f"{QUERY_API}/api/v1/metrics", headers=auth_headers)
        assert r.status_code == 422

    def test_server_summary_not_found(self, http: httpx.Client, auth_headers: dict):
        r = http.get(
            f"{QUERY_API}/api/v1/servers/00000000-0000-0000-0000-000000000000/summary",
            headers=auth_headers,
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# WebSocket Gateway — HTTP upgrade rejection without token
# ---------------------------------------------------------------------------

class TestWSGateway:
    def test_ws_rejects_missing_token(self, http: httpx.Client):
        # Plain HTTP GET to a WS endpoint without Upgrade headers → 422 or 400
        r = http.get(
            f"{WS_GW}/ws/00000000-0000-0000-0000-000000000001",
        )
        # FastAPI returns 422 for missing required Query param
        assert r.status_code in (400, 422)
