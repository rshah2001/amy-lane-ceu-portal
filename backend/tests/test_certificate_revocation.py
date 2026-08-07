"""Revoking a certificate instead of deleting it.

An admin still needs the remedy for a certificate issued to the wrong person —
a name read off the wrong sign-in sheet — but
``docs/data-storage-and-retention-confirmation.md`` commits to keeping issued
certificate records for seven years, and the override on the roster-removal
route used to cut straight through that floor.

So the remedy is revocation: the row, its PDF, its email logs and its audit
trail all survive the retention window, the credential stops being valid, and
the public portal answers "revoked" to anyone holding the document.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.audit_log import AuditLog
from app.models.certificate import Certificate
from app.models.event_attendee import EventAttendee
from app.models.survey_result import SurveyResult
from app.models.test_result import TestResult
from app.models.training_event import TrainingEvent
from helpers_api import compliance_rows_by_name, create_event, upload_standard_roster


@pytest.fixture()
def event(client, admin):
    return create_event(client, admin.headers, title="Revocation CEU")


@pytest.fixture()
def rows(client, admin, event):
    upload_standard_roster(client, admin.headers, event["id"])
    submitted = client.post(
        f"/api/public/surveys/{event['survey_token']}",
        json={
            "full_name": "Alice Nguyen",
            "email": "alice.nguyen@example.com",
            "answers": {"liked": "Good session"},
        },
    )
    assert submitted.status_code == 200, submitted.text
    return compliance_rows_by_name(client, admin.headers, event["id"])


def issue(client, headers, event_id, link_id, *, send_it: bool = True) -> dict:
    """Approve, generate and (by default) email a certificate."""
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


@pytest.fixture()
def issued(client, admin, event, rows):
    """One delivered certificate for Alice, the wrong-person candidate."""
    link_id = rows["Alice Nguyen"]["id"]
    certificate = issue(client, admin.headers, event["id"], link_id)
    return {"link_id": link_id, "certificate": certificate, "number": certificate["certificate_number"]}


def revoke(client, headers, event_id, link_id, *, reason: str | None = None):
    query = "?include_sent=true" + (f"&reason={reason}" if reason else "")
    return client.delete(f"/api/events/{event_id}/compliance/{link_id}{query}", headers=headers)


def backdate_past_retention(db_session, event_id: int, certificate_id: int) -> None:
    """Move an event and its certificate outside the retention window."""
    years = settings.retention_years + 1
    old_date = date.today() - timedelta(days=365 * years + years // 4)
    old_stamp = datetime.now(timezone.utc) - timedelta(days=365 * years + years // 4)
    event = db_session.scalar(select(TrainingEvent).where(TrainingEvent.id == event_id))
    event.event_date = old_date
    certificate = db_session.scalar(select(Certificate).where(Certificate.id == certificate_id))
    certificate.generated_at = old_stamp
    if certificate.sent_at:
        certificate.sent_at = old_stamp
    db_session.commit()


class TestTheRecordSurvives:
    def test_the_certificate_row_is_kept(self, client, admin, event, issued, db_session):
        response = revoke(client, admin.headers, event["id"], issued["link_id"])
        assert response.status_code == 200, response.text
        db_session.expire_all()
        certificate = db_session.scalar(
            select(Certificate).where(Certificate.id == issued["certificate"]["id"])
        )
        assert certificate is not None
        assert certificate.revoked_at is not None

    def test_the_pdf_is_kept(self, client, admin, event, issued, db_session):
        pdf = Path(
            db_session.scalar(
                select(Certificate.pdf_path).where(
                    Certificate.id == issued["certificate"]["id"]
                )
            )
        )
        assert pdf.exists()
        revoke(client, admin.headers, event["id"], issued["link_id"])
        assert pdf.exists(), "the retained record includes the document itself"

    def test_the_link_row_is_kept(self, client, admin, event, issued, db_session):
        """The FK is the reason: certificates.event_attendee_id is NOT NULL and
        ON DELETE CASCADE, so deleting the link deletes the certificate."""
        revoke(client, admin.headers, event["id"], issued["link_id"])
        db_session.expire_all()
        assert db_session.scalar(
            select(EventAttendee).where(EventAttendee.id == issued["link_id"])
        ) is not None

    def test_who_when_and_why_are_recorded(self, client, admin, event, issued, db_session):
        revoke(client, admin.headers, event["id"], issued["link_id"], reason="Wrong sign-in sheet")
        db_session.expire_all()
        certificate = db_session.scalar(
            select(Certificate).where(Certificate.id == issued["certificate"]["id"])
        )
        assert certificate.revoked_by_id == admin.id
        assert certificate.revoked_reason == "Wrong sign-in sheet"
        assert certificate.revoked_at is not None

    def test_the_reason_is_optional(self, client, admin, event, issued, db_session):
        revoke(client, admin.headers, event["id"], issued["link_id"])
        db_session.expire_all()
        certificate = db_session.scalar(
            select(Certificate).where(Certificate.id == issued["certificate"]["id"])
        )
        assert certificate.revoked_reason is None
        assert certificate.revoked_at is not None

    def test_an_over_long_reason_is_rejected(self, client, admin, event, issued):
        response = revoke(client, admin.headers, event["id"], issued["link_id"], reason="x" * 501)
        assert response.status_code == 422

    def test_revoking_twice_does_not_rewrite_the_first_revocation(
        self, client, admin, event, issued, db_session
    ):
        revoke(client, admin.headers, event["id"], issued["link_id"], reason="Wrong person")
        db_session.expire_all()
        first = db_session.scalar(
            select(Certificate).where(Certificate.id == issued["certificate"]["id"])
        )
        original_at, original_reason = first.revoked_at, first.revoked_reason

        again = revoke(client, admin.headers, event["id"], issued["link_id"], reason="Changed mind")
        assert again.status_code == 200, again.text
        assert again.json()["revoked"] == ["Alice Nguyen"]
        db_session.expire_all()
        second = db_session.scalar(
            select(Certificate).where(Certificate.id == issued["certificate"]["id"])
        )
        assert second.revoked_at == original_at
        assert second.revoked_reason == original_reason

    def test_revocation_is_audited(self, client, admin, event, issued, db_session):
        revoke(client, admin.headers, event["id"], issued["link_id"], reason="Wrong person")
        entry = db_session.scalar(
            select(AuditLog).where(AuditLog.action == "certificate.revoked")
        )
        assert entry is not None
        assert entry.actor_id == admin.id
        assert entry.details["full_name"] == "Alice Nguyen"
        assert entry.details["certificate_number"] == issued["number"]
        assert entry.details["reason"] == "Wrong person"
        assert entry.details["certificate_sent"] is True
        # Explains, on its own, why the row is still in the database.
        assert entry.details["retained_until"].startswith(
            str(date.today().year + settings.retention_years)
        )

    def test_a_removal_that_deletes_is_still_audited_as_a_removal(
        self, client, admin, event, rows, db_session
    ):
        """Only the retained path becomes a revocation; the rest is unchanged."""
        client.delete(
            f"/api/events/{event['id']}/compliance/{rows['Dan Poe']['id']}", headers=admin.headers
        )
        actions = [entry.action for entry in db_session.scalars(select(AuditLog))]
        assert "attendee.removed" in actions
        assert "certificate.revoked" not in actions


class TestRosterDetachment:
    def test_the_attendee_stops_counting_as_a_participant(
        self, client, admin, event, issued
    ):
        revoke(client, admin.headers, event["id"], issued["link_id"])
        row = compliance_rows_by_name(client, admin.headers, event["id"])["Alice Nguyen"]
        assert row["attended"] is False
        assert row["registered"] is False
        assert row["approved"] is False
        assert row["eligible"] is False
        assert row["test_completed"] is False
        assert row["survey_completed"] is False

    def test_the_event_results_go_with_them(
        self, client, admin, event, issued, rows, db_session
    ):
        attendee_id = rows["Alice Nguyen"]["attendee_id"]
        assert db_session.scalars(
            select(TestResult).where(TestResult.attendee_id == attendee_id)
        ).all()
        assert db_session.scalars(
            select(SurveyResult).where(SurveyResult.attendee_id == attendee_id)
        ).all()
        revoke(client, admin.headers, event["id"], issued["link_id"])
        db_session.expire_all()
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

    def test_the_row_reports_itself_as_revoked(self, client, admin, event, issued):
        revoke(client, admin.headers, event["id"], issued["link_id"])
        row = compliance_rows_by_name(client, admin.headers, event["id"])["Alice Nguyen"]
        assert row["lifecycle_status"] == "revoked"
        assert row["certificate_revoked_at"] is not None
        # The number is still theirs and still resolvable — that is the point.
        assert row["certificate_number"] == issued["number"]

    def test_revoked_outranks_the_delivery_milestones(self, client, admin, event, issued):
        """It was emailed and downloaded; "downloaded" would read as in-good-standing."""
        assert client.get(f"/api/public/verify/{issued['number']}/download").status_code == 200
        revoke(client, admin.headers, event["id"], issued["link_id"])
        row = compliance_rows_by_name(client, admin.headers, event["id"])["Alice Nguyen"]
        assert row["certificate_sent_at"] is not None
        assert row["certificate_downloaded_at"] is not None
        assert row["lifecycle_status"] == "revoked"

    def test_other_attendees_are_untouched(self, client, admin, event, issued):
        revoke(client, admin.headers, event["id"], issued["link_id"])
        rows_now = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows_now["Bob Ramos"]["attended"] is True
        assert rows_now["Bob Ramos"]["lifecycle_status"] != "revoked"


class TestPublicVerification:
    def test_a_revoked_certificate_verifies_as_revoked(self, client, admin, event, issued):
        revoke(client, admin.headers, event["id"], issued["link_id"])
        response = client.get(f"/api/public/verify/{issued['number']}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["valid"] is False
        assert body["status"] == "revoked"
        assert body["revoked_at"] is not None
        # Not "not found": whoever is holding the PDF has to be able to tell the
        # difference between a mistyped number and a withdrawn certificate.
        assert body["certificate_number"] == issued["number"]
        assert body["attendee_name"] == "Alice Nguyen"
        assert body["event_title"] == event["title"]

    def test_it_no_longer_states_the_credit_it_used_to_grant(
        self, client, admin, event, issued
    ):
        revoke(client, admin.headers, event["id"], issued["link_id"])
        body = client.get(f"/api/public/verify/{issued['number']}").json()
        assert body["ceu_hours"] is None
        assert body["course_instructor"] is None

    def test_an_unknown_number_is_still_simply_unknown(self, client):
        body = client.get("/api/public/verify/CEU-00000-NOPE").json()
        assert body["valid"] is False
        assert body["status"] is None
        assert body["revoked_at"] is None

    def test_a_live_certificate_is_unaffected(self, client, admin, event, issued):
        body = client.get(f"/api/public/verify/{issued['number']}").json()
        assert body["valid"] is True
        assert body["status"] == "sent"
        assert body["revoked_at"] is None
        assert body["ceu_hours"] is not None

    def test_the_public_download_refuses_a_revoked_certificate(
        self, client, admin, event, issued, db_session
    ):
        revoke(client, admin.headers, event["id"], issued["link_id"])
        response = client.get(f"/api/public/verify/{issued['number']}/download")
        assert response.status_code == 410, response.text
        assert "revoked" in response.json()["detail"].lower()

    def test_a_refused_download_does_not_record_a_download(
        self, client, admin, event, rows, db_session
    ):
        """downloaded_at is load-bearing (it marks a certificate as issued), so
        the refusal has to happen before anything is written."""
        link_id = rows["Bob Ramos"]["id"]
        certificate = issue(client, admin.headers, event["id"], link_id, send_it=True)
        revoke(client, admin.headers, event["id"], link_id)
        client.get(f"/api/public/verify/{certificate['certificate_number']}/download")
        db_session.expire_all()
        stored = db_session.scalar(
            select(Certificate).where(Certificate.id == certificate["id"])
        )
        assert stored.downloaded_at is None


class TestCertificateRoutes:
    def test_an_admin_can_still_download_it_for_the_record(
        self, client, admin, event, issued
    ):
        revoke(client, admin.headers, event["id"], issued["link_id"])
        response = client.get(
            f"/api/events/{event['id']}/certificates/{issued['certificate']['id']}/download",
            headers=admin.headers,
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "application/pdf"

    def test_it_cannot_be_re_sent(self, client, admin, event, issued):
        revoke(client, admin.headers, event["id"], issued["link_id"])
        response = client.post(
            f"/api/events/{event['id']}/certificates/{issued['link_id']}/send",
            headers=admin.headers,
        )
        assert response.status_code == 409, response.text
        assert "revoked" in response.json()["detail"].lower()

    def test_it_cannot_be_regenerated(self, client, admin, event, issued):
        """event_attendee_id is unique, so "generate" would hand back the
        revoked row rather than mint a replacement."""
        revoke(client, admin.headers, event["id"], issued["link_id"])
        client.post(
            f"/api/events/{event['id']}/compliance/approve",
            json={"event_attendee_ids": [issued["link_id"]], "approved": True, "override": True},
            headers=admin.headers,
        )
        response = client.post(
            f"/api/events/{event['id']}/certificates/{issued['link_id']}/generate",
            headers=admin.headers,
        )
        assert response.status_code == 409, response.text

    def test_a_manual_issue_cannot_resurrect_it(self, client, admin, event, issued):
        revoke(client, admin.headers, event["id"], issued["link_id"])
        response = client.post(
            f"/api/events/{event['id']}/certificates/issue",
            json={"full_name": "Alice Nguyen", "email": "alice.nguyen@example.com"},
            headers=admin.headers,
        )
        assert response.status_code == 409, response.text

    def test_send_all_skips_it(self, client, admin, event, rows, db_session):
        """Revoked but never emailed: send-all must not be the way back out."""
        link_id = rows["Alice Nguyen"]["id"]
        certificate = issue(client, admin.headers, event["id"], link_id, send_it=False)
        assert client.get(f"/api/public/verify/{certificate['certificate_number']}/download").status_code == 200
        revoke(client, admin.headers, event["id"], link_id)

        response = client.post(
            f"/api/events/{event['id']}/certificates/send-all", headers=admin.headers
        )
        assert response.status_code == 200, response.text
        db_session.expire_all()
        stored = db_session.scalar(select(Certificate).where(Certificate.id == certificate["id"]))
        assert stored.sent_at is None


class TestRetentionBoundary:
    def test_inside_the_window_it_is_revoked(self, client, admin, event, issued):
        response = revoke(client, admin.headers, event["id"], issued["link_id"])
        assert response.json() == {
            "removed": 0,
            "kept_with_issued_certificates": [],
            "revoked": ["Alice Nguyen"],
        }

    def test_past_the_window_the_old_delete_still_stands(
        self, client, admin, event, issued, db_session
    ):
        """Retention is a floor, not a prohibition. Once it has elapsed there is
        nothing left to keep, so the override deletes as it always did."""
        backdate_past_retention(db_session, event["id"], issued["certificate"]["id"])
        response = revoke(client, admin.headers, event["id"], issued["link_id"])
        assert response.status_code == 200, response.text
        assert response.json() == {
            "removed": 1,
            "kept_with_issued_certificates": [],
            "revoked": [],
        }
        db_session.expire_all()
        assert db_session.scalar(
            select(Certificate).where(Certificate.id == issued["certificate"]["id"])
        ) is None

    def test_a_revoked_certificate_still_blocks_deleting_its_event(
        self, client, admin, event, issued, db_session
    ):
        """Revoking is not a way around the retention floor by another route."""
        revoke(client, admin.headers, event["id"], issued["link_id"])
        response = client.delete(f"/api/events/{event['id']}", headers=admin.headers)
        assert response.status_code == 409, response.text
        assert f"{settings.retention_years} years" in response.json()["detail"]

    def test_the_purge_eventually_takes_it(self, client, admin, event, issued, db_session):
        from app.services import retention

        revoke(client, admin.headers, event["id"], issued["link_id"], reason="Wrong person")
        backdate_past_retention(db_session, event["id"], issued["certificate"]["id"])

        preview = retention.purge_expired(db_session)
        assert preview.dry_run is True
        entry = next(item for item in preview.events if item.event_id == event["id"])
        assert entry.certificates_revoked == 1
        assert entry.as_details()["certificates_revoked"] == 1
        assert db_session.scalar(
            select(Certificate).where(Certificate.id == issued["certificate"]["id"])
        ) is not None

        pdf = Path(
            db_session.scalar(
                select(Certificate.pdf_path).where(
                    Certificate.id == issued["certificate"]["id"]
                )
            )
        )
        retention.purge_expired(db_session, apply=True)
        db_session.expire_all()
        assert db_session.scalar(
            select(Certificate).where(Certificate.id == issued["certificate"]["id"])
        ) is None
        assert not pdf.exists()
