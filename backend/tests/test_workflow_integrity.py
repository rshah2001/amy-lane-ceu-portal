"""Regression tests for the workflow-integrity defects found in the live audit.

Each class covers one defect: a way the portal could record a compliance
outcome that never actually happened (an unanswered survey, a survey answered
by somebody else, a pass erased by a retake) or could hide one that did (a
question-less post-test link, a distribution failure with no reason, an import
that deleted results silently).
"""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.models.event_attendee import EventAttendee
from app.models.test_result import TestResult
from app.models.training_event import TrainingEvent
from app.services import emailer
from app.services.audit import RESULTS_CLEARED_ACTION, record_destructive_import
from helpers_api import create_event, upload_csv, upload_standard_roster

TEST_QUESTIONS = [
    {"id": "q1", "prompt": "2 + 2?", "choices": ["3", "4"], "correct_index": 1},
    {"id": "q2", "prompt": "Capital of France?", "choices": ["Paris", "Rome"], "correct_index": 0},
]


def submit_survey(client, token, **body):
    return client.post(f"/api/public/surveys/{token}", json=body)


def submit_test(client, token, answers, name="Sam Lee", email="sam.lee@example.com"):
    return client.post(
        f"/api/public/tests/{token}",
        json={"full_name": name, "email": email, "answers": answers},
    )


def compliance_by_email(client, headers, event_id) -> dict[str, dict]:
    response = client.get(f"/api/events/{event_id}/compliance", headers=headers)
    assert response.status_code == 200, response.text
    return {row["email"]: row for row in response.json()}


def audit_actions(db_session, event_id) -> list[AuditLog]:
    return list(
        db_session.scalars(
            select(AuditLog).where(AuditLog.event_id == event_id).order_by(AuditLog.id)
        )
    )


# --- 1. An empty survey submission satisfied a mandatory survey --------------


