"""A credential change ends the sessions that were open under the old one.

The hole these cover: access tokens carried nothing tying them to the password
they were minted under, so changing or resetting a password left every
previously issued token valid for the rest of ``access_token_expire_minutes``
(eight hours). Somebody who resets a password in a hurry does it *because* they
believe another person has it -- and that person kept working access all day.

The counter is ``User.token_version``; every token carries the value it was
minted under and ``app.api.deps`` refuses any that no longer matches.
"""
from unittest.mock import patch

from conftest import TEST_PASSWORD
from jose import jwt
from sqlalchemy import select

from app.core.config import settings
from app.core.security import ALGORITHM, create_access_token, decode_access_token
from app.models.user import User

NEW_PASSWORD = "BrandNewPass1!"


def me(client, headers):
    return client.get("/api/auth/me", headers=headers)


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def forge(claims: dict) -> str:
    """A validly *signed* token with arbitrary claims.

    The signature is never the thing under test here -- the point is that a
    token which survives the signature check on claims we did not write is
    still refused, or is refused with a 401 rather than a 500."""
    return jwt.encode(claims, settings.secret_key, algorithm=ALGORITHM)


def claims_of(headers: dict) -> dict:
    return decode_access_token(headers["Authorization"].split()[1])


def change_password(client, headers, current=TEST_PASSWORD, new=NEW_PASSWORD):
    return client.post(
        "/api/auth/change-password",
        json={"current_password": current, "new_password": new},
        headers=headers,
    )


def reset_token_for(client, email) -> str:
    """A live reset token, read out of the email the way a user would get it."""
    with patch("app.api.auth.send_password_reset_email") as mock:
        assert client.post("/api/auth/forgot-password", json={"email": email}).status_code == 202
    return mock.call_args_list[0].args[2].split("reset=")[1]


class TestChangePasswordEndsOtherSessions:
    def test_a_token_issued_before_the_change_stops_working(self, client, presenter):
        stolen = presenter.headers
        assert me(client, stolen).status_code == 200
        assert change_password(client, stolen).status_code == 200
        # The whole point: not at expiry, now.
        response = me(client, stolen)
        assert response.status_code == 401, response.text
        assert "sign in again" in response.json()["detail"].lower()

    def test_a_second_device_is_signed_out_too(self, client, db_session, presenter):
        """Two sessions, one changes the password: the other one dies."""
        user = db_session.scalar(select(User).where(User.id == presenter.id))
        other_device = bearer(create_access_token(str(user.id), user.role, user.token_version))
        assert change_password(client, presenter.headers).status_code == 200
        assert me(client, other_device).status_code == 401

    def test_the_caller_who_changed_it_is_not_signed_out(self, client, presenter):
        """The one session a password change must not evict is the one that
        made it -- otherwise changing a password teaches people not to."""
        response = change_password(client, presenter.headers)
        assert response.status_code == 200, response.text
        body = response.json()
        # A superset of MessageOut: a client reading only `detail` still works.
        assert body["detail"]
        assert body["token_type"] == "bearer"
        assert body["user"]["id"] == presenter.id
        fresh = me(client, bearer(body["access_token"]))
        assert fresh.status_code == 200, fresh.text
        assert fresh.json()["id"] == presenter.id

    def test_a_failed_change_leaves_the_session_alone(self, client, presenter):
        assert change_password(client, presenter.headers, current="wrong").status_code == 400
        assert me(client, presenter.headers).status_code == 200


class TestResetPasswordEndsAllSessions:
    def test_redeeming_a_reset_link_kills_the_open_session(self, client, admin, presenter):
        token = reset_token_for(client, presenter.email)
        assert me(client, presenter.headers).status_code == 200
        response = client.post(
            "/api/auth/reset-password", json={"token": token, "new_password": NEW_PASSWORD}
        )
        assert response.status_code == 200, response.text
        # The reset is anonymous, so there is nobody to hand a fresh token to;
        # every session on the account goes, including the owner's.
        assert me(client, presenter.headers).status_code == 401
        login = client.post(
            "/api/auth/login", json={"email": presenter.email, "password": NEW_PASSWORD}
        )
        assert login.status_code == 200, login.text
        assert me(client, bearer(login.json()["access_token"])).status_code == 200

    def test_merely_issuing_an_admin_reset_link_does_not_sign_anyone_out(
        self, client, admin, presenter
    ):
        """Issuing a link sets no password, so it must not evict a session the
        user may still be using -- the eviction lands when the link is spent."""
        with patch("app.api.users.send_password_reset_email"):
            response = client.post(
                f"/api/users/{presenter.id}/reset-password", headers=admin.headers
            )
        assert response.status_code == 200, response.text
        assert me(client, presenter.headers).status_code == 200


