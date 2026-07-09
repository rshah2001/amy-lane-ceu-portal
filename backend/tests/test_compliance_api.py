"""End-to-end eligibility flow through the HTTP API: upload registration,
attendance, and post-test CSVs, then verify the compliance endpoint reports
eligibility and reasons, and that approval enforces eligibility."""
import pytest

from helpers_api import (
    compliance_rows_by_name,
    create_event,
    upload_standard_roster,
)


@pytest.fixture()
def event(client, admin):
    return create_event(client, admin.headers)


@pytest.fixture()
def rows(client, admin, event):
    upload_standard_roster(client, admin.headers, event["id"])
    return compliance_rows_by_name(client, admin.headers, event["id"])


class TestEligibility:
    def test_all_uploaded_people_appear(self, rows):
        assert set(rows) == {"Alice Nguyen", "Bob Ramos", "Cara Fields", "Dan Poe"}

    def test_fully_compliant_attendee_is_eligible(self, rows):
        alice = rows["Alice Nguyen"]
        assert alice["registered"] is True
        assert alice["attended"] is True
        assert alice["test_completed"] is True
        assert alice["test_score"] == 92.0
        assert alice["has_valid_email"] is True
        assert alice["eligible"] is True
        assert alice["eligibility_reasons"] == []
        assert alice["compliance_status"] == "eligible"
        assert alice["lifecycle_status"] == "eligible"

    def test_low_score_blocks_eligibility(self, rows):
        bob = rows["Bob Ramos"]
        assert bob["eligible"] is False
        assert "Post-test score below 80%" in bob["eligibility_reasons"]
        assert bob["compliance_status"] == "ineligible"

    def test_invalid_email_blocks_eligibility(self, rows):
        cara = rows["Cara Fields"]
        assert cara["eligible"] is False
        assert "Missing or invalid email" in cara["eligibility_reasons"]

    def test_absent_attendee_gets_attendance_and_test_reasons(self, rows):
        dan = rows["Dan Poe"]
        assert dan["eligible"] is False
        assert "Not found on attendance sheet" in dan["eligibility_reasons"]
        assert "Post-test not completed" in dan["eligibility_reasons"]

    def test_eligibility_filter(self, client, admin, event, rows):
        response = client.get(
            f"/api/events/{event['id']}/compliance",
            params={"eligibility": "eligible"},
            headers=admin.headers,
        )
        assert response.status_code == 200
        names = {row["full_name"] for row in response.json()}
        assert names == {"Alice Nguyen"}

        response = client.get(
            f"/api/events/{event['id']}/compliance",
            params={"eligibility": "ineligible"},
            headers=admin.headers,
        )
        names = {row["full_name"] for row in response.json()}
        assert names == {"Bob Ramos", "Cara Fields", "Dan Poe"}

    def test_event_summary_reflects_uploads(self, client, admin, event, rows):
        response = client.get(
            f"/api/events/{event['id']}/summary", headers=admin.headers
        )
        assert response.status_code == 200, response.text
        summary = response.json()
        assert summary["total_attendees"] == 4
        assert summary["registered"] == 4
        assert summary["attended"] == 3
        assert summary["test_passed"] == 2  # Alice 92, Cara 95
        assert summary["eligible"] == 1
        assert summary["compliance_rate"] == 25.0


class TestApproval:
    def test_admin_approves_eligible_attendee(self, client, admin, event, rows):
        alice_id = rows["Alice Nguyen"]["id"]
        response = client.post(
            f"/api/events/{event['id']}/compliance/approve",
            json={"event_attendee_ids": [alice_id], "approved": True},
            headers=admin.headers,
        )
        assert response.status_code == 200, response.text
        (row,) = response.json()
        assert row["approved"] is True
        assert row["compliance_status"] == "approved"
        assert row["lifecycle_status"] == "approved"

    def test_ineligible_attendee_cannot_be_approved(self, client, admin, event, rows):
        bob_id = rows["Bob Ramos"]["id"]
        response = client.post(
            f"/api/events/{event['id']}/compliance/approve",
            json={"event_attendee_ids": [bob_id], "approved": True},
            headers=admin.headers,
        )
        assert response.status_code == 409, response.text

    def test_unknown_attendee_id_returns_404(self, client, admin, event, rows):
        response = client.post(
            f"/api/events/{event['id']}/compliance/approve",
            json={"event_attendee_ids": [999999], "approved": True},
            headers=admin.headers,
        )
        assert response.status_code == 404, response.text

    def test_approval_can_be_revoked(self, client, admin, event, rows):
        alice_id = rows["Alice Nguyen"]["id"]
        client.post(
            f"/api/events/{event['id']}/compliance/approve",
            json={"event_attendee_ids": [alice_id], "approved": True},
            headers=admin.headers,
        )
        response = client.post(
            f"/api/events/{event['id']}/compliance/approve",
            json={"event_attendee_ids": [alice_id], "approved": False},
            headers=admin.headers,
        )
        assert response.status_code == 200, response.text
        (row,) = response.json()
        assert row["approved"] is False
        assert row["compliance_status"] == "eligible"


class TestComplianceScoping:
    def test_presenter_sees_compliance_only_for_assigned_event(
        self, client, admin, presenter, event, rows
    ):
        # Not assigned to this event: hidden entirely.
        response = client.get(
            f"/api/events/{event['id']}/compliance", headers=presenter.headers
        )
        assert response.status_code == 404, response.text

    def test_assigned_presenter_can_view_compliance(
        self, client, admin, presenter
    ):
        assigned = create_event(
            client, admin.headers, assigned_presenter_id=presenter.id
        )
        upload_standard_roster(client, admin.headers, assigned["id"])
        rows = compliance_rows_by_name(client, presenter.headers, assigned["id"])
        assert "Alice Nguyen" in rows
