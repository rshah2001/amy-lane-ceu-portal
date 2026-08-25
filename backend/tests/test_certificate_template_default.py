"""The certificate an attendee receives must be NMEDA's certificate.

The branded CAMS Lunch & Learn PDF ships with the code, but nothing applied it
to an event: ``create_event`` never set ``certificate_template_path`` and the
portal has no UI for uploading one, so it stayed NULL and every certificate
issued through the portal was rendered on the built-in generic design -- an
attendee was emailed a plain "Certificate of Completion" instead of the
accredited document. These tests pin the default and, just as importantly, that
the choice of template is recorded in the issue-time snapshot so a re-issue
reproduces the same document.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from pypdf import PdfReader
from sqlalchemy import select

from app.models.certificate import Certificate
from app.models.event_attendee import EventAttendee
from app.services import certificates as certificates_service
from app.services.certificates import certificate_snapshot, reissue_certificate_pdf
from helpers_api import compliance_rows_by_name, create_event, upload_standard_roster

# Wording that only exists in the branded template's artwork.
BRANDED_MARKER = "has completed the training on"
# What the built-in design prints as its heading.
BUILTIN_MARKER = "CERTIFICATE OF COMPLETION"


def pdf_text(source: bytes | Path) -> str:
    reader = PdfReader(io.BytesIO(source) if isinstance(source, bytes) else source)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def issue(client, headers, event_id: int, db_session) -> Certificate:
    """Take one attendee all the way to a generated certificate."""
    upload_standard_roster(client, headers, event_id)
    link_id = compliance_rows_by_name(client, headers, event_id)["Alice Nguyen"]["id"]
    approve = client.post(
        f"/api/events/{event_id}/compliance/approve",
        json={"event_attendee_ids": [link_id], "approved": True},
        headers=headers,
    )
    assert approve.status_code == 200, approve.text
    response = client.post(
        f"/api/events/{event_id}/certificates/{link_id}/generate", headers=headers
    )
    assert response.status_code == 200, response.text
    return db_session.scalar(select(Certificate).where(Certificate.id == response.json()["id"]))


@pytest.fixture()
def issued(client, admin, db_session):
    event = create_event(client, admin.headers, course_instructor="Monique McGivney")
    certificate = issue(client, admin.headers, event["id"], db_session)
    return {"event": event, "certificate": certificate, "path": Path(certificate.pdf_path)}


class TestBrandedDefault:
    def test_portal_created_event_issues_the_branded_certificate(self, issued):
        text = pdf_text(issued["path"])
        assert BRANDED_MARKER in text
        assert BUILTIN_MARKER not in text.upper()
        # The variable fields are still stamped onto it.
        assert "Alice Nguyen" in text
        assert "Monique McGivney" in text

    def test_event_row_is_not_pinned_to_a_machine_specific_path(self, db_session, issued):
        """The default is resolved at issue time, not written to the database.

        The bundled asset sits at a different absolute path on a developer's
        machine than on the server, so storing one would point the other
        environment at a file that does not exist.
        """
        event = db_session.scalar(
            select(EventAttendee).where(
                EventAttendee.id == issued["certificate"].event_attendee_id
            )
        ).event
        assert event.certificate_template_path is None

    def test_snapshot_records_the_template_actually_rendered_on(self, issued):
        """Otherwise the snapshot says "no template" and the re-issue comes
        back on the built-in design -- two documents, one certificate number."""
        recorded = issued["certificate"].event_snapshot["template_path"]
        assert recorded is not None
        assert Path(recorded).name == certificates_service.BUNDLED_TEMPLATE_PATH.name

    def test_reissue_reproduces_the_branded_document(self, db_session, issued):
        original = issued["path"].read_bytes()
        link = db_session.scalar(
            select(EventAttendee).where(
                EventAttendee.id == issued["certificate"].event_attendee_id
            )
        )
        again = reissue_certificate_pdf(link, issued["certificate"], output_path=issued["path"])
        assert again.read_bytes() == original
        assert BRANDED_MARKER in pdf_text(again)


class TestOverridesAndDegradation:
    def test_uploaded_template_still_wins(self, client, admin, db_session):
        event = create_event(client, admin.headers)
        response = client.post(
            f"/api/events/{event['id']}/certificates/template",
            headers=admin.headers,
            files={
                "file": (
                    "house-style.pdf",
                    certificates_service.BUNDLED_TEMPLATE_PATH.read_bytes(),
                    "application/pdf",
                )
            },
        )
        assert response.status_code == 200, response.text
        certificate = issue(client, admin.headers, event["id"], db_session)
        recorded = Path(certificate.event_snapshot["template_path"])
        assert recorded.name != certificates_service.BUNDLED_TEMPLATE_PATH.name
        assert f"templates/{event['id']}/" in str(recorded)

    def test_missing_bundled_asset_degrades_to_the_builtin_design(
        self, client, admin, db_session, monkeypatch
    ):
        """A build without the asset must still issue something, not raise."""
        monkeypatch.setattr(
            certificates_service, "BUNDLED_TEMPLATE_PATH", Path("/nonexistent/gone.pdf")
        )
        event = create_event(client, admin.headers)
        certificate = issue(client, admin.headers, event["id"], db_session)
        assert certificate.event_snapshot["template_path"] is None
        assert BUILTIN_MARKER in pdf_text(Path(certificate.pdf_path)).upper()

    def test_bundled_template_is_recovered_from_a_foreign_absolute_path(
        self, db_session, issued
    ):
        """A record written on another machine names the bundled template at a
        path that does not exist here. The file ships with the code, so the
        re-issue uses that copy rather than quietly changing design."""
        certificate = issued["certificate"]
        snapshot = dict(certificate.event_snapshot)
        snapshot["template_path"] = (
            f"/somewhere/else/{certificates_service.BUNDLED_TEMPLATE_PATH.name}"
        )
        certificate.event_snapshot = snapshot
        db_session.commit()
        link = db_session.scalar(
            select(EventAttendee).where(EventAttendee.id == certificate.event_attendee_id)
        )
        again = reissue_certificate_pdf(link, certificate, output_path=issued["path"])
        assert BRANDED_MARKER in pdf_text(again)


def test_snapshot_helper_resolves_the_default(db_session, issued):
    """certificate_snapshot is the single place the choice is recorded."""
    link = db_session.scalar(
        select(EventAttendee).where(
            EventAttendee.id == issued["certificate"].event_attendee_id
        )
    )
    assert Path(certificate_snapshot(link)["template_path"]).is_file()