class TestEmptySurveySubmission:
    def test_submission_with_no_answers_is_rejected(self, client, admin):
        event = create_event(client, admin.headers, survey_required=True)
        response = submit_survey(
            client,
            event["survey_token"],
            full_name="Sam Lee",
            email="sam.lee@example.com",
            answers={},
        )
        assert response.status_code == 422, response.text
        assert "at least one" in response.text

    def test_submission_of_only_blank_answers_is_rejected(self, client, admin):
        event = create_event(client, admin.headers, survey_required=True)
        response = submit_survey(
            client,
            event["survey_token"],
            full_name="Sam Lee",
            email="sam.lee@example.com",
            answers={"liked": "", "improve": "   "},
        )
        assert response.status_code == 422, response.text

    def test_blank_submission_leaves_the_survey_requirement_unsatisfied(self, client, admin):
        """The defect: a blank POST used to mark the attendee survey-complete."""
        event = create_event(client, admin.headers, survey_required=True, test_required=False)
        upload_standard_roster(client, admin.headers, event["id"])
        blank = submit_survey(
            client,
            event["survey_token"],
            full_name="Alice Nguyen",
            email="alice.nguyen@example.com",
            answers={"liked": ""},
        )
        assert blank.status_code == 422, blank.text

        alice = compliance_by_email(client, admin.headers, event["id"])["alice.nguyen@example.com"]
        assert alice["survey_completed"] is False
        assert "Feedback survey not completed" in alice["eligibility_reasons"]

        answered = submit_survey(
            client,
            event["survey_token"],
            full_name="Alice Nguyen",
            email="alice.nguyen@example.com",
            answers={"liked": "The demo vehicles"},
        )
        assert answered.status_code == 200, answered.text
        alice = compliance_by_email(client, admin.headers, event["id"])["alice.nguyen@example.com"]
        assert alice["survey_completed"] is True
        assert alice["eligible"] is True

    def test_anonymous_submission_with_real_answers_still_works(self, client, admin):
        """Anonymity is about identity, not about content: commit 4020a61 stays."""
        event = create_event(client, admin.headers)
        response = submit_survey(
            client,
            event["survey_token"],
            full_name=None,
            email=None,
            answers={"liked": "Blind feedback"},
        )
        assert response.status_code == 200, response.text
        rows = client.get(
            f"/api/survey-responses?event_id={event['id']}", headers=admin.headers
        ).json()
        assert len(rows) == 1
        assert rows[0]["attendee_id"] is None

    def test_anonymous_submission_with_no_answers_is_rejected(self, client, admin):
        event = create_event(client, admin.headers)
        response = submit_survey(client, event["survey_token"], full_name=None, email=None, answers={})
        assert response.status_code == 422, response.text
        assert client.get(
            f"/api/survey-responses?event_id={event['id']}", headers=admin.headers
        ).json() == []

    def test_a_partial_submission_is_still_accepted_by_default(self, client, admin):
        """No question is mandatory unless it says so: skipping one of three
        template questions is normal feedback, not an empty submission."""
        event = create_event(client, admin.headers, survey_required=True)
        response = submit_survey(client, event["survey_token"], answers={"liked": "The pacing"})
        assert response.status_code == 200, response.text

    def test_required_flag_blocks_a_partial_submission(self, client, admin, db_session):
        """The stored ``required`` flag is honoured even though nothing sets it
        yet, so making questions mandatory later is a schema and UI change
        only -- this endpoint already enforces it."""
        created = create_event(client, admin.headers, title="Required Question CEU")
        event_row = db_session.get(TrainingEvent, created["id"])
        event_row.survey_questions = [
            {"id": "liked", "label": "What did you like?", "type": "text", "options": []},
            {"id": "improve", "label": "What could we improve?", "type": "text", "required": True},
        ]
        db_session.commit()

        partial = submit_survey(client, created["survey_token"], answers={"liked": "The pacing"})
        assert partial.status_code == 422, partial.text
        assert "improve" in partial.text

        complete = submit_survey(
            client, created["survey_token"], answers={"liked": "The pacing", "improve": "Nothing"}
        )
        assert complete.status_code == 200, complete.text


# --- 2. Anyone with the link could complete somebody else's survey -----------