class TestAdminPasswordSetEndsSessions:
    def test_patching_a_password_signs_that_user_out(self, client, admin, presenter):
        response = client.patch(
            f"/api/users/{presenter.id}",
            json={"password": NEW_PASSWORD},
            headers=admin.headers,
        )
        assert response.status_code == 200, response.text
        assert me(client, presenter.headers).status_code == 401
        # The admin's own session is untouched by someone else's change.
        assert me(client, admin.headers).status_code == 200

    def test_patching_something_other_than_the_password_keeps_the_session(
        self, client, admin, presenter
    ):
        response = client.patch(
            f"/api/users/{presenter.id}", json={"full_name": "Renamed"}, headers=admin.headers
        )
        assert response.status_code == 200, response.text
        assert me(client, presenter.headers).status_code == 200


class TestDeactivationIsImmediate:
    def test_deactivating_a_user_ends_their_open_session(self, client, admin, presenter):
        assert me(client, presenter.headers).status_code == 200
        response = client.patch(
            f"/api/users/{presenter.id}", json={"is_active": False}, headers=admin.headers
        )
        assert response.status_code == 200, response.text
        assert me(client, presenter.headers).status_code == 401

    def test_a_reactivated_user_keeps_the_session_they_had(self, client, admin, presenter):
        """Deactivation is not a credential change: nothing was disclosed, so
        the token is suspended rather than destroyed."""
        client.patch(
            f"/api/users/{presenter.id}", json={"is_active": False}, headers=admin.headers
        )
        client.patch(
            f"/api/users/{presenter.id}", json={"is_active": True}, headers=admin.headers
        )
        assert me(client, presenter.headers).status_code == 200


class TestTokenVersionClaim:
    def test_a_token_with_no_version_claim_is_accepted_as_version_one(
        self, client, presenter
    ):
        """Grandfathering, so shipping this does not sign the portal out: a
        token minted before the claim existed reads as version 1, which is what
        every existing row starts at."""
        claims = claims_of(presenter.headers)
        assert claims["tv"] == 1
        legacy = {key: value for key, value in claims.items() if key != "tv"}
        assert me(client, bearer(forge(legacy))).status_code == 200

    def test_a_grandfathered_token_still_dies_on_the_next_password_change(
        self, client, presenter
    ):
        """The grandfather window is bounded by the deploy, not open-ended:
        version 1 stops matching the moment the account moves off it."""
        legacy = {k: v for k, v in claims_of(presenter.headers).items() if k != "tv"}
        assert change_password(client, presenter.headers).status_code == 200
        assert me(client, bearer(forge(legacy))).status_code == 401

    def test_a_stale_version_claim_is_refused(self, client, db_session, presenter):
        user = db_session.scalar(select(User).where(User.id == presenter.id))
        ahead = bearer(create_access_token(str(user.id), user.role, user.token_version + 1))
        behind = bearer(create_access_token(str(user.id), user.role, user.token_version - 1))
        # Neither direction is "close enough": only an exact match is a session.
        assert me(client, ahead).status_code == 401
        assert me(client, behind).status_code == 401

    def test_a_non_integer_version_claim_is_401_not_500(self, client, presenter):
        # `True` is in the list on purpose: bool is an int subclass, so a naive
        # comparison would read it as version 1 and let it through.
        for bogus in ("one", None, True, [1], {"v": 1}):
            claims = {**claims_of(presenter.headers), "tv": bogus}
            assert me(client, bearer(forge(claims))).status_code == 401, bogus

    def test_login_mints_the_current_version(self, client, presenter):
        assert change_password(client, presenter.headers).status_code == 200
        login = client.post(
            "/api/auth/login", json={"email": presenter.email, "password": NEW_PASSWORD}
        )
        assert login.status_code == 200, login.text
        assert decode_access_token(login.json()["access_token"])["tv"] == 2
