"""Survey completion can no longer be claimed with only a known email address.

Before the nonce, ``_completion_basis`` accepted ``email_on_submission`` as
proof: a submission carrying an address that matched a roster attendee credited
that attendee. An address is not a secret, so anybody who knew a colleague's
registered email could complete their survey for them.

The invite email now carries a per-attendee ``?k=`` nonce that nothing on the
roster reveals. These tests pin both halves: the nonce is trusted, and the
nonce-less QR flow -- which is a core feature, printed on paper -- still works
exactly as it did.
"""
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from app.models.event_attendee import EventAttendee
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


def submit(client, token, nonce=None, **body):
    url = f"/api/public/surveys/{token}"
    if nonce is not None:
        url = f"{url}?k={nonce}"
    return client.post(url, json=body)


def survey_flags(client, headers, event_id) -> dict[str, bool]:
    rows = client.get(f"/api/events/{event_id}/compliance", headers=headers).json()
    return {row["email"]: row["survey_completed"] for row in rows}


def link_for(db_session, event_id, email) -> EventAttendee:
    return db_session.scalar(
        select(EventAttendee)
        .join(EventAttendee.attendee)
        .where(EventAttendee.event_id == event_id)
        .where(EventAttendee.attendee.has(normalized_email=email))
    )


def audit_details(db_session, event_id, action):
    from app.models.audit_log import AuditLog

    return [
        entry.details
        for entry in db_session.scalars(
            select(AuditLog)
            .where(AuditLog.event_id == event_id, AuditLog.action == action)
            .order_by(AuditLog.id)
        )
    ]


class TestNonceCreditsTheRightAttendee:
    def test_a_nonce_credits_its_own_attendee_with_no_identity_typed_in(
        self, client, admin, db_session
    ):
        """The case the nonce exists for: the attendee opens the link we mailed
        them and answers, without retyping the address we already hold."""
        event = create_event(client, admin.headers)
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        nonce = ensure_invite_nonce(link_for(db_session, event["id"], ALICE))
        db_session.commit()

        response = submit(client, event["survey_token"], nonce, answers={"liked": "Useful"})
        assert response.status_code == 200, response.text
        assert response.json() == {"status": "submitted"}
        assert survey_flags(client, admin.headers, event["id"])[ALICE] is True

    def test_a_nonce_beats_a_wrong_name_typed_into_the_form(
        self, client, admin, db_session
    ):
        """The nonce is the identity; the form's name is not consulted. Nobody
        else's flag moves, and no stray roster row is created for the nickname."""
        event = create_event(client, admin.headers)
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        nonce = ensure_invite_nonce(link_for(db_session, event["id"], ALICE))
        db_session.commit()

        assert submit(
            client,
            event["survey_token"],
            nonce,
            full_name="Ali N",
            answers={"liked": "Useful"},
        ).status_code == 200
        flags = survey_flags(client, admin.headers, event["id"])
        assert flags[ALICE] is True
        assert flags[BOB] is False
        assert len(flags) == 2  # "Ali N" did not become a third attendee

    def test_the_nonce_is_recorded_as_the_basis_that_credited_it(
        self, client, admin, db_session
    ):
        event = create_event(client, admin.headers)
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        nonce = ensure_invite_nonce(link_for(db_session, event["id"], ALICE))
        db_session.commit()

        submit(client, event["survey_token"], nonce, answers={"liked": "Useful"})
        details = audit_details(db_session, event["id"], "survey.submitted")[0]
        assert details["completion_basis"] == "invite_nonce"
        assert details["survey_completed"] is True
        assert details["invite_nonce_presented"] is True
        assert details["invite_nonce_valid"] is True


