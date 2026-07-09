"""Plain helper functions shared by the API test modules."""
from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook

DEFAULT_EVENT = {
    "title": "Adaptive Vehicle Safety CEU",
    "event_date": "2026-06-15",
    "ceu_hours": 2.0,
    "location": "Orlando, FL",
    "presenter_name": "Jordan Miles",
}


def create_event(client, headers, **overrides) -> dict:
    payload = {**DEFAULT_EVENT, **overrides}
    response = client.post("/api/events", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def upload_document(client, headers, event_id, file_type, filename, content, content_type):
    if isinstance(content, str):
        content = content.encode()
    return client.post(
        f"/api/events/{event_id}/uploads/{file_type}",
        headers=headers,
        files={"file": (filename, content, content_type)},
    )


def upload_csv(client, headers, event_id, file_type, csv_text, filename="rows.csv"):
    return upload_document(client, headers, event_id, file_type, filename, csv_text, "text/csv")


def xlsx_bytes(rows: list[list]) -> bytes:
    """Real XLSX bytes (valid ZIP container) so magic-byte checks pass."""
    workbook = Workbook()
    worksheet = workbook.active
    for row in rows:
        worksheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


# --- Standard roster used by the compliance / certificate flow tests -------
#
# Alice: attended, scored 92, valid email      -> eligible
# Bob:   attended, scored 70, valid email      -> ineligible (score)
# Cara:  attended, scored 95, malformed email  -> ineligible (email)
# Dan:   registered only                       -> ineligible (attendance, test)

REGISTRATION_CSV = (
    "Full Name,Email,Company\n"
    "Alice Nguyen,alice.nguyen@example.com,Mobility Works\n"
    "Bob Ramos,bob.ramos@example.com,Mobility Works\n"
    "Cara Fields,cara-at-example.com,Independent\n"
    "Dan Poe,dan.poe@example.com,Independent\n"
)
ATTENDANCE_CSV = (
    "Name,Email\n"
    "Alice Nguyen,alice.nguyen@example.com\n"
    "Bob Ramos,bob.ramos@example.com\n"
    "Cara Fields,cara-at-example.com\n"
)
POST_TEST_CSV = (
    "Participant Name,Email,Score\n"
    "Alice Nguyen,alice.nguyen@example.com,92\n"
    "Bob Ramos,bob.ramos@example.com,70\n"
    "Cara Fields,cara-at-example.com,95\n"
)


def upload_standard_roster(client, headers, event_id) -> None:
    for file_type, csv_text in (
        ("registration", REGISTRATION_CSV),
        ("attendance", ATTENDANCE_CSV),
        ("post_test", POST_TEST_CSV),
    ):
        response = upload_csv(client, headers, event_id, file_type, csv_text)
        assert response.status_code == 201, response.text


def compliance_rows_by_name(client, headers, event_id) -> dict[str, dict]:
    response = client.get(f"/api/events/{event_id}/compliance", headers=headers)
    assert response.status_code == 200, response.text
    return {row["full_name"]: row for row in response.json()}
