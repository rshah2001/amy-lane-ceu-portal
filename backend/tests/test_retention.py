"""Record retention: the minimum-retention floor and the operator-run purge.

We attest to the CEU accrediting body that issued certificates are kept for
seven years and destroyed after that. Both halves are enforced here: an event
holding a live certificate cannot be deleted, and the purge that eventually
removes expired records only deletes when it is explicitly told to.
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
from app.models.training_event import TrainingEvent
from app.services import retention
from helpers_api import compliance_rows_by_name, create_event, upload_standard_roster


def issue_certificate(client, headers, db_session, *, send: bool, **event_overrides) -> dict:
    """An event with one approved attendee holding a certificate."""
    event = create_event(client, headers, **event_overrides)
    upload_standard_roster(client, headers, event["id"])
    rows = compliance_rows_by_name(client, headers, event["id"])
    link_id = rows["Alice Nguyen"]["id"]
    approve = client.post(
        f"/api/events/{event['id']}/compliance/approve",
        json={"event_attendee_ids": [link_id], "approved": True},
        headers=headers,
    )
    assert approve.status_code == 200, approve.text
    generated = client.post(
        f"/api/events/{event['id']}/certificates/{link_id}/generate", headers=headers
    )
    assert generated.status_code == 200, generated.text
    if send:
        sent = client.post(
            f"/api/events/{event['id']}/certificates/{link_id}/send", headers=headers
        )
        assert sent.status_code == 200, sent.text
    certificate = db_session.scalar(
        select(Certificate).where(Certificate.id == generated.json()["id"])
    )
    db_session.refresh(certificate)
    return {"event": event, "link_id": link_id, "certificate": certificate}


def backdate(db_session, event_id: int, certificate: Certificate, years: int) -> None:
    """Move an event and its certificate far enough back to expire."""
    event = db_session.scalar(select(TrainingEvent).where(TrainingEvent.id == event_id))
    event.event_date = date.today() - timedelta(days=365 * years + years // 4)
    old = datetime.now(timezone.utc) - timedelta(days=365 * years + years // 4)
    certificate.generated_at = old
    if certificate.sent_at:
        certificate.sent_at = old
    db_session.commit()


def delete_event(client, headers, event_id: int):
    return client.delete(f"/api/events/{event_id}", headers=headers)


class TestMinimumRetentionGuard:
    """DELETE /events/{id} must not be able to destroy a live certificate."""

    def test_event_with_an_issued_certificate_cannot_be_deleted(
        self, client, admin, db_session
    ):
        issued = issue_certificate(client, admin.headers, db_session, send=True)
        response = delete_event(client, admin.headers, issued["event"]["id"])
        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        # The admin has to be told why and when, not just "no".
        assert f"{settings.retention_years} years" in detail
        deletable_on = date.today().replace(year=date.today().year + settings.retention_years)
        assert str(deletable_on.year) in detail
        # Nothing was destroyed.
        assert (
            client.get(f"/api/events/{issued['event']['id']}", headers=admin.headers).status_code
            == 200
        )
        assert db_session.scalar(select(Certificate).where(Certificate.id == issued["certificate"].id))

    def test_refusal_is_audited(self, client, admin, db_session):
        issued = issue_certificate(client, admin.headers, db_session, send=True)
        assert delete_event(client, admin.headers, issued["event"]["id"]).status_code == 409
        entry = db_session.scalar(
            select(AuditLog).where(AuditLog.action == "event.delete_blocked")
        )
        assert entry is not None
        assert entry.details["reason"] == "retention_period"
        assert entry.details["issued_certificates"] == 1

    def test_a_certificate_the_holder_downloaded_also_blocks_deletion(
        self, client, admin, db_session
    ):
        # Never emailed, but the holder pulled it from the public portal, so it
        # is just as much a live credential.
        issued = issue_certificate(client, admin.headers, db_session, send=False)
        issued["certificate"].downloaded_at = datetime.now(timezone.utc)
        db_session.commit()
        assert delete_event(client, admin.headers, issued["event"]["id"]).status_code == 409

    def test_certificate_that_never_reached_anyone_does_not_block(
        self, client, admin, db_session
    ):
        # Generated but never sent or downloaded: nobody holds it, so cleaning
        # up the event is still an ordinary admin action.
        issued = issue_certificate(client, admin.headers, db_session, send=False)
        assert delete_event(client, admin.headers, issued["event"]["id"]).status_code == 204

    def test_event_without_certificates_is_freely_deletable(self, client, admin):
        event = create_event(client, admin.headers, title="Draft Session")
        assert delete_event(client, admin.headers, event["id"]).status_code == 204

    def test_deletable_once_the_retention_period_has_elapsed(self, client, admin, db_session):
        issued = issue_certificate(client, admin.headers, db_session, send=True)
        backdate(db_session, issued["event"]["id"], issued["certificate"], settings.retention_years + 1)
        assert delete_event(client, admin.headers, issued["event"]["id"]).status_code == 204


class TestRetentionWindow:
    def test_clock_runs_from_the_later_of_event_date_and_issue_date(
        self, client, admin, db_session
    ):
        """A certificate issued long after the event keeps its own full window."""
        issued = issue_certificate(client, admin.headers, db_session, send=True)
        event = db_session.scalar(
            select(TrainingEvent).where(TrainingEvent.id == issued["event"]["id"])
        )
        event.event_date = date(2020, 1, 1)
        issued["certificate"].generated_at = datetime(2024, 6, 1, tzinfo=timezone.utc)
        db_session.commit()
        assert retention.retained_until(event, [issued["certificate"]]) == date(
            2024 + settings.retention_years, 6, 1
        )

    @pytest.mark.parametrize(
        "anchor,expected",
        [(date(2020, 2, 29), date(2027, 3, 1)), (date(2021, 6, 15), date(2028, 6, 15))],
    )
    def test_leap_day_anchor_never_shortens_the_window(self, anchor, expected):
        assert retention._add_years(anchor, 7) == expected


class TestPurge:
    """purge_expired is a dry run unless it is explicitly told to apply."""

    @pytest.fixture()
    def expired(self, client, admin, db_session):
        issued = issue_certificate(client, admin.headers, db_session, send=True)
        backdate(db_session, issued["event"]["id"], issued["certificate"], settings.retention_years + 1)
        return issued

    def test_dry_run_is_the_default_and_deletes_nothing(self, db_session, expired):
        pdf_path = Path(expired["certificate"].pdf_path)
        report = retention.purge_expired(db_session)
        assert report.dry_run is True
        assert report.event_count == 1
        assert report.certificate_count == 1
        assert report.attendee_link_count == 4
        assert "would purge" in report.describe()
        assert "Re-run with --apply" in report.describe()
        # Still all there.
        assert db_session.scalar(select(Certificate).where(Certificate.id == expired["certificate"].id))
        assert pdf_path.exists()

    def test_apply_removes_rows_and_files_and_audits_the_purge(self, db_session, expired):
        event_id = expired["event"]["id"]
        pdf_path = Path(expired["certificate"].pdf_path)
        assert pdf_path.exists()

        report = retention.purge_expired(db_session, apply=True)

        assert report.dry_run is False
        assert report.event_count == 1
        assert db_session.scalar(select(TrainingEvent).where(TrainingEvent.id == event_id)) is None
        assert not db_session.scalars(
            select(EventAttendee).where(EventAttendee.event_id == event_id)
        ).all()
        assert db_session.scalar(select(Certificate).where(Certificate.id == expired["certificate"].id)) is None
        assert not pdf_path.exists()
        # The audit row outlives the record it describes.
        entry = db_session.scalar(select(AuditLog).where(AuditLog.action == "retention.purged"))
        assert entry is not None
        assert entry.details["certificates"] == 1
        assert entry.details["retention_years"] == settings.retention_years

    def test_records_inside_the_window_are_left_alone(self, client, admin, db_session):
        issued = issue_certificate(client, admin.headers, db_session, send=True)
        report = retention.purge_expired(db_session, apply=True)
        assert report.event_count == 0
        assert db_session.scalar(
            select(TrainingEvent).where(TrainingEvent.id == issued["event"]["id"])
        )

    def test_certificate_issued_late_keeps_an_old_event_alive(self, client, admin, db_session):
        issued = issue_certificate(client, admin.headers, db_session, send=True)
        event = db_session.scalar(
            select(TrainingEvent).where(TrainingEvent.id == issued["event"]["id"])
        )
        # Event is well past retention, but the certificate was issued recently.
        event.event_date = date.today().replace(year=date.today().year - settings.retention_years - 2)
        db_session.commit()
        report = retention.purge_expired(db_session, apply=True)
        assert report.event_count == 0
        assert db_session.scalar(select(TrainingEvent).where(TrainingEvent.id == event.id))

    def test_cli_entrypoint_defaults_to_dry_run(self, db_session, expired, monkeypatch, capsys):
        """`python -m app.services.retention` must not delete anything."""
        import app.db.session as db_module

        monkeypatch.setattr(db_module, "SessionLocal", lambda: db_session)
        monkeypatch.setattr(db_session, "close", lambda: None)

        assert retention.main([]) == 0

        assert "[DRY RUN]" in capsys.readouterr().out
        assert db_session.scalar(
            select(TrainingEvent).where(TrainingEvent.id == expired["event"]["id"])
        )

    def test_cli_apply_flag_performs_the_purge(self, db_session, expired, monkeypatch):
        import app.db.session as db_module

        monkeypatch.setattr(db_module, "SessionLocal", lambda: db_session)
        monkeypatch.setattr(db_session, "close", lambda: None)

        assert retention.main(["--apply"]) == 0

        assert db_session.scalar(
            select(TrainingEvent).where(TrainingEvent.id == expired["event"]["id"])
        ) is None