class TestNonceCannotBeBorrowed:
    def test_one_attendees_nonce_cannot_credit_another(self, client, admin, db_session):
        """Bob's own link credits Bob, whatever email he types into the form."""
        event = create_event(client, admin.headers)
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        bob_nonce = ensure_invite_nonce(link_for(db_session, event["id"], BOB))
        db_session.commit()

        assert submit(
            client,
            event["survey_token"],
            bob_nonce,
            full_name="Alice Nguyen",
            email=ALICE,
            answers={"liked": "Not hers"},
        ).status_code == 200
        flags = survey_flags(client, admin.headers, event["id"])
        assert flags[BOB] is True
        assert flags[ALICE] is False

    def test_a_nonce_from_another_event_does_not_resolve(self, client, admin, db_session):
        """Nonces are globally unique but looked up scoped to the event, so a
        forwarded link from one event vouches for nobody on another."""
        other = create_event(client, admin.headers, title="Other CEU")
        upload_csv(client, admin.headers, other["id"], "registration", ROSTER_CSV)
        foreign = ensure_invite_nonce(link_for(db_session, other["id"], ALICE))
        db_session.commit()

        event = create_event(client, admin.headers, title="Target CEU")
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        response = submit(
            client, event["survey_token"], foreign, full_name="Alice Nguyen",
            answers={"liked": "Borrowed"},
        )
        # Falls back to the older rules: a name naming an attendee who has an
        # email on file, without that email, is still refused.
        assert response.status_code == 200, response.text
        assert response.json()["credited"] is False
        assert survey_flags(client, admin.headers, event["id"])[ALICE] is False

    def test_an_unrecognised_nonce_falls_back_instead_of_failing(
        self, client, admin, db_session
    ):
        """A mangled link must not throw away real feedback -- but it must be
        visible in the audit trail, because it is what a tampered link looks
        like."""
        event = create_event(client, admin.headers)
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        response = submit(
            client, event["survey_token"], "not-a-real-nonce",
            full_name="Alice Nguyen", email=ALICE, answers={"liked": "Still counted"},
        )
        assert response.status_code == 200, response.text
        # The pre-nonce basis still applies, so this one is credited.
        assert survey_flags(client, admin.headers, event["id"])[ALICE] is True
        details = audit_details(db_session, event["id"], "survey.submitted")[0]
        assert details["completion_basis"] == "email_on_submission"
        assert details["invite_nonce_presented"] is True
        assert details["invite_nonce_valid"] is False

    def test_an_over_long_nonce_is_rejected_by_the_schema(self, client, admin):
        event = create_event(client, admin.headers)
        response = submit(client, event["survey_token"], "x" * 200, answers={"liked": "Hi"})
        assert response.status_code == 422, response.text


class TestNonceLessFlowIsUnchanged:
    def test_the_shared_qr_link_still_credits_an_email_bearing_submission(
        self, client, admin
    ):
        """The printed QR sheet has no nonce and never will; the pre-existing
        email basis is what keeps it working."""
        event = create_event(client, admin.headers)
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        response = submit(
            client, event["survey_token"], full_name="Alice Nguyen", email=ALICE,
            answers={"liked": "From the QR sheet"},
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"status": "submitted"}
        assert survey_flags(client, admin.headers, event["id"])[ALICE] is True

    def test_anonymous_submission_still_works(self, client, admin):
        event = create_event(client, admin.headers)
        response = submit(client, event["survey_token"], answers={"liked": "Blind feedback"})
        assert response.status_code == 200, response.text
        rows = client.get(
            f"/api/survey-responses?event_id={event['id']}", headers=admin.headers
        ).json()
        assert len(rows) == 1
        assert rows[0]["attendee_id"] is None

    def test_a_name_only_impersonation_is_still_refused(self, client, admin, db_session):
        event = create_event(client, admin.headers)
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        response = submit(
            client, event["survey_token"], full_name="Alice Nguyen", answers={"liked": "Not mine"}
        )
        assert response.json()["credited"] is False
        assert survey_flags(client, admin.headers, event["id"])[ALICE] is False
        details = audit_details(db_session, event["id"], "survey.submitted")[0]
        assert details["invite_nonce_presented"] is False
        assert details["invite_nonce_valid"] is False
        refused = audit_details(db_session, event["id"], "survey.completion_refused")[0]
        assert refused["invite_nonce_presented"] is False

    def test_a_refusal_records_that_a_nonce_was_offered_and_did_not_resolve(
        self, client, admin, db_session
    ):
        """The fingerprint of a stale or edited link, readable without cross-
        referencing the submission entry."""
        event = create_event(client, admin.headers)
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        submit(
            client, event["survey_token"], "not-a-real-nonce",
            full_name="Alice Nguyen", answers={"liked": "Not mine"},
        )
        refused = audit_details(db_session, event["id"], "survey.completion_refused")[0]
        assert refused["invite_nonce_presented"] is True


