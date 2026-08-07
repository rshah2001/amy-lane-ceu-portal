"""A scored post-test can no longer be sat in somebody else's name from their
own invite link.

``POST /public/tests/{token}`` credited ``test_completed`` and the score purely
on the name and email typed into the form -- there was no attribution check at
all, not even the survey's. That matters more than the survey case it mirrors:
a post-test scored >=80% is what *directly* gates CEU eligibility.

The invite email now carries the same per-attendee ``?k=`` nonce the survey link
does. These tests pin both halves: the nonce is the identity and outranks
anything typed into the form, and the nonce-less QR flow -- one shared link for
the whole room, printed on paper -- still behaves exactly as it did.
"""
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.models.event_attendee import EventAttendee
from app.models.test_result import TestResult
from app.services import emailer
from app.services.invites import ensure_invite_nonce
from helpers_api import create_event, upload_csv

ALICE = "alice.nguyen@example.com"
BOB = "bob.ramos@example.com"

ROSTER_CSV = (
    "Full Name,Email,Company\n"
    f"Alice Nguyen,{ALICE},Mobility Works\n"
    f"Bob Ramos,{BOB},Mobility Works\n"
)

TEST_QUESTIONS = [
    {"id": "q1", "prompt": "2 + 2?", "choices": ["3", "4"], "correct_index": 1},
    {"id": "q2", "prompt": "Capital of France?", "choices": ["Paris", "Rome"], "correct_index": 0},
]
ALL_CORRECT = {"q1": 1, "q2": 0}
ALL_WRONG = {"q1": 0, "q2": 1}


def event_with_a_test(client, headers, **overrides) -> dict:
    return create_event(
        client, headers, test_mode="internal", test_questions=TEST_QUESTIONS, **overrides
    )


def submit(client, token, answers, nonce=None, name="Alice Nguyen", email=ALICE):
    url = f"/api/public/tests/{token}"
    if nonce is not None:
        url = f"{url}?k={nonce}"
    return client.post(url, json={"full_name": name, "email": email, "answers": answers})


def rows_by_email(client, headers, event_id) -> dict[str, dict]:
    response = client.get(f"/api/events/{event_id}/compliance", headers=headers)
    assert response.status_code == 200, response.text
    return {row["email"]: row for row in response.json()}


def link_for(db_session, event_id, email) -> EventAttendee:
    return db_session.scalar(
        select(EventAttendee)
        .join(EventAttendee.attendee)
        .where(EventAttendee.event_id == event_id)
        .where(EventAttendee.attendee.has(normalized_email=email))
    )


def audit_details(db_session, event_id, action="test.submitted") -> list[dict]:
    return [
        entry.details
        for entry in db_session.scalars(
            select(AuditLog)
            .where(AuditLog.event_id == event_id, AuditLog.action == action)
            .order_by(AuditLog.id)
        )
    ]


