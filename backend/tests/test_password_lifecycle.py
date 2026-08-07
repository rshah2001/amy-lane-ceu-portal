"""Change-password, forgotten-password, and admin-initiated reset.

Covers the three properties the reset token has to have (single-use, expiring,
not guessable), the rate limit on the unauthenticated routes, the fact that
neither the response nor the audit trail ever carries password material, and
that a wrong address cannot be used to enumerate accounts.
"""
from datetime import timedelta
from unittest.mock import patch

import pytest
from conftest import TEST_PASSWORD, make_user

from app.core.clock import utc_now
from app.core.config import settings
from app.core.rate_limit import password_reset_limiter
from app.models.user import User
from app.services.password_reset import hash_token

NEW_PASSWORD = "BrandNewPass1!"


def login(client, email, password):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def forgot(client, email):
    return client.post("/api/auth/forgot-password", json={"email": email})


def reset(client, token, new_password=NEW_PASSWORD):
    return client.post(
        "/api/auth/reset-password", json={"token": token, "new_password": new_password}
    )


def sent_emails(mock) -> list[tuple]:
    return [call.args for call in mock.call_args_list]


@pytest.fixture()
def reset_token(client, admin, presenter):
    """A live reset token for the presenter, minted the way a user would."""
    with patch("app.api.auth.send_password_reset_email") as mock:
        assert forgot(client, presenter.email).status_code == 202
    # The token only ever exists in the email; that is the point of storing a
    # hash. Read it back out of the message the emailer was handed.
    return sent_emails(mock)[0][2].split("reset=")[1]


class TestChangeOwnPassword:
    def test_changes_the_password_when_the_current_one_is_right(
        self, client, presenter
    ):
        response = client.post(
            "/api/auth/change-password",
            json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
            headers=presenter.headers,
        )
        assert response.status_code == 200, response.text
        assert login(client, presenter.email, NEW_PASSWORD).status_code == 200
        assert login(client, presenter.email, TEST_PASSWORD).status_code == 401

    def test_wrong_current_password_is_refused(self, client, presenter):
        response = client.post(
            "/api/auth/change-password",
            json={"current_password": "not-the-password", "new_password": NEW_PASSWORD},
            headers=presenter.headers,
        )
        assert response.status_code == 400, response.text
        # A borrowed session must not be enough to lock the owner out.
        assert login(client, presenter.email, TEST_PASSWORD).status_code == 200

    def test_reusing_the_current_password_is_refused(self, client, presenter):
        response = client.post(
            "/api/auth/change-password",
            json={"current_password": TEST_PASSWORD, "new_password": TEST_PASSWORD},
            headers=presenter.headers,
        )
        assert response.status_code == 400, response.text

    def test_short_password_is_a_422(self, client, presenter):
        response = client.post(
            "/api/auth/change-password",
            json={"current_password": TEST_PASSWORD, "new_password": "short"},
            headers=presenter.headers,
        )
        assert response.status_code == 422, response.text

    def test_requires_authentication(self, client):
        response = client.post(
            "/api/auth/change-password",
            json={"current_password": "x", "new_password": NEW_PASSWORD},
        )
        assert response.status_code == 403, response.text


class TestForgotPassword:
    def test_emails_a_reset_link(self, client, presenter):
        with patch("app.api.auth.send_password_reset_email") as mock:
            response = forgot(client, presenter.email)
        assert response.status_code == 202, response.text
        recipient, _name, url, _expires = sent_emails(mock)[0]
        assert recipient == presenter.email
        assert url.startswith(settings.public_frontend_url)
        assert "reset=" in url

    def test_unknown_address_answers_identically_and_sends_nothing(
        self, client, presenter
    ):
        with patch("app.api.auth.send_password_reset_email") as mock:
            known = forgot(client, presenter.email)
            unknown = forgot(client, "nobody@example.com")
        assert known.status_code == unknown.status_code == 202
        # Identical bodies: the route must not be usable to test which
        # addresses have portal accounts.
        assert known.json() == unknown.json()
        assert len(sent_emails(mock)) == 1

    def test_deactivated_account_gets_no_token(self, client, db_session, password_hash):
        inactive = make_user(db_session, password_hash, role="presenter", is_active=False)
        with patch("app.api.auth.send_password_reset_email") as mock:
            assert forgot(client, inactive.email).status_code == 202
        assert sent_emails(mock) == []
        assert db_session.get(User, inactive.id).password_reset_token_hash is None

    def test_a_failed_send_does_not_change_the_answer(self, client, presenter):
        with patch(
            "app.api.auth.send_password_reset_email", side_effect=RuntimeError("smtp down")
        ):
            response = forgot(client, presenter.email)
        # Surfacing the failure here would be an enumeration oracle.
        assert response.status_code == 202, response.text

    def test_rate_limited_per_caller(self, client, presenter):
        original = settings.password_reset_rate_limit
        settings.password_reset_rate_limit = 2
        password_reset_limiter.reset()
        try:
            with patch("app.api.auth.send_password_reset_email"):
                assert forgot(client, presenter.email).status_code == 202
                assert forgot(client, presenter.email).status_code == 202
                blocked = forgot(client, presenter.email)
            assert blocked.status_code == 429, blocked.text
            assert "Retry-After" in blocked.headers
        finally:
            settings.password_reset_rate_limit = original
            password_reset_limiter.reset()


