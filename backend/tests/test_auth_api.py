"""Auth endpoint tests: login, /auth/me, token handling.

Login has a brute-force rate limiter keyed by email + client IP (429 after
several failures), so each negative-login test uses its own unique email and
performs at most one failed attempt.
"""
from conftest import TEST_PASSWORD, make_user, unique_email


class TestLogin:
    def test_successful_login_returns_token_and_user(self, client, admin):
        response = client.post(
            "/api/auth/login",
            json={"email": admin.email, "password": TEST_PASSWORD},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["access_token"]
        assert body["token_type"] == "bearer"
        assert body["user"]["email"] == admin.email
        assert body["user"]["role"] == "admin"
        assert body["user"]["is_active"] is True

        # The issued token must authenticate /auth/me.
        me = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )
        assert me.status_code == 200
        assert me.json()["email"] == admin.email

    def test_login_uppercase_email_is_normalized(self, client, presenter):
        response = client.post(
            "/api/auth/login",
            json={"email": presenter.email.upper(), "password": TEST_PASSWORD},
        )
        assert response.status_code == 200, response.text
        assert response.json()["user"]["email"] == presenter.email

    def test_wrong_password_returns_401(self, client, db_session, password_hash):
        user = make_user(
            db_session, password_hash, role="presenter", email=unique_email("wrongpw")
        )
        response = client.post(
            "/api/auth/login",
            json={"email": user.email, "password": "not-the-password"},
        )
        assert response.status_code == 401, response.text

    def test_unknown_email_returns_401(self, client):
        response = client.post(
            "/api/auth/login",
            json={"email": unique_email("ghost"), "password": "whatever123"},
        )
        assert response.status_code == 401, response.text

    def test_inactive_user_returns_403(self, client, db_session, password_hash):
        user = make_user(
            db_session,
            password_hash,
            role="presenter",
            email=unique_email("inactive"),
            is_active=False,
        )
        # Correct password, inactive account: must be rejected with 403.
        response = client.post(
            "/api/auth/login",
            json={"email": user.email, "password": TEST_PASSWORD},
        )
        assert response.status_code == 403, response.text


class TestMe:
    def test_me_without_token_is_rejected(self, client):
        response = client.get("/api/auth/me")
        # HTTPBearer rejects a missing header; 401 or 403 depending on config.
        assert response.status_code in (401, 403), response.text

    def test_me_with_garbage_token_returns_401(self, client):
        response = client.get(
            "/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
        )
        assert response.status_code == 401, response.text

    def test_me_with_token_of_inactive_user_returns_401(
        self, client, db_session, password_hash
    ):
        user = make_user(
            db_session,
            password_hash,
            role="presenter",
            email=unique_email("inactive-token"),
            is_active=False,
        )
        response = client.get("/api/auth/me", headers=user.headers)
        assert response.status_code == 401, response.text

    def test_me_returns_current_user(self, client, presenter):
        response = client.get("/api/auth/me", headers=presenter.headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["email"] == presenter.email
        assert body["role"] == "presenter"