class TestNonceCreditsTheRightAttendee:
    def test_a_nonce_credits_its_own_attendee_and_scores_them(
        self, client, admin, db_session
    ):
        """The case the nonce exists for: the attendee opens the link we mailed
        them and sits the test, without retyping the address we already hold."""
        event = event_with_a_test(client, admin.headers)
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        nonce = ensure_invite_nonce(link_for(db_session, event["id"], ALICE))
        db_session.commit()

        response = submit(client, event["test_token"], ALL_CORRECT, nonce, name="", email=ALICE)
        assert response.status_code == 422, "the form still validates its own fields"

        response = submit(client, event["test_token"], ALL_CORRECT, nonce)
        assert response.status_code == 200, response.text
        assert response.json()["passed"] is True
        alice = rows_by_email(client, admin.headers, event["id"])[ALICE]
        assert alice["test_completed"] is True
        assert alice["test_score"] == 100.0

    def test_a_nonce_beats_a_wrong_name_typed_into_the_form(
        self, client, admin, db_session
    ):
        """The nonce is the identity; the form's name is not consulted. No stray
        roster row is created for the nickname."""
        event = event_with_a_test(client, admin.headers)
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        nonce = ensure_invite_nonce(link_for(db_session, event["id"], ALICE))
        db_session.commit()

        assert submit(
            client, event["test_token"], ALL_CORRECT, nonce, name="Ali N", email=ALICE
        ).status_code == 200
        rows = rows_by_email(client, admin.headers, event["id"])
        assert rows[ALICE]["test_completed"] is True
        assert len(rows) == 2  # "Ali N" did not become a third attendee

    def test_the_nonce_is_recorded_as_the_basis_that_credited_it(
        self, client, admin, db_session
    ):
        event = event_with_a_test(client, admin.headers)
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        nonce = ensure_invite_nonce(link_for(db_session, event["id"], ALICE))
        db_session.commit()

        submit(client, event["test_token"], ALL_CORRECT, nonce)
        details = audit_details(db_session, event["id"])[0]
        assert details["completion_basis"] == "invite_nonce"
        assert details["invite_nonce_presented"] is True
        assert details["invite_nonce_valid"] is True

    def test_the_nonce_value_is_never_written_into_the_audit_row(
        self, client, admin, db_session
    ):
        """Credentials do not appear in audit rows: an admin reading the log
        must not come away able to sit anybody's test."""
        event = event_with_a_test(client, admin.headers)
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        nonce = ensure_invite_nonce(link_for(db_session, event["id"], ALICE))
        db_session.commit()

        submit(client, event["test_token"], ALL_CORRECT, nonce)
        assert nonce not in str(audit_details(db_session, event["id"])[0])
        response = client.get(
            f"/api/audit-logs?event_id={event['id']}", headers=admin.headers
        )
        assert response.status_code == 200
        assert nonce not in response.text

    def test_what_was_typed_is_still_recorded_even_though_it_was_ignored(
        self, client, admin, db_session
    ):
        """The endpoint is unauthenticated, so the audit trail is the only
        record that the form claimed one person and the nonce named another."""
        event = event_with_a_test(client, admin.headers)
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        alice_nonce = ensure_invite_nonce(link_for(db_session, event["id"], ALICE))
        alice_id = link_for(db_session, event["id"], ALICE).attendee_id
        db_session.commit()

        submit(
            client, event["test_token"], ALL_CORRECT, alice_nonce,
            name="Bob Ramos", email=BOB,
        )
        details = audit_details(db_session, event["id"])[0]
        assert details["submitted_name"] == "Bob Ramos"
        assert details["submitted_email"] == BOB
        assert details["attendee_id"] == alice_id