class TestResetPassword:
    def test_token_sets_a_new_password(self, client, presenter, reset_token):
        response = reset(client, reset_token)
        assert response.status_code == 200, response.text
        assert login(client, presenter.email, NEW_PASSWORD).status_code == 200
        assert login(client, presenter.email, TEST_PASSWORD).status_code == 401

    def test_token_is_single_use(self, client, presenter, reset_token):
        assert reset(client, reset_token).status_code == 200
        replay = reset(client, reset_token, "AnotherPass1!")
        assert replay.status_code == 400, replay.text
        # The first password stands; a replayed link changes nothing.
        assert login(client, presenter.email, NEW_PASSWORD).status_code == 200

    def test_expired_token_is_refused_and_cleared(
        self, client, db_session, presenter, reset_token
    ):
        user = db_session.get(User, presenter.id)
        user.password_reset_expires_at = utc_now() - timedelta(minutes=1)
        db_session.commit()

        response = reset(client, reset_token)
        assert response.status_code == 400, response.text
        db_session.expire_all()
        # An expired token is burned rather than left lying in the table.
        assert db_session.get(User, presenter.id).password_reset_token_hash is None
        assert login(client, presenter.email, TEST_PASSWORD).status_code == 200

    def test_unknown_token_is_refused_with_the_same_message(self, client, reset_token):
        unknown = reset(client, "x" * 43)
        assert unknown.status_code == 400, unknown.text
        used = reset(client, reset_token)
        assert used.status_code == 200
        replayed = reset(client, reset_token)
        # Unknown and already-used are indistinguishable to an anonymous caller.
        assert replayed.json()["detail"] == unknown.json()["detail"]

    def test_only_the_hash_is_stored(self, client, db_session, presenter, reset_token):
        user = db_session.get(User, presenter.id)
        db_session.refresh(user)
        stored = user.password_reset_token_hash
        # A readable token in the database would be an account takeover for
        # anybody holding a backup.
        assert stored != reset_token
        assert reset_token not in stored
        assert stored == hash_token(reset_token)
        assert len(stored) == 64

    def test_tokens_are_long_and_unpredictable(self, client, presenter, admin):
        seen = set()
        with patch("app.api.auth.send_password_reset_email") as mock:
            for _ in range(3):
                password_reset_limiter.reset()
                assert forgot(client, presenter.email).status_code == 202
        for call in sent_emails(mock):
            token = call[2].split("reset=")[1]
            assert len(token) >= 40
            seen.add(token)
        assert len(seen) == 3

    def test_requesting_again_invalidates_the_previous_link(self, client, presenter):
        with patch("app.api.auth.send_password_reset_email") as mock:
            assert forgot(client, presenter.email).status_code == 202
            password_reset_limiter.reset()
            assert forgot(client, presenter.email).status_code == 202
        first, second = (call[2].split("reset=")[1] for call in sent_emails(mock))
        assert reset(client, first).status_code == 400
        assert reset(client, second).status_code == 200

    def test_rate_limited_per_caller(self, client, presenter):
        original = settings.password_reset_rate_limit
        settings.password_reset_rate_limit = 2
        password_reset_limiter.reset()
        try:
            assert reset(client, "y" * 43).status_code == 400
            assert reset(client, "y" * 43).status_code == 400
            assert reset(client, "y" * 43).status_code == 429
        finally:
            settings.password_reset_rate_limit = original
            password_reset_limiter.reset()

    def test_oversized_token_is_a_422(self, client):
        assert reset(client, "z" * 5000).status_code == 422