class TestInviteEmailCarriesTheNonce:
    def test_distribution_mints_a_nonce_and_puts_it_in_the_survey_link(
        self, client, admin, db_session, monkeypatch
    ):
        sent: dict[str, str] = {}
        monkeypatch.setattr(
            emailer,
            "_deliver",
            lambda recipient, subject, body, pdf_path=None: sent.setdefault(recipient, body),
        )
        event = create_event(client, admin.headers)
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        assert client.post(
            f"/api/events/{event['id']}/distribute", headers=admin.headers
        ).status_code == 200

        db_session.expire_all()
        nonce = link_for(db_session, event["id"], ALICE).invite_nonce
        assert nonce
        assert f"k={nonce}" in sent[ALICE]
        # And it is that attendee's alone -- Bob's email never carries it.
        bob_nonce = link_for(db_session, event["id"], BOB).invite_nonce
        assert bob_nonce and bob_nonce != nonce
        assert nonce not in sent[BOB]

    def test_re_running_distribution_keeps_the_same_nonce(
        self, client, admin, db_session, monkeypatch
    ):
        """A second send must not invalidate the link already in an inbox."""
        monkeypatch.setattr(
            emailer, "_deliver", lambda recipient, subject, body, pdf_path=None: "sent"
        )
        event = create_event(client, admin.headers)
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        client.post(f"/api/events/{event['id']}/distribute", headers=admin.headers)
        db_session.expire_all()
        first = link_for(db_session, event["id"], ALICE).invite_nonce
        client.post(f"/api/events/{event['id']}/distribute", headers=admin.headers)
        db_session.expire_all()
        assert link_for(db_session, event["id"], ALICE).invite_nonce == first

    def test_the_nonce_is_never_serialized_to_an_api_response(
        self, client, admin, db_session, monkeypatch
    ):
        """It is a per-person secret, not roster data: an admin export that
        carried it would hand every reader the ability to complete anyone's
        survey."""
        monkeypatch.setattr(
            emailer, "_deliver", lambda recipient, subject, body, pdf_path=None: "sent"
        )
        event = create_event(client, admin.headers)
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        client.post(f"/api/events/{event['id']}/distribute", headers=admin.headers)
        db_session.expire_all()
        nonce = link_for(db_session, event["id"], ALICE).invite_nonce

        for path in (
            f"/api/events/{event['id']}/compliance",
            f"/api/events/{event['id']}",
            f"/api/events/{event['id']}/summary",
            f"/api/attendees/search?event_id={event['id']}",
            "/api/survey-responses",
            "/api/survey-responses.csv",
            f"/api/audit-logs?event_id={event['id']}",
        ):
            response = client.get(path, headers=admin.headers)
            assert response.status_code == 200, (path, response.text)
            assert nonce not in response.text, path

    def test_an_end_to_end_emailed_link_credits_its_attendee(
        self, client, admin, db_session, monkeypatch
    ):
        """Take the URL out of the email, use it, and the right person is
        credited without typing anything."""
        sent: dict[str, str] = {}
        monkeypatch.setattr(
            emailer,
            "_deliver",
            lambda recipient, subject, body, pdf_path=None: sent.setdefault(recipient, body),
        )
        event = create_event(client, admin.headers)
        upload_csv(client, admin.headers, event["id"], "registration", ROSTER_CSV)
        client.post(f"/api/events/{event['id']}/distribute", headers=admin.headers)

        # Pull the survey URL out of the email and read its query the way a
        # browser would, rather than trusting a substring.
        survey_url = next(
            word for word in sent[ALICE].split() if f"survey={event['survey_token']}" in word
        )
        nonce = parse_qs(urlparse(survey_url).query)["k"][0]
        assert submit(
            client, event["survey_token"], nonce, answers={"liked": "Straight from the email"}
        ).status_code == 200
        flags = survey_flags(client, admin.headers, event["id"])
        assert flags[ALICE] is True
        assert flags[BOB] is False