class TestNonceCannotBeBorrowed:
    def test_one_attendees_nonce_cannot_score_another(self, client, admin, db_session):
        """The gap this sprint closes, from the other side: Bob's own link
        credits Bob, whatever email he types into the form."""
        event = event_with_a_test(client, admin.headers)
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        bob_nonce = ensure_invite_nonce(link_for(db_session, event["id"], BOB))
        db_session.commit()

        assert submit(
            client, event["test_token"], ALL_CORRECT, bob_nonce,
            name="Alice Nguyen", email=ALICE,
        ).status_code == 200
        rows = rows_by_email(client, admin.headers, event["id"])
        assert rows[BOB]["test_completed"] is True
        assert rows[ALICE]["test_completed"] is False
        assert rows[ALICE]["test_score"] is None

    def test_a_nonce_from_another_event_does_not_resolve(self, client, admin, db_session):
        """Nonces are globally unique but looked up scoped to the event, so a
        forwarded link from one event vouches for nobody on another."""
        other = event_with_a_test(client, admin.headers, title="Other CEU")
        upload_csv(client, admin.headers, other["id"], "registration", ROSTER_CSV)
        foreign = ensure_invite_nonce(link_for(db_session, other["id"], BOB))
        db_session.commit()

        event = event_with_a_test(client, admin.headers, title="Target CEU")
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        assert submit(
            client, event["test_token"], ALL_CORRECT, foreign,
            name="Alice Nguyen", email=ALICE,
        ).status_code == 200
        # Falls back to the pre-nonce rules, so Alice -- who is who the form
        # said -- is credited, and Bob's foreign link bought nothing.
        rows = rows_by_email(client, admin.headers, event["id"])
        assert rows[ALICE]["test_completed"] is True
        assert rows[BOB]["test_completed"] is False
        details = audit_details(db_session, event["id"])[0]
        assert details["completion_basis"] == "email_on_submission"
        assert details["invite_nonce_presented"] is True
        assert details["invite_nonce_valid"] is False

    def test_an_unrecognised_nonce_falls_back_instead_of_burning_the_attempt(
        self, client, admin, db_session
    ):
        """A mangled link must not cost the attendee one of three sittings --
        but it must be visible in the audit trail, because it is also what a
        tampered link looks like."""
        event = event_with_a_test(client, admin.headers)
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        response = submit(client, event["test_token"], ALL_CORRECT, "not-a-real-nonce")
        assert response.status_code == 200, response.text
        assert rows_by_email(client, admin.headers, event["id"])[ALICE]["test_score"] == 100.0
        details = audit_details(db_session, event["id"])[0]
        assert details["completion_basis"] == "email_on_submission"
        assert details["invite_nonce_presented"] is True
        assert details["invite_nonce_valid"] is False

    def test_an_over_long_nonce_is_rejected_by_the_schema(self, client, admin):
        """Bounded before it is used as a lookup key, not after."""
        event = event_with_a_test(client, admin.headers)
        response = submit(client, event["test_token"], ALL_CORRECT, "x" * 200)
        assert response.status_code == 422, response.text


class TestNonceLessFlowIsUnchanged:
    def test_the_shared_qr_link_still_scores_an_email_bearing_submission(
        self, client, admin, db_session
    ):
        """The printed QR sheet has no nonce and never will; the pre-existing
        email basis is what keeps it working."""
        event = event_with_a_test(client, admin.headers)
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        response = submit(client, event["test_token"], ALL_CORRECT)
        assert response.status_code == 200, response.text
        assert rows_by_email(client, admin.headers, event["id"])[ALICE]["test_score"] == 100.0
        details = audit_details(db_session, event["id"])[0]
        assert details["completion_basis"] == "email_on_submission"
        assert details["invite_nonce_presented"] is False
        assert details["invite_nonce_valid"] is False

    def test_a_walk_in_who_is_not_on_the_roster_is_still_created(self, client, admin):
        """The check-in path: no invite, no nonce, no roster row yet."""
        event = event_with_a_test(client, admin.headers)
        response = submit(
            client, event["test_token"], ALL_CORRECT,
            name="Pat Walkin", email="pat.walkin@example.com",
        )
        assert response.status_code == 200, response.text
        rows = rows_by_email(client, admin.headers, event["id"])
        assert rows["pat.walkin@example.com"]["test_completed"] is True


