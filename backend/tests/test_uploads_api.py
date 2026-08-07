"""Upload endpoint tests: validation, role restrictions, and row ingestion.

Uploaded test files carry real, well-formed content matching their extension
(actual CSV text, actual XLSX zip bytes) so magic-byte content validation
passes for the positive cases.
"""
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import Workbook
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


TEAMS_STYLE_CSV = (
    "1. Summary,,,,,\n"
    "Meeting title,CEU Training,,,,\n"
    "Attended participants,2,,,,\n"
    ",,,,,\n"
    "2. Participants,,,,,\n"
    "Name,Join time,Leave time,Duration,Email,Role\n"
    "Alice Nguyen,6/15/26 10:00,6/15/26 11:00,1h,alice.nguyen@example.com,Attendee\n"
    "Bob Ramos,6/15/26 10:05,6/15/26 11:00,55m,bob.ramos@example.com,Attendee\n"
)


class TestSheetFormatHint:
    """The optional `sheet_format` form field steers/validates parsing."""

    def test_virtual_hint_reads_teams_csv_with_summary_rows(self, client, admin, event):
        response = upload_csv(
            client,
            admin.headers,
            event["id"],
            "attendance",
            TEAMS_STYLE_CSV,
            filename="teams-attendance.csv",
            sheet_format="virtual_meeting",
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["row_count"] == 2
        assert body["parse_errors"] == []
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert set(rows) == {"Alice Nguyen", "Bob Ramos"}
        assert rows["Alice Nguyen"]["attended"] is True

    def test_same_teams_csv_without_hint_reports_no_names(self, client, admin, event):
        # Without the hint the summary line is taken as the header, so no names
        # are found. An import with nothing in it is refused outright: it would
        # otherwise reset the event's attendance and put nothing back.
        response = upload_csv(
            client,
            admin.headers,
            event["id"],
            "attendance",
            TEAMS_STYLE_CSV,
            filename="teams-attendance.csv",
        )
        assert response.status_code == 400, response.text
        assert "No attendee names could be read" in response.json()["detail"]

    def test_virtual_hint_steers_xlsx_header_detection(self, client, admin, event):
        # The summary line "Meeting name" would win default header detection
        # (it names a "name"); the virtual hint demands an email/join-time too.
        content = xlsx_bytes(
            [
                ["Meeting name", "Weekly CEU"],
                ["Name", "Join time", "Leave time", "Duration", "Email", "Role"],
                ["Iris Stone", "10:00", "11:00", "60", "iris.stone@example.com", "Attendee"],
            ]
        )
        response = upload_document(
            client,
            admin.headers,
            event["id"],
            "attendance",
            "teams.xlsx",
            content,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            sheet_format="virtual_meeting",
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["row_count"] == 1
        assert body["parse_errors"] == []
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows["Iris Stone"]["attended"] is True

    def test_mismatched_hint_warns_but_still_parses(self, client, admin, event):
        # "Word document" hint on a CSV: warn clearly, then trust the file.
        response = upload_csv(
            client,
            admin.headers,
            event["id"],
            "attendance",
            SIMPLE_CSV,
            sheet_format="word",
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["row_count"] == 2
        assert body["parse_status"] == "processed_with_errors"
        assert any("does not match" in error["message"] for error in body["parse_errors"])
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert set(rows) == {"Alice Nguyen", "Bob Ramos"}

    def test_matching_hint_keeps_default_parsing(self, client, admin, event):
        response = upload_csv(
            client,
            admin.headers,
            event["id"],
            "attendance",
            SIMPLE_CSV,
            sheet_format="spreadsheet",
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["row_count"] == 2
        assert body["parse_errors"] == []

    def test_other_hint_is_a_noop(self, client, admin, event):
        response = upload_csv(
            client,
            admin.headers,
            event["id"],
            "attendance",
            SIMPLE_CSV,
            sheet_format="other",
        )
        assert response.status_code == 201, response.text
        assert response.json()["parse_errors"] == []

    def test_invalid_sheet_format_returns_400(self, client, admin, event):
        response = upload_csv(
            client,
            admin.headers,
            event["id"],
            "attendance",
            SIMPLE_CSV,
            sheet_format="carrier_pigeon",
        )
        assert response.status_code == 400, response.text


class TestZeroNamesFeedback:
    """A file with no attendees in it is refused, not reported as processed.

    The message is the same one commit 6b6d062 introduced; it now arrives as a
    400 because an empty import is also a destructive one (see
    test_import_integrity.py).
    """

    def test_header_only_csv_reports_no_names(self, client, admin, event):
        response = upload_csv(
            client, admin.headers, event["id"], "attendance", "Full Name,Email\n"
        )
        assert response.status_code == 400, response.text
        assert "No attendee names could be read" in response.json()["detail"]

    def test_csv_without_name_column_reports_no_names(self, client, admin, event):
        response = upload_csv(
            client,
            admin.headers,
            event["id"],
            "attendance",
            "Widget,Count\nBolt,2\nNut,7\n",
        )
        assert response.status_code == 400, response.text
        assert "No attendee names could be read" in response.json()["detail"]

    def test_upload_with_names_has_no_zero_names_message(self, client, admin, event):
        response = upload_csv(
            client, admin.headers, event["id"], "attendance", SIMPLE_CSV
        )
        assert response.status_code == 201, response.text
        assert response.json()["parse_errors"] == []


def problems(body: dict) -> list[dict]:
    """Parse entries that are actual problems, dropping "how I read it" notices."""
    return [error for error in body["parse_errors"] if error.get("level") != "info"]


class TestPostTestScoreFormats:
    """Presenters upload scores as percentages, fractions, or out of 10.

    The unit is decided once for the whole column (see test_import_integrity),
    so a column that is plainly percentages reads every bare number as one.
    """

    def test_csv_score_formats_normalize_to_percent(self, client, admin, event):
        response = upload_csv(
            client,
            admin.headers,
            event["id"],
            "post_test",
            "Full Name,Email,Score\n"
            "Percy Cent,percy.cent@example.com,85%\n"
            "Fran Action,fran.action@example.com,8/10\n"
            "Tenny Scale,tenny.scale@example.com,90\n"
            "Plain Percent,plain.percent@example.com,72\n",
        )
        assert response.status_code == 201, response.text
        assert problems(response.json()) == []
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows["Percy Cent"]["test_score"] == 85.0
        assert rows["Fran Action"]["test_score"] == 80.0
        assert rows["Tenny Scale"]["test_score"] == 90.0
        assert rows["Plain Percent"]["test_score"] == 72.0

    def test_out_of_ten_column_reads_out_of_ten(self, client, admin, event):
        # Explicit "x/10" in every row: no inference needed, and no cell is
        # read on a unit it did not state.
        response = upload_csv(
            client,
            admin.headers,
            event["id"],
            "post_test",
            "Full Name,Email,Score\n"
            "Fran Action,fran.action@example.com,8/10\n"
            "Nina Nine,nina.nine@example.com,9/10\n",
        )
        assert response.status_code == 201, response.text
        assert problems(response.json()) == []
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows["Fran Action"]["test_score"] == 80.0
        assert rows["Nina Nine"]["test_score"] == 90.0

    def test_xlsx_percent_formatted_cell_reads_as_percentage(self, client, admin, event):
        # Excel stores a percent-formatted 90% as the number 0.9.
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(["Name", "Email", "Score"])
        worksheet.append(["Exel Percent", "exel.percent@example.com", 0.9])
        worksheet["C2"].number_format = "0%"
        output = BytesIO()
        workbook.save(output)
        response = upload_document(
            client,
            admin.headers,
            event["id"],
            "post_test",
            "results.xlsx",
            output.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        assert response.status_code == 201, response.text
        assert problems(response.json()) == []
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows["Exel Percent"]["test_score"] == 90.0

    def test_unreadable_score_reports_row_error(self, client, admin, event):
        # One readable row keeps the import alive; the unreadable one is
        # reported against its own row and simply not imported.
        response = upload_csv(
            client,
            admin.headers,
            event["id"],
            "post_test",
            "Full Name,Email,Score\n"
            "Good Score,good.score@example.com,85%\n"
            "Bad Score,bad.score@example.com,eight\n",
        )
        assert response.status_code == 201, response.text
        errors = problems(response.json())
        assert len(errors) == 1 and "Invalid score" in errors[0]["message"]
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows["Good Score"]["test_score"] == 85.0
        # A row that cannot be imported is not half-imported either: scores are
        # read before anything is written, so the bad row adds no roster entry.
        assert "Bad Score" not in rows


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
