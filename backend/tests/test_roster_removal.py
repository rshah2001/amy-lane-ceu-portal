"""Removing attendees from an event's roster.

This is the repair path for a roster holding the wrong people — the practice
events whose sign-in sheets merged names in from a different event before
attendee matching was scoped. Clearing the roster and re-uploading the sheet
rebuilds it from the file alone.
"""
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.certificate import Certificate
from app.models.certificate_email_log import CertificateEmailLog
from app.models.event_attendee import EventAttendee
from app.models.survey_result import SurveyResult
from app.models.test_result import TestResult
from helpers_api import (
    ATTENDANCE_CSV,
    compliance_rows_by_name,
    create_event,
    upload_csv,
    upload_standard_roster,
)


@pytest.fixture()
def event(client, admin):
    return create_event(client, admin.headers, title="Roster Cleanup CEU")


@pytest.fixture()
def rows(client, admin, event):
    upload_standard_roster(client, admin.headers, event["id"])
    # The standard roster covers registration/attendance/post_test only; a real
    # survey response is what makes the SurveyResult cleanup observable.
    submitted = client.post(
        f"/api/public/surveys/{event['survey_token']}",
        json={
            "full_name": "Bob Ramos",
            "email": "bob.ramos@example.com",
            "answers": {"liked": "Good session"},
        },
    )
    assert submitted.status_code == 200, submitted.text
    return compliance_rows_by_name(client, admin.headers, event["id"])


def names(client, headers, event_id) -> list[str]:
    response = client.get(f"/api/events/{event_id}/compliance", headers=headers)
    assert response.status_code == 200, response.text
    return sorted(row["full_name"] for row in response.json())


def issue_certificate(client, headers, event_id, link_id, *, send_it: bool) -> dict:
    """Approve, generate and optionally email a certificate; returns the certificate."""
    approve = client.post(
        f"/api/events/{event_id}/compliance/approve",
        json={"event_attendee_ids": [link_id], "approved": True, "override": True},
        headers=headers,
    )
    assert approve.status_code == 200, approve.text
    generated = client.post(
        f"/api/events/{event_id}/certificates/{link_id}/generate", headers=headers
    )
    assert generated.status_code == 200, generated.text
    if send_it:
        sent = client.post(f"/api/events/{event_id}/certificates/{link_id}/send", headers=headers)
        assert sent.status_code == 200, sent.text
    return generated.json()


def verifies_publicly(client, certificate_number: str) -> bool:
    response = client.get(f"/api/public/verify/{certificate_number}")
    assert response.status_code == 200, response.text
    return response.json()["valid"] is True