class TestNonceDoesNotChangeTheRestOfTheRules:
    def test_the_attempt_cap_still_applies_on_the_invited_path(
        self, client, admin, db_session
    ):
        """A per-person link is not a per-person exemption from the cap that
        stops a printed link being brute-forced into an answer key."""
        event = event_with_a_test(client, admin.headers)
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        nonce = ensure_invite_nonce(link_for(db_session, event["id"], ALICE))
        db_session.commit()

        for _ in range(3):
            assert submit(client, event["test_token"], ALL_WRONG, nonce).status_code == 200
        exhausted = submit(client, event["test_token"], ALL_CORRECT, nonce)
        assert exhausted.status_code == 409, exhausted.text

    def test_nonce_and_nonce_less_attempts_share_one_cap(
        self, client, admin, db_session
    ):
        """Both paths resolve to the same attendee, so the attempts are the same
        attempts -- switching links must not hand out three more."""
        event = event_with_a_test(client, admin.headers)
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        nonce = ensure_invite_nonce(link_for(db_session, event["id"], ALICE))
        db_session.commit()

        assert submit(client, event["test_token"], ALL_WRONG, nonce).status_code == 200
        assert submit(client, event["test_token"], ALL_WRONG).status_code == 200
        assert submit(client, event["test_token"], ALL_WRONG, nonce).status_code == 200
        assert submit(client, event["test_token"], ALL_CORRECT).status_code == 409

    def test_the_best_attempt_is_still_the_credited_one(self, client, admin, db_session):
        event = event_with_a_test(client, admin.headers)
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        nonce = ensure_invite_nonce(link_for(db_session, event["id"], ALICE))
        db_session.commit()

        assert submit(client, event["test_token"], ALL_CORRECT, nonce).status_code == 200
        assert submit(client, event["test_token"], ALL_WRONG, nonce).status_code == 200
        assert rows_by_email(client, admin.headers, event["id"])[ALICE]["test_score"] == 100.0
        # Both sittings are still on file behind that credited score.
        attempts = list(
            db_session.scalars(
                select(TestResult).where(TestResult.event_id == event["id"])
            )
        )
        assert len(attempts) == 2


class TestInviteEmailCarriesTheNonce:
    def test_distribution_puts_the_nonce_in_the_post_test_link(
        self, client, admin, db_session, monkeypatch
    ):
        sent: dict[str, str] = {}
        monkeypatch.setattr(
            emailer,
            "_deliver",
            lambda recipient, subject, body, pdf_path=None: sent.setdefault(recipient, body),
        )
        event = event_with_a_test(client, admin.headers)
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        assert client.post(
            f"/api/events/{event['id']}/distribute", headers=admin.headers
        ).status_code == 200

        db_session.expire_all()
        nonce = link_for(db_session, event["id"], ALICE).invite_nonce
        assert nonce
        test_url = next(
            word for word in sent[ALICE].split() if f"test={event['test_token']}" in word
        )
        assert parse_qs(urlparse(test_url).query)["k"] == [nonce]
        # And it is that attendee's alone -- Bob's email never carries it.
        assert nonce not in sent[BOB]

    def test_an_external_post_test_url_never_carries_the_nonce(
        self, client, admin, monkeypatch
    ):
        """It is our secret and an external form has no use for it; sending it
        there would hand a third party the ability to credit our attendees."""
        sent: dict[str, str] = {}
        monkeypatch.setattr(
            emailer,
            "_deliver",
            lambda recipient, subject, body, pdf_path=None: sent.setdefault(recipient, body),
        )
        event = create_event(
            client,
            admin.headers,
            test_mode="external",
            post_test_url="https://forms.example.com/post-test",
        )
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        client.post(f"/api/events/{event['id']}/distribute", headers=admin.headers)
        external = next(
            word for word in sent[ALICE].split() if word.startswith("https://forms.example.com")
        )
        assert "k=" not in external

    def test_an_end_to_end_emailed_link_scores_its_attendee(
        self, client, admin, db_session, monkeypatch
    ):
        """Take the URL out of the email, use it, and the right person is
        credited with the score they earned."""
        sent: dict[str, str] = {}
        monkeypatch.setattr(
            emailer,
            "_deliver",
            lambda recipient, subject, body, pdf_path=None: sent.setdefault(recipient, body),
        )
        event = event_with_a_test(client, admin.headers)
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        client.post(f"/api/events/{event['id']}/distribute", headers=admin.headers)

        # Read the query the way a browser would rather than trusting a substring.
        test_url = next(
            word for word in sent[BOB].split() if f"test={event['test_token']}" in word
        )
        nonce = parse_qs(urlparse(test_url).query)["k"][0]
        assert submit(
            client, event["test_token"], ALL_CORRECT, nonce, name="Bob Ramos", email=BOB
        ).status_code == 200
        rows = rows_by_email(client, admin.headers, event["id"])
        assert rows[BOB]["test_score"] == 100.0
        assert rows[ALICE]["test_completed"] is False
