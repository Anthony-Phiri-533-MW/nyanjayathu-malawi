"""Authentication, authorization and privilege-escalation rules."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.permissions import PERMISSIONS
from tests.conftest import ADMIN_EMAIL


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] in {"ok", "healthy"}


def test_login_rejects_bad_password(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "not-the-password"}
    )
    assert response.status_code == 401


def test_login_rejects_unknown_email(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.org", "password": "whatever-12345"}
    )
    assert response.status_code == 401


def test_me_requires_token(client: TestClient) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401


def test_me_returns_roles_and_permissions(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    response = client.get("/api/v1/auth/me", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert "super_admin" in body["roles"]
    perms = set(body["permissions"])
    assert "admin.users.write" in perms
    assert "research.indicators.read" in perms
    # the wildcard is expanded for API responses, so /me lists every concrete key
    assert perms == set(PERMISSIONS)


def test_expired_or_garbage_token_is_rejected(client: TestClient) -> None:
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not.a.token"}).status_code == 401


# --------------------------------------------------------------- RBAC
def test_researcher_cannot_reach_admin_endpoints(
    client: TestClient, make_user
) -> None:
    _, headers = make_user("researcher1@example.org", role="researcher")
    assert client.get("/api/v1/admin/users", headers=headers).status_code == 403
    assert client.get("/api/v1/admin/audit", headers=headers).status_code == 403
    assert client.get("/api/v1/admin/data-sources", headers=headers).status_code == 403


def test_researcher_can_read_catalogue(client: TestClient, make_user) -> None:
    _, headers = make_user("researcher2@example.org", role="researcher")
    assert client.get("/api/v1/providers", headers=headers).status_code == 200
    assert client.get("/api/v1/indicators/definitions", headers=headers).status_code == 200
    assert client.get("/api/v1/study-areas", headers=headers).status_code == 200
    # admin-only surfaces stay closed
    assert client.get("/api/v1/admin/data-sources", headers=headers).status_code == 403


def test_admin_cannot_grant_super_admin(client: TestClient, make_user) -> None:
    _, admin_headers = make_user("plain-admin@example.org", role="admin")
    response = client.post(
        "/api/v1/admin/users",
        json={
            "email": "wannabe-super@example.org",
            "full_name": "Wannabe Super",
            "password": "Sup3r-secret-pass",
            "roles": ["super_admin"],
        },
        headers=admin_headers,
    )
    assert response.status_code == 403


def test_admin_cannot_promote_user_to_super_admin(client: TestClient, make_user, admin_headers) -> None:
    target, _ = make_user("promote-me@example.org", role="researcher")
    _, plain_admin = make_user("promoter@example.org", role="admin")
    response = client.put(
        f"/api/v1/admin/users/{target['id']}/roles",
        json={"roles": ["super_admin"]},
        headers=plain_admin,
    )
    assert response.status_code == 403


def test_super_admin_can_create_and_promote(client: TestClient, make_user, admin_headers) -> None:
    user, _ = make_user("future-admin@example.org", role="researcher")
    response = client.put(
        f"/api/v1/admin/users/{user['id']}/roles",
        json={"roles": ["admin"]},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert "admin" in response.json()["roles"]


def test_admin_cannot_modify_super_admin(client: TestClient, admin_headers) -> None:
    listing = client.get("/api/v1/admin/users", params={"q": ADMIN_EMAIL}, headers=admin_headers)
    assert listing.status_code == 200
    super_admin = next(u for u in listing.json()["items"] if u["email"] == ADMIN_EMAIL)

    _, plain_admin = _make_admin(client, admin_headers)
    response = client.patch(
        f"/api/v1/admin/users/{super_admin['id']}",
        json={"full_name": "Hijacked"},
        headers=plain_admin,
    )
    assert response.status_code == 403


def test_admin_cannot_change_own_roles(client: TestClient, admin_headers) -> None:
    _, plain_admin = _make_admin(client, admin_headers)
    me = client.get("/api/v1/auth/me", headers=plain_admin).json()
    response = client.put(
        f"/api/v1/admin/users/{me['id']}/roles",
        json={"roles": ["researcher"]},
        headers=plain_admin,
    )
    assert response.status_code in (403, 409), response.text


def test_admin_cannot_deactivate_self(client: TestClient, admin_headers) -> None:
    _, plain_admin = _make_admin(client, admin_headers)
    me = client.get("/api/v1/auth/me", headers=plain_admin).json()
    response = client.post(
        f"/api/v1/admin/users/{me['id']}/deactivate", headers=plain_admin
    )
    assert response.status_code in (400, 403, 409), response.text


def test_super_admin_cannot_deactivate_self(client: TestClient, admin_headers) -> None:
    listing = client.get("/api/v1/admin/users", params={"q": ADMIN_EMAIL}, headers=admin_headers)
    super_admin = next(u for u in listing.json()["items"] if u["email"] == ADMIN_EMAIL)
    response = client.post(
        f"/api/v1/admin/users/{super_admin['id']}/deactivate", headers=admin_headers
    )
    assert response.status_code in (400, 409), response.text


def test_change_password_flow(client: TestClient, make_user) -> None:
    _, headers = make_user("password-user@example.org", role="researcher")
    wrong = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "wrong-password", "new_password": "Br4nd-new-secret"},
        headers=headers,
    )
    assert wrong.status_code in (400, 401, 403)

    ok = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "Sup3r-secret-pass", "new_password": "Br4nd-new-secret"},
        headers=headers,
    )
    assert ok.status_code == 200, ok.text
    relogin = client.post(
        "/api/v1/auth/login",
        json={"email": "password-user@example.org", "password": "Br4nd-new-secret"},
    )
    assert relogin.status_code == 200


def _make_admin(client: TestClient, admin_headers: dict[str, str]) -> tuple[dict, dict[str, str]]:
    import uuid

    email = f"admin-{uuid.uuid4().hex[:8]}@example.org"
    created = client.post(
        "/api/v1/admin/users",
        json={
            "email": email,
            "full_name": "Secondary Admin",
            "password": "Sup3r-secret-pass",
            "roles": ["admin"],
        },
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    login = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "Sup3r-secret-pass"}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return created.json(), headers