class TestRemoveOneAttendee:
    def test_removes_only_that_attendee(self, client, admin, event, rows):
        response = client.delete(
            f"/api/events/{event['id']}/compliance/{rows['Bob Ramos']['id']}",
            headers=admin.headers,
        )
        assert response.status_code == 200, response.text
        assert response.json() == {
            "removed": 1,
            "kept_with_issued_certificates": [],
            "revoked": [],
        }
        assert names(client, admin.headers, event["id"]) == [
            "Alice Nguyen",
            "Cara Fields",
            "Dan Poe",
        ]

    def test_event_results_go_with_the_attendee(
        self, client, admin, event, rows, db_session
    ):
        attendee_id = rows["Bob Ramos"]["attendee_id"]
        # Both rows must exist first, or the "gone afterwards" assertions below
        # would pass against a fixture that never created them.
        assert db_session.scalars(
            select(TestResult).where(
                TestResult.event_id == event["id"], TestResult.attendee_id == attendee_id
            )
        ).all()
        assert db_session.scalars(
            select(SurveyResult).where(
                SurveyResult.event_id == event["id"], SurveyResult.attendee_id == attendee_id
            )
        ).all()
        client.delete(
            f"/api/events/{event['id']}/compliance/{rows['Bob Ramos']['id']}",
            headers=admin.headers,
        )
        assert not db_session.scalars(
            select(TestResult).where(
                TestResult.event_id == event["id"], TestResult.attendee_id == attendee_id
            )
        ).all()
        assert not db_session.scalars(
            select(SurveyResult).where(
                SurveyResult.event_id == event["id"], SurveyResult.attendee_id == attendee_id
            )
        ).all()

    def test_anonymous_survey_responses_survive_a_removal(self, client, admin, event, rows, db_session):
        """Blind feedback has no attendee_id, so it belongs to the event, not a person."""
        anonymous = client.post(
            f"/api/public/surveys/{event['survey_token']}",
            json={"full_name": None, "email": None, "answers": {"liked": "Anonymous note"}},
        )
        assert anonymous.status_code == 200, anonymous.text
        client.delete(f"/api/events/{event['id']}/compliance", headers=admin.headers)
        surviving = db_session.scalars(
            select(SurveyResult).where(
                SurveyResult.event_id == event["id"], SurveyResult.attendee_id.is_(None)
            )
        ).all()
        assert len(surviving) == 1
        # The Survey Responses tab must still render after the roster is gone.
        listed = client.get(f"/api/survey-responses?event_id={event['id']}", headers=admin.headers)
        assert listed.status_code == 200, listed.text

    def test_generated_but_undelivered_certificate_is_removed(
        self, client, admin, event, rows, db_session
    ):
        """Nobody has this number yet, so a routine cleanup may drop it."""
        link_id = rows["Alice Nguyen"]["id"]
        issue_certificate(client, admin.headers, event["id"], link_id, send_it=False)
        assert db_session.scalars(
            select(Certificate).where(Certificate.event_attendee_id == link_id)
        ).all()
        response = client.delete(
            f"/api/events/{event['id']}/compliance/{link_id}", headers=admin.headers
        )
        assert response.status_code == 200, response.text
        assert not db_session.scalars(
            select(Certificate).where(Certificate.event_attendee_id == link_id)
        ).all()

    def test_certificate_pdf_is_deleted_from_storage(
        self, client, admin, event, rows, db_session
    ):
        link_id = rows["Alice Nguyen"]["id"]
        issue_certificate(client, admin.headers, event["id"], link_id, send_it=False)
        pdf = Path(
            db_session.scalar(
                select(Certificate.pdf_path).where(Certificate.event_attendee_id == link_id)
            )
        )
        assert pdf.exists()
        client.delete(f"/api/events/{event['id']}/compliance/{link_id}", headers=admin.headers)
        assert not pdf.exists()

    def test_email_logs_survive_a_revocation(self, client, admin, event, rows, db_session):
        """The delivery record is part of what the seven years covers.

        Email logs cascade off the certificate row, so before revocation existed
        the override deleted them too — erasing the evidence of who the wrong
        certificate was actually sent to, which is the one fact the revocation
        is about.
        """
        link_id = rows["Alice Nguyen"]["id"]
        issue_certificate(client, admin.headers, event["id"], link_id, send_it=True)
        assert db_session.scalars(select(CertificateEmailLog)).all()
        client.delete(
            f"/api/events/{event['id']}/compliance/{link_id}?include_sent=true",
            headers=admin.headers,
        )
        db_session.expire_all()
        assert db_session.scalars(select(CertificateEmailLog)).all()

    def test_undelivered_certificate_takes_its_email_logs_with_it(
        self, client, admin, event, rows, db_session
    ):
        """The cascade still applies to the certificates that may be deleted."""
        link_id = rows["Alice Nguyen"]["id"]
        certificate_id = issue_certificate(
            client, admin.headers, event["id"], link_id, send_it=False
        )["id"]
        db_session.add(
            CertificateEmailLog(
                certificate_id=certificate_id,
                recipient_email="alice.nguyen@example.com",
                status="failed",
                error_message="SMTP timeout",
            )
        )
        db_session.commit()
        client.delete(f"/api/events/{event['id']}/compliance/{link_id}", headers=admin.headers)
        db_session.expire_all()
        assert not db_session.scalars(select(CertificateEmailLog)).all()

    def test_sent_certificate_needs_an_explicit_override(
        self, client, admin, event, rows
    ):
        link_id = rows["Alice Nguyen"]["id"]
        number = issue_certificate(
            client, admin.headers, event["id"], link_id, send_it=True
        )["certificate_number"]
        assert verifies_publicly(client, number)

        blocked = client.delete(
            f"/api/events/{event['id']}/compliance/{link_id}", headers=admin.headers
        )
        assert blocked.status_code == 409
        assert "Alice Nguyen" in blocked.json()["detail"]
        assert "Alice Nguyen" in names(client, admin.headers, event["id"])
        # The rejected attempt must not have revoked anything.
        assert verifies_publicly(client, number)

        forced = client.delete(
            f"/api/events/{event['id']}/compliance/{link_id}?include_sent=true",
            headers=admin.headers,
        )
        assert forced.status_code == 200, forced.text
        # Revoked, not removed: the record is retained for seven years, so the
        # override withdraws the credential instead of destroying it.
        assert forced.json() == {
            "removed": 0,
            "kept_with_issued_certificates": [],
            "revoked": ["Alice Nguyen"],
        }
        assert not verifies_publicly(client, number)

    def test_downloaded_certificate_also_needs_the_override(self, client, admin, event, rows):
        """A certificate the holder pulled themselves never had sent_at set, but
        it is just as much in their hands as an emailed one."""
        link_id = rows["Alice Nguyen"]["id"]
        number = issue_certificate(
            client, admin.headers, event["id"], link_id, send_it=False
        )["certificate_number"]
        downloaded = client.get(f"/api/public/verify/{number}/download")
        assert downloaded.status_code == 200, downloaded.text
        assert compliance_rows_by_name(client, admin.headers, event["id"])["Alice Nguyen"][
            "certificate_sent_at"
        ] is None

        blocked = client.delete(
            f"/api/events/{event['id']}/compliance/{link_id}", headers=admin.headers
        )
        assert blocked.status_code == 409, blocked.text
        assert verifies_publicly(client, number)

        forced = client.delete(
            f"/api/events/{event['id']}/compliance/{link_id}?include_sent=true",
            headers=admin.headers,
        )
        assert forced.status_code == 200, forced.text
        assert not verifies_publicly(client, number)

    def test_downloaded_certificates_are_kept_by_a_roster_clear(self, client, admin, event, rows):
        link_id = rows["Alice Nguyen"]["id"]
        number = issue_certificate(
            client, admin.headers, event["id"], link_id, send_it=False
        )["certificate_number"]
        assert client.get(f"/api/public/verify/{number}/download").status_code == 200

        response = client.delete(f"/api/events/{event['id']}/compliance", headers=admin.headers)
        assert response.status_code == 200, response.text
        assert response.json() == {
            "removed": 3,
            "kept_with_issued_certificates": ["Alice Nguyen"],
            "revoked": [],
        }
        assert verifies_publicly(client, number)

    def test_attendee_from_another_event_is_not_found(self, client, admin, event, rows):
        other = create_event(client, admin.headers, title="Unrelated CEU")
        response = client.delete(
            f"/api/events/{other['id']}/compliance/{rows['Alice Nguyen']['id']}",
            headers=admin.headers,
        )
        assert response.status_code == 404

    def test_presenter_cannot_remove_attendees_even_when_assigned(
        self, client, admin, presenter, password_hash
    ):
        """Removal is admin-only; being the event's own presenter does not grant it."""
        assigned = create_event(
            client, admin.headers, title="Presenter Session", assigned_presenter_id=presenter.id
        )
        upload_standard_roster(client, admin.headers, assigned["id"])
        assert (
            client.get(f"/api/events/{assigned['id']}", headers=presenter.headers).status_code == 200
        ), "fixture broken: the presenter is not actually assigned to this event"
        link_id = compliance_rows_by_name(client, admin.headers, assigned["id"])["Alice Nguyen"]["id"]
        response = client.delete(
            f"/api/events/{assigned['id']}/compliance/{link_id}", headers=presenter.headers
        )
        assert response.status_code == 403
        assert len(names(client, admin.headers, assigned["id"])) == 4