class TestAdminInitiatedReset:
    def test_returns_a_link_the_admin_can_pass_on_and_emails_it(
        self, client, admin, presenter
    ):
        with patch("app.api.users.send_password_reset_email") as mock:
            response = client.post(
                f"/api/users/{presenter.id}/reset-password", headers=admin.headers
            )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["user_id"] == presenter.id
        assert body["emailed"] is True
        assert body["email_error"] is None
        assert "reset=" in body["reset_url"]
        assert sent_emails(mock)[0][0] == presenter.email

        token = body["reset_url"].split("reset=")[1]
        assert reset(client, token).status_code == 200
        assert login(client, presenter.email, NEW_PASSWORD).status_code == 200

    def test_link_still_returned_when_the_email_fails(self, client, admin, presenter):
        # The case this exists for: the presenter's address is itself what is
        # broken, so "check your email" is not an answer.
        with patch(
            "app.api.users.send_password_reset_email", side_effect=RuntimeError("smtp down")
        ):
            response = client.post(
                f"/api/users/{presenter.id}/reset-password", headers=admin.headers
            )
        assert response.status_code == 200, response.text
        assert response.json()["emailed"] is False
        assert response.json()["email_error"]
        token = response.json()["reset_url"].split("reset=")[1]
        assert reset(client, token).status_code == 200

    def test_presenters_cannot_reset_other_accounts(self, client, presenter, other_presenter):
        response = client.post(
            f"/api/users/{other_presenter.id}/reset-password", headers=presenter.headers
        )
        assert response.status_code == 403, response.text

    def test_unknown_user_is_404(self, client, admin):
        response = client.post("/api/users/999999/reset-password", headers=admin.headers)
        assert response.status_code == 404, response.text

    def test_deactivated_account_is_refused(self, client, admin, db_session, password_hash):
        inactive = make_user(db_session, password_hash, role="presenter", is_active=False)
        response = client.post(
            f"/api/users/{inactive.id}/reset-password", headers=admin.headers
        )
        assert response.status_code == 409, response.text

    def test_setting_a_password_by_hand_invalidates_an_outstanding_link(
        self, client, admin, presenter
    ):
        with patch("app.api.users.send_password_reset_email"):
            issued = client.post(
                f"/api/users/{presenter.id}/reset-password", headers=admin.headers
            )
        token = issued.json()["reset_url"].split("reset=")[1]
        patched = client.patch(
            f"/api/users/{presenter.id}",
            json={"password": "SetByHand1!"},
            headers=admin.headers,
        )
        assert patched.status_code == 200, patched.text
        # The link in the inbox is a spare key nobody asked to keep.
        assert reset(client, token).status_code == 400


class TestNoPasswordMaterialIsRecorded:
    def _audit(self, client, headers):
        response = client.get("/api/audit-logs", headers=headers)
        assert response.status_code == 200, response.text
        return response.json()

    def test_change_password_audit_carries_no_secret(self, client, admin, presenter):
        client.post(
            "/api/auth/change-password",
            json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
            headers=presenter.headers,
        )
        entries = [e for e in self._audit(client, admin.headers) if e["action"] == "user.password_changed"]
        assert len(entries) == 1
        assert entries[0]["details"] == {"method": "self_service"}
        blob = str(self._audit(client, admin.headers))
        assert NEW_PASSWORD not in blob
        assert TEST_PASSWORD not in blob

    def test_reset_audit_carries_neither_token_nor_password(
        self, client, admin, presenter, reset_token
    ):
        assert reset(client, reset_token).status_code == 200
        blob = str(self._audit(client, admin.headers))
        assert reset_token not in blob
        assert NEW_PASSWORD not in blob
        actions = {e["action"] for e in self._audit(client, admin.headers)}
        assert "user.password_reset_requested" in actions
        assert "user.password_changed" in actions

    def test_admin_issued_reset_is_audited_without_the_token(
        self, client, admin, presenter
    ):
        with patch("app.api.users.send_password_reset_email"):
            issued = client.post(
                f"/api/users/{presenter.id}/reset-password", headers=admin.headers
            )
        token = issued.json()["reset_url"].split("reset=")[1]
        entries = [
            e for e in self._audit(client, admin.headers) if e["action"] == "user.password_reset_issued"
        ]
        assert len(entries) == 1
        assert entries[0]["actor_id"] == admin.id
        assert entries[0]["entity_id"] == presenter.id
        assert entries[0]["details"]["emailed"] is True
        assert token not in str(entries[0])
