"""Upload endpoint tests: validation, role restrictions, and row ingestion.

Uploaded test files carry real, well-formed content matching their extension
(actual CSV text, actual XLSX zip bytes) so magic-byte content validation
passes for the positive cases.
"""
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.pagesizes import letter

from app.models.uploaded_file import UploadedFile
from helpers_api import (
    compliance_rows_by_name,
    create_event,
    upload_csv,
    upload_document,
    xlsx_bytes,
)

SIMPLE_CSV = (
    "Full Name,Email,Company\n"
    "Alice Nguyen,alice.nguyen@example.com,Mobility Works\n"
    "Bob Ramos,bob.ramos@example.com,Mobility Works\n"
)

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def pdf_bytes(lines: list[str]) -> bytes:
    """A real PDF with a text layer, one comma-separated table line per row."""
    output = BytesIO()
    canvas = Canvas(output, pagesize=letter)
    canvas.setFont("Helvetica", 12)
    y = 720
    for line in lines:
        canvas.drawString(72, y, line)
        y -= 20
    canvas.save()
    return output.getvalue()


def docx_bytes(rows: list[list[str]]) -> bytes:
    """A minimal real DOCX (valid ZIP + word/document.xml) holding one table."""

    def cell(text: str) -> str:
        return f"<w:tc><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>"

    table_rows = "".join(
        "<w:tr>" + "".join(cell(value) for value in row) + "</w:tr>" for row in rows
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:tbl>{table_rows}</w:tbl></w:body></w:document>"
    )
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/></Relationships>',
        )
        archive.writestr("word/document.xml", document)
    return output.getvalue()


@pytest.fixture()
def event(client, admin, presenter):
    """An event assigned to `presenter` so both roles can reach it."""
    return create_event(client, admin.headers, assigned_presenter_id=presenter.id)