class TestClearRoster:
    def test_clears_every_attendee(self, client, admin, event, rows):
        response = client.delete(
            f"/api/events/{event['id']}/compliance", headers=admin.headers
        )
        assert response.status_code == 200, response.text
        assert response.json() == {
            "removed": 4,
            "kept_with_issued_certificates": [],
            "revoked": [],
        }
        assert names(client, admin.headers, event["id"]) == []

    def test_reupload_rebuilds_the_roster_from_the_sheet_alone(
        self, client, admin, event, rows
    ):
        """Amy's repair for a polluted roster: clear it, upload the sheet again."""
        client.delete(f"/api/events/{event['id']}/compliance", headers=admin.headers)
        response = upload_csv(client, admin.headers, event["id"], "attendance", ATTENDANCE_CSV)
        assert response.status_code == 201, response.text
        assert names(client, admin.headers, event["id"]) == [
            "Alice Nguyen",
            "Bob Ramos",
            "Cara Fields",
        ]

    def test_sent_certificates_are_kept_and_reported(self, client, admin, event, rows):
        issue_certificate(
            client, admin.headers, event["id"], rows["Alice Nguyen"]["id"], send_it=True
        )
        response = client.delete(
            f"/api/events/{event['id']}/compliance", headers=admin.headers
        )
        assert response.status_code == 200, response.text
        assert response.json() == {
            "removed": 3,
            "kept_with_issued_certificates": ["Alice Nguyen"],
            "revoked": [],
        }
        assert names(client, admin.headers, event["id"]) == ["Alice Nguyen"]

    def test_include_sent_revokes_rather_than_clearing_a_delivered_certificate(
        self, client, admin, event, rows
    ):
        """The override empties the roster of everyone it is allowed to delete.

        The one attendee holding a delivered certificate keeps a row, because
        deleting it would take the certificate with it (the FK cascades) and
        that record is retained for seven years. Their certificate is revoked
        and the response says so separately from the three that were removed.
        """
        issue_certificate(
            client, admin.headers, event["id"], rows["Alice Nguyen"]["id"], send_it=True
        )
        response = client.delete(
            f"/api/events/{event['id']}/compliance?include_sent=true", headers=admin.headers
        )
        assert response.status_code == 200, response.text
        assert response.json() == {
            "removed": 3,
            "kept_with_issued_certificates": [],
            "revoked": ["Alice Nguyen"],
        }
        assert names(client, admin.headers, event["id"]) == ["Alice Nguyen"]

    def test_other_events_are_untouched(self, client, admin, event, rows):
        other = create_event(client, admin.headers, title="Untouched CEU")
        upload_standard_roster(client, admin.headers, other["id"])
        client.delete(f"/api/events/{event['id']}/compliance", headers=admin.headers)
        assert names(client, admin.headers, other["id"]) == [
            "Alice Nguyen",
            "Bob Ramos",
            "Cara Fields",
            "Dan Poe",
        ]

    def test_presenter_cannot_clear_the_roster_even_when_assigned(
        self, client, admin, presenter
    ):
        assigned = create_event(
            client, admin.headers, title="Presenter Session", assigned_presenter_id=presenter.id
        )
        upload_standard_roster(client, admin.headers, assigned["id"])
        assert (
            client.get(f"/api/events/{assigned['id']}", headers=presenter.headers).status_code == 200
        ), "fixture broken: the presenter is not actually assigned to this event"
        response = client.delete(
            f"/api/events/{assigned['id']}/compliance", headers=presenter.headers
        )
        assert response.status_code == 403
        assert len(names(client, admin.headers, assigned["id"])) == 4

    def test_removal_is_audited(self, client, admin, event, rows, db_session):
        client.delete(f"/api/events/{event['id']}/compliance", headers=admin.headers)
        response = client.get(
            f"/api/audit-logs?event_id={event['id']}", headers=admin.headers
        )
        assert response.status_code == 200, response.text
        entries = response.json()
        actions = [entry["action"] for entry in entries]
        assert actions.count("attendee.removed") == 4
        assert "roster.cleared" in actions
        # The details payload is the only forensic record of who was removed,
        # so pin its shape rather than just the action name.
        alice = next(
            entry for entry in entries
            if entry["action"] == "attendee.removed"
            and entry["details"]["full_name"] == "Alice Nguyen"
        )
        assert alice["details"]["email"] == "alice.nguyen@example.com"
        assert alice["details"]["attendee_id"] == rows["Alice Nguyen"]["attendee_id"]

    def test_the_global_attendee_record_survives(self, client, admin, event, rows, db_session):
        """Clearing one roster must not erase the person from other events."""
        other = create_event(client, admin.headers, title="Second CEU")
        upload_standard_roster(client, admin.headers, other["id"])
        client.delete(f"/api/events/{event['id']}/compliance", headers=admin.headers)
        remaining = db_session.scalars(
            select(EventAttendee).where(EventAttendee.event_id == other["id"])
        ).all()
        assert len(remaining) == 4
