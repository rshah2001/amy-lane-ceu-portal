"""A certificate number must always identify one document.

The regeneration path (used when the PDF is missing from storage -- an
ephemeral disk, a redeploy, a purged cache) used to re-render from the *live*
event row, so renaming an event silently changed the contents of certificates
that had already been issued under it. These tests pin the fix: regeneration
renders from the snapshot captured at issue time.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest
from pypdf import PdfReader
from sqlalchemy import select

from app.models.certificate import Certificate
from app.models.event_attendee import EventAttendee
from app.services.certificates import (
    certificate_snapshot,
    content_from_snapshot,
    reissue_certificate_pdf,
)
from helpers_api import compliance_rows_by_name, create_event, upload_standard_roster

ORIGINAL_TITLE = "Adaptive Driving Controls (2026 Edition)"
ORIGINAL_INSTRUCTOR = "Dr. Alice Marks"


@pytest.fixture()
def issued(client, admin, db_session):
    """An event with one approved attendee holding a generated certificate."""
    event = create_event(
        client,
        admin.headers,
        title=ORIGINAL_TITLE,
        course_instructor=ORIGINAL_INSTRUCTOR,
        certificate_title="Certificate of CEU Completion",
    )
    upload_standard_roster(client, admin.headers, event["id"])
    rows = compliance_rows_by_name(client, admin.headers, event["id"])
    link_id = rows["Alice Nguyen"]["id"]
    approve = client.post(
        f"/api/events/{event['id']}/compliance/approve",
        json={"event_attendee_ids": [link_id], "approved": True},
        headers=admin.headers,
    )
    assert approve.status_code == 200, approve.text
    response = client.post(
        f"/api/events/{event['id']}/certificates/{link_id}/generate", headers=admin.headers
    )
    assert response.status_code == 200, response.text
    certificate = db_session.scalar(
        select(Certificate).where(Certificate.id == response.json()["id"])
    )
    return {
        "event": event,
        "link_id": link_id,
        "certificate": certificate,
        "path": Path(certificate.pdf_path),
    }


def pdf_text(data: bytes | Path) -> str:
    source = data if isinstance(data, Path) else __import__("io").BytesIO(data)
    return "\n".join(page.extract_text() or "" for page in PdfReader(source).pages)


def rename_event(client, headers, event_id: int) -> None:
    """Everything a certificate prints, changed after issue."""
    response = client.put(
        f"/api/events/{event_id}",
        json={
            "title": "Completely Different Course",
            "course_instructor": "Someone Else Entirely",
            "certificate_title": "Award of Attendance",
            "ceu_hours": 9.0,
            "event_date": "2030-01-02",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text


class TestSnapshotRegeneration:
    def test_snapshot_is_written_with_everything_the_renderer_needs(self, issued):
        snapshot = issued["certificate"].event_snapshot
        assert snapshot["event_title"] == ORIGINAL_TITLE
        assert snapshot["fields"]["attendee_name"] == "Alice Nguyen"
        assert snapshot["fields"]["course_instructor"] == ORIGINAL_INSTRUCTOR
        # Field placement is part of the document's appearance, so it has to be
        # in the record too.
        assert "certificate_fields" in snapshot
        assert content_from_snapshot(snapshot) is not None

    def test_reissued_pdf_is_the_document_that_was_issued(
        self, client, admin, db_session, issued
    ):
        original_bytes = issued["path"].read_bytes()
        assert ORIGINAL_TITLE in pdf_text(issued["path"])

        rename_event(client, admin.headers, issued["event"]["id"])
        # Simulate the ephemeral disk losing the PDF; the DB row survives.
        issued["path"].unlink()

        response = client.get(
            f"/api/events/{issued['event']['id']}/certificates/{issued['certificate'].id}/download",
            headers=admin.headers,
        )
        assert response.status_code == 200, response.text
        text = pdf_text(response.content)
        assert ORIGINAL_TITLE in text
        assert ORIGINAL_INSTRUCTOR in text
        assert "Completely Different Course" not in text
        assert "Someone Else Entirely" not in text
        assert "CERTIFICATE OF CEU COMPLETION" in text.upper()
        # Same certificate number, same document -- literally the same bytes.
        assert response.content == original_bytes

    def test_resend_attaches_the_original_document(self, client, admin, issued):
        original_bytes = issued["path"].read_bytes()
        rename_event(client, admin.headers, issued["event"]["id"])
        issued["path"].unlink()

        response = client.post(
            f"/api/events/{issued['event']['id']}/certificates/{issued['link_id']}/send",
            headers=admin.headers,
        )
        assert response.status_code == 200, response.text
        assert issued["path"].read_bytes() == original_bytes

    def test_rendering_is_deterministic(self, db_session, issued):
        """Two renders of the same record are byte-identical (no embedded clock)."""
        link = db_session.scalar(
            select(EventAttendee).where(EventAttendee.id == issued["link_id"])
        )
        first = issued["path"].read_bytes()
        again = reissue_certificate_pdf(link, issued["certificate"], output_path=issued["path"])
        assert again.read_bytes() == first


class TestLiveFallback:
    """Rows issued before snapshots existed have nothing to render from."""

    def test_missing_snapshot_falls_back_to_live_data_and_logs_it(
        self, db_session, issued, caplog
    ):
        certificate = issued["certificate"]
        certificate.event_snapshot = {}
        db_session.commit()
        link = db_session.scalar(
            select(EventAttendee).where(EventAttendee.id == issued["link_id"])
        )
        link.event.title = "Renamed After The Fact"
        db_session.commit()

        with caplog.at_level(logging.WARNING, logger="app.certificates"):
            path = reissue_certificate_pdf(link, certificate, output_path=issued["path"])

        assert "no usable issue-time snapshot" in caplog.text
        assert certificate.certificate_number in caplog.text
        # The fallback is explicit, not silent: it does use live data.
        assert "Renamed After The Fact" in pdf_text(path)

    @pytest.mark.parametrize("snapshot", [None, {}, {"event_title": "x"}, {"fields": {}}])
    def test_unusable_snapshots_are_rejected(self, snapshot):
        assert content_from_snapshot(snapshot) is None

    def test_snapshot_without_layout_borrows_the_current_layout(self, db_session, issued):
        """Older snapshots predate the stored layout; values still come from
        the snapshot, only the placement falls back."""
        snapshot = dict(certificate_snapshot(issued["certificate"].event_attendee))
        snapshot.pop("certificate_fields")
        content = content_from_snapshot(snapshot, fallback_layout={"attendee_name": {"x": 10}})
        assert content is not None
        assert content.source == "snapshot"
        assert content.layout == {"attendee_name": {"x": 10}}
        assert content.event_title == ORIGINAL_TITLE