class TestSurveyImpersonation:
    @pytest.fixture()
    def event(self, client, admin):
        event = create_event(
            client, admin.headers, survey_required=True, test_required=False, title="Impersonation CEU"
        )
        upload_standard_roster(client, admin.headers, event["id"])
        return event

    def test_name_only_submission_cannot_complete_an_existing_identity(self, client, admin, event):
        """Alice is on the roster with her email; naming her is not proving it."""
        response = submit_survey(
            client, event["survey_token"], full_name="Alice Nguyen", answers={"liked": "Not really me"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["credited"] is False

        alice = compliance_by_email(client, admin.headers, event["id"])["alice.nguyen@example.com"]
        assert alice["survey_completed"] is False
        assert alice["eligible"] is False

    def test_the_response_is_still_kept_for_the_admin(self, client, admin, event):
        submit_survey(
            client, event["survey_token"], full_name="Alice Nguyen", answers={"liked": "Real feedback"}
        )
        rows = client.get(
            f"/api/survey-responses?event_id={event['id']}", headers=admin.headers
        ).json()
        assert [row["answers"] for row in rows] == [{"liked": "Real feedback"}]

    def test_submission_carrying_the_address_on_file_is_credited(self, client, admin, event):
        response = submit_survey(
            client,
            event["survey_token"],
            full_name="Alice Nguyen",
            email="alice.nguyen@example.com",
            answers={"liked": "Genuinely mine"},
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"status": "submitted"}
        alice = compliance_by_email(client, admin.headers, event["id"])["alice.nguyen@example.com"]
        assert alice["survey_completed"] is True

    def test_a_name_not_on_the_roster_still_completes_its_own_survey(self, client, admin, event):
        """A walk-in creating their own record has no one else's flag to flip."""
        response = submit_survey(
            client, event["survey_token"], full_name="Walk In", answers={"liked": "Found it useful"}
        )
        assert response.status_code == 200, response.text
        rows = client.get(
            f"/api/survey-responses?event_id={event['id']}", headers=admin.headers
        ).json()
        assert rows[0]["full_name"] == "Walk In"
        compliance = client.get(
            f"/api/events/{event['id']}/compliance", headers=admin.headers
        ).json()
        walk_in = next(row for row in compliance if row["full_name"] == "Walk In")
        assert walk_in["survey_completed"] is True

    def test_every_public_submission_is_audited_with_its_source(
        self, client, admin, event, db_session
    ):
        submit_survey(
            client,
            event["survey_token"],
            full_name="Alice Nguyen",
            email="alice.nguyen@example.com",
            answers={"liked": "Mine"},
            business_location="Mobility Works",
        )
        entries = [
            entry for entry in audit_actions(db_session, event["id"])
            if entry.action == "survey.submitted"
        ]
        assert len(entries) == 1
        details = entries[0].details
        assert details["source"] == "public_web"
        assert details["survey_completed"] is True
        assert details["completion_basis"] == "email_on_submission"
        assert details["submitted_email"] == "alice.nguyen@example.com"
        assert details["client_ip"]
        assert details["answered"] == 1

    def test_a_refused_completion_is_audited_separately(self, client, admin, event, db_session):
        submit_survey(
            client, event["survey_token"], full_name="Alice Nguyen", answers={"liked": "Not mine"}
        )
        entries = audit_actions(db_session, event["id"])
        submitted = [entry for entry in entries if entry.action == "survey.submitted"]
        refused = [entry for entry in entries if entry.action == "survey.completion_refused"]
        assert len(submitted) == 1
        assert submitted[0].details["survey_completed"] is False
        assert len(refused) == 1
        assert refused[0].details["submitted_name"] == "Alice Nguyen"
        assert refused[0].details["submitted_email"] is None
        assert refused[0].details["client_ip"]

    def test_a_name_only_roster_row_can_still_be_completed(self, client, admin):
        """The paper sign-in sheet flow: no address on file, nothing to prove."""
        event = create_event(client, admin.headers, survey_required=True, title="Paper Sheet CEU")
        upload_csv(client, admin.headers, event["id"], "attendance", "Name\nPat Paper\n")
        response = submit_survey(
            client, event["survey_token"], full_name="Pat Paper", answers={"liked": "Good session"}
        )
        assert response.status_code == 200, response.text
        compliance = client.get(
            f"/api/events/{event['id']}/compliance", headers=admin.headers
        ).json()
        pat = next(row for row in compliance if row["full_name"] == "Pat Paper")
        assert pat["survey_completed"] is True
        # ...and it still buys nothing on its own: no address, no certificate.
        assert pat["eligible"] is False


# --- 3. A retake overwrote a passing score ----------------------------------


class TestPostTestRetakes:
    @pytest.fixture()
    def event(self, client, admin):
        return create_event(
            client,
            admin.headers,
            title="Retake CEU",
            test_mode="internal",
            test_questions=TEST_QUESTIONS,
        )

    def test_every_attempt_is_kept_as_its_own_row(self, client, admin, event, db_session):
        assert submit_test(client, event["test_token"], {"q1": 1, "q2": 0}).status_code == 200
        assert submit_test(client, event["test_token"], {"q1": 0, "q2": 1}).status_code == 200

        attempts = list(
            db_session.scalars(
                select(TestResult)
                .where(TestResult.event_id == event["id"])
                .order_by(TestResult.id)
            )
        )
        assert [Decimal(str(attempt.score)) for attempt in attempts] == [
            Decimal("100.00"),
            Decimal("0.00"),
        ]
        assert {attempt.source for attempt in attempts} == {"web"}

    def test_a_later_failing_attempt_never_erases_a_pass(self, client, admin, event):
        first = submit_test(client, event["test_token"], {"q1": 1, "q2": 0})
        assert first.json()["passed"] is True

        retake = submit_test(client, event["test_token"], {"q1": 0, "q2": 1})
        assert retake.status_code == 200, retake.text
        # The attempt itself is reported honestly...
        assert retake.json()["score"] == 0.0
        assert retake.json()["passed"] is False

        # ...but the credited score is the best attempt, so the pass stands.
        row = compliance_by_email(client, admin.headers, event["id"])["sam.lee@example.com"]
        assert row["test_score"] == 100.0
        assert row["test_completed"] is True
        assert "Post-test score below 80%" not in row["eligibility_reasons"]

    def test_a_better_retake_raises_the_credited_score(self, client, admin, event):
        submit_test(client, event["test_token"], {"q1": 0, "q2": 0})
        row = compliance_by_email(client, admin.headers, event["id"])["sam.lee@example.com"]
        assert row["test_score"] == 50.0

        submit_test(client, event["test_token"], {"q1": 1, "q2": 0})
        row = compliance_by_email(client, admin.headers, event["id"])["sam.lee@example.com"]
        assert row["test_score"] == 100.0

    def test_attempts_are_capped(self, client, admin, event):
        for _ in range(3):
            assert submit_test(client, event["test_token"], {"q1": 0, "q2": 1}).status_code == 200
        blocked = submit_test(client, event["test_token"], {"q1": 1, "q2": 0})
        assert blocked.status_code == 409, blocked.text
        assert "attempts" in blocked.text

    def test_the_cap_does_not_count_uploaded_results(self, client, admin, event):
        upload_csv(
            client,
            admin.headers,
            event["id"],
            "post_test",
            "Full Name,Email,Score\nSam Lee,sam.lee@example.com,72\n",
        )
        for _ in range(3):
            assert submit_test(client, event["test_token"], {"q1": 1, "q2": 0}).status_code == 200

    def test_each_attempt_is_audited_with_what_it_credited(self, client, admin, event, db_session):
        submit_test(client, event["test_token"], {"q1": 1, "q2": 0})
        submit_test(client, event["test_token"], {"q1": 0, "q2": 1})
        entries = [
            entry for entry in audit_actions(db_session, event["id"])
            if entry.action == "test.submitted"
        ]
        assert [entry.details["attempt"] for entry in entries] == [1, 2]
        assert entries[1].details["score"] == 0.0
        assert entries[1].details["credited_score"] == 100.0
        assert entries[1].details["credited_result_id"] == entries[0].details["credited_result_id"]
        assert entries[1].details["source"] == "public_web"


# --- 4. Attendees were emailed a link to a question-less quiz ----------------


@pytest.fixture()
def captured_emails(monkeypatch):
    sent: list[dict] = []

    def fake_deliver(recipient, subject, body, pdf_path=None):
        sent.append({"recipient": recipient, "subject": subject, "body": body})
        return "captured"

    monkeypatch.setattr(emailer, "_deliver", fake_deliver)
    return sent


class TestInviteEmailLinks:
    def _event_row(self, client, admin, db_session, **overrides) -> TrainingEvent:
        created = create_event(client, admin.headers, **overrides)
        return db_session.get(TrainingEvent, created["id"])

    def test_no_post_test_link_when_the_internal_test_has_no_questions(
        self, client, admin, db_session, captured_emails
    ):
        event = self._event_row(client, admin, db_session, test_mode="internal")
        emailer.send_invite_email(event, "Sam Lee", "sam.lee@example.com")
        body = captured_emails[0]["body"]
        assert "?test=" not in body and event.test_token not in body
        # The survey link is unaffected: only the broken action is withheld.
        assert event.survey_token in body

    def test_the_post_test_link_is_sent_once_questions_exist(
        self, client, admin, db_session, captured_emails
    ):
        event = self._event_row(
            client, admin, db_session, test_mode="internal", test_questions=TEST_QUESTIONS
        )
        emailer.send_invite_email(event, "Sam Lee", "sam.lee@example.com")
        assert event.test_token in captured_emails[0]["body"]

    def test_an_external_post_test_link_is_unaffected(
        self, client, admin, db_session, captured_emails
    ):
        event = self._event_row(
            client,
            admin,
            db_session,
            test_mode="external",
            post_test_url="https://forms.example.com/post-test",
        )
        emailer.send_invite_email(event, "Sam Lee", "sam.lee@example.com")
        assert "https://forms.example.com/post-test" in captured_emails[0]["body"]

    def test_an_email_with_nothing_to_ask_for_is_not_sent(
        self, client, admin, db_session, captured_emails
    ):
        event = self._event_row(
            client, admin, db_session, test_mode="internal", survey_mode="external"
        )
        with pytest.raises(RuntimeError, match="no post-test or survey link"):
            emailer.send_invite_email(event, "Sam Lee", "sam.lee@example.com")
        assert captured_emails == []


# --- 5. Distribution discarded every failure reason -------------------------


class TestDistributionReport:
    @pytest.fixture()
    def event(self, client, admin):
        event = create_event(client, admin.headers, title="Distribution CEU")
        upload_standard_roster(client, admin.headers, event["id"])
        return event

    def test_every_recipient_is_reported(self, client, admin, event, captured_emails):
        response = client.post(f"/api/events/{event['id']}/distribute", headers=admin.headers)
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["total"] == 4
        assert report["sent"] == 3
        assert report["skipped"] == 1
        assert report["failed"] == 0

        by_name = {row["full_name"]: row for row in report["recipients"]}
        assert by_name["Alice Nguyen"]["status"] == "sent"
        assert by_name["Alice Nguyen"]["reason"] is None
        # Cara's address is malformed, so there is nothing to retry until the
        # roster is fixed.
        assert by_name["Cara Fields"]["status"] == "skipped"
        assert "email" in by_name["Cara Fields"]["reason"]
        assert by_name["Cara Fields"]["retryable"] is False
        assert by_name["Cara Fields"]["attendee_id"] > 0
        assert by_name["Cara Fields"]["link_id"] > 0

    def test_a_delivery_failure_carries_its_reason_and_is_retryable(
        self, client, admin, event, monkeypatch
    ):
        def explode(_event, name, recipient, **_kwargs):
            if name == "Bob Ramos":
                raise RuntimeError("SMTP 550 mailbox unavailable")
            return "ok"

        monkeypatch.setattr("app.api.distribution.send_invite_email", explode)
        report = client.post(
            f"/api/events/{event['id']}/distribute", headers=admin.headers
        ).json()
        assert report["sent"] == 2
        assert report["failed"] == 1
        bob = next(row for row in report["recipients"] if row["full_name"] == "Bob Ramos")
        assert bob["status"] == "failed"
        assert bob["reason"] == "SMTP 550 mailbox unavailable"
        assert bob["retryable"] is True

    def test_failures_reach_the_audit_log_with_their_reasons(
        self, client, admin, event, db_session, monkeypatch
    ):
        def explode(_event, _name, _recipient, **_kwargs):
            raise RuntimeError("SMTP 550 mailbox unavailable")

        monkeypatch.setattr("app.api.distribution.send_invite_email", explode)
        client.post(f"/api/events/{event['id']}/distribute", headers=admin.headers)
        entry = [
            item for item in audit_actions(db_session, event["id"])
            if item.action == "event.distributed"
        ][-1]
        assert entry.details["sent"] == 0
        assert entry.details["failed"] == 3
        reasons = {problem["reason"] for problem in entry.details["problems"]}
        assert "SMTP 550 mailbox unavailable" in reasons
        assert len(entry.details["problems"]) == 4

    def test_an_unsendable_event_fails_every_recipient_with_the_reason(
        self, client, admin, captured_emails
    ):
        event = create_event(
            client,
            admin.headers,
            title="Nothing To Send CEU",
            test_mode="internal",
            survey_mode="external",
        )
        upload_standard_roster(client, admin.headers, event["id"])
        report = client.post(
            f"/api/events/{event['id']}/distribute", headers=admin.headers
        ).json()
        assert report["sent"] == 0
        assert report["failed"] == 3
        failed = [row for row in report["recipients"] if row["status"] == "failed"]
        assert all("no post-test or survey link" in row["reason"] for row in failed)


# --- 6. Destructive imports were not audited --------------------------------


class TestDestructiveImportAudit:
    def test_the_deletion_is_reconstructable_from_the_entry(self, client, admin, db_session):
        event = create_event(client, admin.headers, title="Wiped CEU")
        entry = record_destructive_import(
            db_session,
            event_id=event["id"],
            actor=None,
            file_type="post_test",
            filename="scores.xlsx",
            rows_in_file=31,
            names_parsed=0,
            cleared={"test_results": 24, "event_attendee_test_flags": 31},
            reason="no names parsed",
        )
        db_session.commit()

        stored = db_session.get(AuditLog, entry.id)
        assert stored.action == RESULTS_CLEARED_ACTION
        assert stored.entity_type == "training_event"
        assert stored.entity_id == event["id"]
        assert stored.event_id == event["id"]
        assert stored.created_at is not None
        assert stored.details["file_type"] == "post_test"
        assert stored.details["filename"] == "scores.xlsx"
        assert stored.details["reason"] == "no names parsed"
        assert stored.details["names_parsed"] == 0
        assert stored.details["rows_in_file"] == 31
        assert stored.details["cleared"] == {
            "test_results": 24,
            "event_attendee_test_flags": 31,
        }
        assert stored.details["rows_cleared"] == 55

    def test_the_actor_is_recorded_when_there_is_one(self, client, admin, db_session):
        from app.models.user import User

        event = create_event(client, admin.headers, title="Audited Wipe CEU")
        user = db_session.get(User, admin.id)
        entry = record_destructive_import(
            db_session,
            event_id=event["id"],
            actor=user,
            file_type="survey",
            cleared={"survey_results": 12},
            reason="survey re-import",
        )
        db_session.commit()
        assert db_session.get(AuditLog, entry.id).actor_id == admin.id

    def test_entries_are_queryable_by_action(self, client, admin, db_session):
        event = create_event(client, admin.headers, title="Queryable Wipe CEU")
        record_destructive_import(
            db_session,
            event_id=event["id"],
            actor=None,
            file_type="post_test",
            cleared={"test_results": 3},
            reason="post_test re-import",
        )
        db_session.commit()
        found = db_session.scalars(
            select(AuditLog).where(AuditLog.action == RESULTS_CLEARED_ACTION)
        ).all()
        assert len(found) == 1
        assert found[0].details["cleared"]["test_results"] == 3


def test_event_attendee_flags_are_untouched_by_a_refused_survey(client, admin, db_session):
    """Belt and braces: the refusal must not clear a flag that was already set."""
    event = create_event(client, admin.headers, survey_required=True, title="Flag Safety CEU")
    upload_standard_roster(client, admin.headers, event["id"])
    credited = submit_survey(
        client,
        event["survey_token"],
        full_name="Alice Nguyen",
        email="alice.nguyen@example.com",
        answers={"liked": "Mine"},
    )
    assert credited.status_code == 200, credited.text
    impostor = submit_survey(
        client, event["survey_token"], full_name="Alice Nguyen", answers={"liked": "Not mine"}
    )
    assert impostor.status_code == 200, impostor.text

    links = db_session.scalars(
        select(EventAttendee).where(EventAttendee.event_id == event["id"])
    ).all()
    alice = next(link for link in links if link.attendee.email == "alice.nguyen@example.com")
    assert alice.survey_completed is True