class TestUploadValidation:
    def test_invalid_file_type_returns_400(self, client, admin, event):
        response = upload_csv(
            client, admin.headers, event["id"], "bogus_type", SIMPLE_CSV
        )
        assert response.status_code == 400, response.text

    def test_disallowed_extension_returns_400(self, client, admin, event):
        response = upload_document(
            client,
            admin.headers,
            event["id"],
            "registration",
            "roster.txt",
            SIMPLE_CSV,
            "text/plain",
        )
        assert response.status_code == 400, response.text

    def test_oversize_upload_returns_413(self, client, admin, event):
        # A real, parseable CSV that just exceeds the 15 MB cap.
        row = "Padding Person,padding.person@example.com,Big Co\n"
        oversize_csv = "Full Name,Email,Company\n" + row * (16 * 1024 * 1024 // len(row))
        assert len(oversize_csv) > 15 * 1024 * 1024
        response = upload_csv(
            client, admin.headers, event["id"], "registration", oversize_csv
        )
        assert response.status_code == 413, response.text

    def test_content_not_matching_extension_returns_400(self, client, admin, event):
        # Plain CSV text dressed up with an .xlsx name: magic bytes won't match.
        response = upload_document(
            client,
            admin.headers,
            event["id"],
            "registration",
            "roster.xlsx",
            SIMPLE_CSV,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        assert response.status_code == 400, response.text


class TestUploadRoleScoping:
    def test_presenter_cannot_upload_registration(self, client, presenter, event):
        response = upload_csv(
            client, presenter.headers, event["id"], "registration", SIMPLE_CSV
        )
        assert response.status_code == 403, response.text

    def test_presenter_can_upload_attendance(self, client, presenter, event):
        response = upload_csv(
            client, presenter.headers, event["id"], "attendance", SIMPLE_CSV
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["file_type"] == "attendance"
        assert body["row_count"] == 2

    def test_presenter_cannot_upload_to_unassigned_event(
        self, client, admin, other_presenter
    ):
        unassigned = create_event(client, admin.headers, title="Not Assigned")
        response = upload_csv(
            client,
            other_presenter.headers,
            unassigned["id"],
            "attendance",
            SIMPLE_CSV,
        )
        assert response.status_code == 404, response.text


class TestUploadDownload:
    def upload_and_get_id(self, client, headers, event_id, filename="roster.csv"):
        response = upload_csv(
            client, headers, event_id, "attendance", SIMPLE_CSV, filename=filename
        )
        assert response.status_code == 201, response.text
        return response.json()["id"]

    def test_download_returns_original_file(self, client, admin, event):
        upload_id = self.upload_and_get_id(client, admin.headers, event["id"])
        response = client.get(
            f"/api/events/{event['id']}/uploads/{upload_id}/download",
            headers=admin.headers,
        )
        assert response.status_code == 200, response.text
        assert response.content == SIMPLE_CSV.encode()
        assert response.headers["content-type"].startswith("text/csv")
        disposition = response.headers["content-disposition"]
        assert 'filename="roster.csv"' in disposition
        assert "filename*=UTF-8''roster.csv" in disposition

    def test_download_unknown_upload_returns_404(self, client, admin, event):
        response = client.get(
            f"/api/events/{event['id']}/uploads/999999/download",
            headers=admin.headers,
        )
        assert response.status_code == 404, response.text

    def test_download_upload_of_other_event_returns_404(self, client, admin, event):
        other = create_event(client, admin.headers, title="Other Event")
        upload_id = self.upload_and_get_id(client, admin.headers, other["id"])
        # Right upload id, wrong event: must not leak across events.
        response = client.get(
            f"/api/events/{event['id']}/uploads/{upload_id}/download",
            headers=admin.headers,
        )
        assert response.status_code == 404, response.text

    def test_download_missing_file_on_disk_returns_404(
        self, client, admin, event, db_session
    ):
        upload_id = self.upload_and_get_id(client, admin.headers, event["id"])
        stored = db_session.get(UploadedFile, upload_id)
        Path(stored.storage_path).unlink()
        response = client.get(
            f"/api/events/{event['id']}/uploads/{upload_id}/download",
            headers=admin.headers,
        )
        assert response.status_code == 404, response.text

    def test_download_role_scoping(
        self, client, admin, presenter, other_presenter, event
    ):
        upload_id = self.upload_and_get_id(client, admin.headers, event["id"])
        # The assigned presenter can download files for their event...
        response = client.get(
            f"/api/events/{event['id']}/uploads/{upload_id}/download",
            headers=presenter.headers,
        )
        assert response.status_code == 200, response.text
        # ...but an unassigned presenter cannot even see the event.
        response = client.get(
            f"/api/events/{event['id']}/uploads/{upload_id}/download",
            headers=other_presenter.headers,
        )
        assert response.status_code == 404, response.text

    def test_download_requires_authentication(self, client, admin, event):
        upload_id = self.upload_and_get_id(client, admin.headers, event["id"])
        response = client.get(
            f"/api/events/{event['id']}/uploads/{upload_id}/download"
        )
        assert response.status_code in (401, 403), response.text


class TestUploadIngestion:
    def test_csv_upload_creates_attendees(self, client, admin, event):
        response = upload_csv(
            client, admin.headers, event["id"], "registration", SIMPLE_CSV
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["row_count"] == 2
        assert body["parse_status"] == "processed"
        assert body["parse_errors"] == []

        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert set(rows) == {"Alice Nguyen", "Bob Ramos"}
        assert rows["Alice Nguyen"]["registered"] is True
        assert rows["Alice Nguyen"]["attended"] is False

    def test_xlsx_upload_creates_attendees(self, client, admin, event):
        content = xlsx_bytes(
            [
                ["Full Name", "Email", "Company"],
                ["Iris Stone", "iris.stone@example.com", "Summit Dealer"],
            ]
        )
        response = upload_document(
            client,
            admin.headers,
            event["id"],
            "attendance",
            "signin.xlsx",
            content,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        assert response.status_code == 201, response.text
        assert response.json()["row_count"] == 1

        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows["Iris Stone"]["attended"] is True

    def test_upload_moves_event_to_review(self, client, admin, event):
        assert event["status"] == "draft"
        upload_csv(client, admin.headers, event["id"], "registration", SIMPLE_CSV)
        refreshed = client.get(f"/api/events/{event['id']}", headers=admin.headers)
        assert refreshed.json()["status"] == "review"

    def test_pdf_upload_creates_attendees(self, client, admin, event):
        content = pdf_bytes(
            ["Full Name,Email", "Paula Marsh,paula.marsh@example.com"]
        )
        response = upload_document(
            client,
            admin.headers,
            event["id"],
            "attendance",
            "signin.pdf",
            content,
            "application/pdf",
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["row_count"] == 1
        # PDF extraction always carries the best-effort warning.
        assert body["parse_status"] == "processed_with_errors"
        assert any("best-effort" in error["message"] for error in body["parse_errors"])

        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows["Paula Marsh"]["attended"] is True

    def test_docx_upload_creates_attendees(self, client, admin, event):
        content = docx_bytes(
            [
                ["Full Name", "Email"],
                ["Gina Torres", "gina.torres@example.com"],
            ]
        )
        response = upload_document(
            client,
            admin.headers,
            event["id"],
            "attendance",
            "signin.docx",
            content,
            DOCX_MEDIA_TYPE,
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["row_count"] == 1
        assert body["parse_status"] == "processed"

        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows["Gina Torres"]["attended"] is True

    def test_pdf_content_check_rejects_fakes(self, client, admin, event):
        response = upload_document(
            client,
            admin.headers,
            event["id"],
            "attendance",
            "signin.pdf",
            SIMPLE_CSV,
            "application/pdf",
        )
        assert response.status_code == 400, response.text

    def test_empty_docx_returns_400(self, client, admin, event):
        # A valid ZIP that has no rows to extract -> ValueError -> 400.
        response = upload_document(
            client,
            admin.headers,
            event["id"],
            "attendance",
            "signin.docx",
            docx_bytes([]),
            DOCX_MEDIA_TYPE,
        )
        assert response.status_code == 400, response.text

    def test_list_uploads_returns_uploaded_files(self, client, admin, presenter, event):
        upload_csv(client, admin.headers, event["id"], "registration", SIMPLE_CSV)
        upload_csv(client, presenter.headers, event["id"], "attendance", SIMPLE_CSV)

        response = client.get(f"/api/events/{event['id']}/uploads", headers=admin.headers)
        assert response.status_code == 200, response.text
        file_types = {upload["file_type"] for upload in response.json()}
        assert file_types == {"registration", "attendance"}

        # The assigned presenter can also list uploads for their event.
        response = client.get(
            f"/api/events/{event['id']}/uploads", headers=presenter.headers
        )
        assert response.status_code == 200
        assert len(response.json()) == 2


class TestFileImportKeepsWebSubmissions:
    def test_web_test_result_survives_post_test_file_upload(self, client, admin):
        event = create_event(
            client,
            admin.headers,
            test_mode="internal",
            test_questions=[
                {"id": "q1", "prompt": "2 + 2?", "choices": ["3", "4"], "correct_index": 1}
            ],
        )
        response = client.post(
            f"/api/public/tests/{event['test_token']}",
            json={"full_name": "Sam Lee", "email": "sam.lee@example.com", "answers": {"q1": 1}},
        )
        assert response.status_code == 200, response.text
        assert response.json()["passed"] is True

        upload_csv(
            client,
            admin.headers,
            event["id"],
            "post_test",
            "Full Name,Email,Score\nPat Doe,pat.doe@example.com,85\n",
        )

        compliance = client.get(
            f"/api/events/{event['id']}/compliance", headers=admin.headers
        ).json()
        by_email = {row["email"]: row for row in compliance}
        web = by_email["sam.lee@example.com"]
        assert web["test_completed"] is True, "web test result was wiped by the file import"
        assert web["test_score"] == 100.0
        assert by_email["pat.doe@example.com"]["test_completed"] is True

    def test_qr_checkin_survives_attendance_file_upload(self, client, admin):
        event = create_event(client, admin.headers)
        # The checkin token is generated at event creation; fetch the event to get it.
        detail = client.get(f"/api/events/{event['id']}", headers=admin.headers).json()
        token = detail.get("checkin_token")
        assert token, "event has no checkin token"
        response = client.post(
            f"/api/public/checkin/{token}",
            json={"full_name": "Sam Lee", "email": "sam.lee@example.com"},
        )
        assert response.status_code == 200, response.text

        upload_csv(
            client,
            admin.headers,
            event["id"],
            "attendance",
            "Full Name,Email\nPat Doe,pat.doe@example.com\n",
        )

        compliance = client.get(
            f"/api/events/{event['id']}/compliance", headers=admin.headers
        ).json()
        by_email = {row["email"]: row for row in compliance}
        assert by_email["sam.lee@example.com"]["attended"] is True, (
            "QR check-in was wiped by the sign-in sheet import"
        )
        assert by_email["pat.doe@example.com"]["attended"] is True
