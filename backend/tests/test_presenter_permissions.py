"""Locks in the presenter (instructor) permission model, as confirmed by the
client.

Presenters may ONLY:
- see events an admin assigned to them (list, detail, summary, dashboard)
- upload the attendance / sign-in sheet to their assigned events

Presenters must NOT be able to:
- see or access compliance review
- edit or delete events (even their own)
- approve / generate / send certificates or reach any certificate-center action
- see or manage users
- see or change settings (including the survey template)
- see other presenters'/admins' events, their documents, or survey responses

Admin-only endpoints answer 403; resources hidden by event-visibility scoping
answer 404 (the event does not exist as far as the presenter can tell).
"""
import pytest

from helpers_api import (
    ATTENDANCE_CSV,
    REGISTRATION_CSV,
    create_event,
    upload_csv,
    upload_standard_roster,
)


@pytest.fixture()
def assigned_event(client, admin, presenter) -> dict:
    """An event the presenter under test is assigned to."""
    return create_event(
        client, admin.headers, title="My Assigned CEU", assigned_presenter_id=presenter.id
    )


@pytest.fixture()
def foreign_event(client, admin, other_presenter) -> dict:
    """Another presenter's event — must be invisible to `presenter`."""
    return create_event(
        client,
        admin.headers,
        title="Someone Else's CEU",
        assigned_presenter_id=other_presenter.id,
    )


class TestEventVisibility:
    def test_listing_shows_only_assigned_events(
        self, client, admin, presenter, assigned_event, foreign_event
    ):
        unassigned = create_event(client, admin.headers, title="Admin-Only CEU")
        response = client.get("/api/events", headers=presenter.headers)
        assert response.status_code == 200, response.text
        ids = {event["id"] for event in response.json()}
        assert ids == {assigned_event["id"]}
        assert foreign_event["id"] not in ids
        assert unassigned["id"] not in ids

    def test_can_fetch_assigned_event(self, client, presenter, assigned_event):
        response = client.get(f"/api/events/{assigned_event['id']}", headers=presenter.headers)
        assert response.status_code == 200, response.text
        assert response.json()["assigned_presenter_id"] == presenter.id

    def test_foreign_event_is_hidden(self, client, presenter, foreign_event):
        response = client.get(f"/api/events/{foreign_event['id']}", headers=presenter.headers)
        assert response.status_code == 404, response.text

    def test_unassigned_event_is_hidden(self, client, admin, presenter):
        unassigned = create_event(client, admin.headers, title="Nobody Assigned")
        response = client.get(f"/api/events/{unassigned['id']}", headers=presenter.headers)
        assert response.status_code == 404, response.text

    def test_summary_follows_event_visibility(
        self, client, presenter, assigned_event, foreign_event
    ):
        ok = client.get(
            f"/api/events/{assigned_event['id']}/summary", headers=presenter.headers
        )
        assert ok.status_code == 200, ok.text
        hidden = client.get(
            f"/api/events/{foreign_event['id']}/summary", headers=presenter.headers
        )
        assert hidden.status_code == 404, hidden.text

    def test_dashboard_counts_only_assigned_events(
        self, client, admin, presenter, assigned_event, foreign_event
    ):
        create_event(client, admin.headers, title="Extra Unassigned")
        response = client.get("/api/dashboard", headers=presenter.headers)
        assert response.status_code == 200, response.text
        assert response.json()["total_events"] == 1

    def test_dashboard_charts_only_include_assigned_events(
        self, client, presenter, assigned_event, foreign_event
    ):
        response = client.get("/api/dashboard/charts", headers=presenter.headers)
        assert response.status_code == 200, response.text
        chart_ids = {point["event_id"] for point in response.json()["events_compliance"]}
        assert chart_ids == {assigned_event["id"]}


class TestEventMutationForbidden:
    def test_cannot_create_event(self, client, presenter):
        response = client.post(
            "/api/events",
            json={"title": "Rogue Event", "event_date": "2026-08-01"},
            headers=presenter.headers,
        )
        assert response.status_code == 403, response.text

    def test_cannot_edit_own_assigned_event(self, client, presenter, assigned_event):
        response = client.put(
            f"/api/events/{assigned_event['id']}",
            json={"title": "Hijacked"},
            headers=presenter.headers,
        )
        assert response.status_code == 403, response.text

    def test_cannot_edit_foreign_event(self, client, presenter, foreign_event):
        response = client.put(
            f"/api/events/{foreign_event['id']}",
            json={"title": "Hijacked"},
            headers=presenter.headers,
        )
        assert response.status_code == 403, response.text

    def test_cannot_delete_own_assigned_event(self, client, presenter, assigned_event):
        response = client.delete(
            f"/api/events/{assigned_event['id']}", headers=presenter.headers
        )
        assert response.status_code == 403, response.text


class TestUploads:
    def test_can_upload_attendance_to_assigned_event(
        self, client, presenter, assigned_event
    ):
        response = upload_csv(
            client, presenter.headers, assigned_event["id"], "attendance", ATTENDANCE_CSV
        )
        assert response.status_code == 201, response.text
        assert response.json()["file_type"] == "attendance"

    def test_cannot_upload_to_foreign_event(self, client, presenter, foreign_event):
        response = upload_csv(
            client, presenter.headers, foreign_event["id"], "attendance", ATTENDANCE_CSV
        )
        assert response.status_code == 404, response.text

    @pytest.mark.parametrize("file_type", ["registration", "post_test", "survey"])
    def test_can_only_upload_attendance_file_type(
        self, client, presenter, assigned_event, file_type
    ):
        response = upload_csv(
            client, presenter.headers, assigned_event["id"], file_type, REGISTRATION_CSV
        )
        assert response.status_code == 403, response.text

    def test_can_list_own_event_uploads(self, client, presenter, assigned_event):
        upload_csv(client, presenter.headers, assigned_event["id"], "attendance", ATTENDANCE_CSV)
        response = client.get(
            f"/api/events/{assigned_event['id']}/uploads", headers=presenter.headers
        )
        assert response.status_code == 200, response.text
        assert len(response.json()) == 1

    def test_cannot_list_foreign_event_uploads(
        self, client, admin, presenter, foreign_event
    ):
        upload_csv(client, admin.headers, foreign_event["id"], "attendance", ATTENDANCE_CSV)
        response = client.get(
            f"/api/events/{foreign_event['id']}/uploads", headers=presenter.headers
        )
        assert response.status_code == 404, response.text

    def test_cannot_download_foreign_event_document(
        self, client, admin, presenter, foreign_event
    ):
        uploaded = upload_csv(
            client, admin.headers, foreign_event["id"], "attendance", ATTENDANCE_CSV
        )
        assert uploaded.status_code == 201, uploaded.text
        response = client.get(
            f"/api/events/{foreign_event['id']}/uploads/{uploaded.json()['id']}/download",
            headers=presenter.headers,
        )
        assert response.status_code == 404, response.text


class TestComplianceLockdown:
    def test_cannot_view_compliance_for_assigned_event(
        self, client, admin, presenter, assigned_event
    ):
        upload_standard_roster(client, admin.headers, assigned_event["id"])
        response = client.get(
            f"/api/events/{assigned_event['id']}/compliance", headers=presenter.headers
        )
        assert response.status_code == 403, response.text

    def test_cannot_view_compliance_for_foreign_event(
        self, client, presenter, foreign_event
    ):
        response = client.get(
            f"/api/events/{foreign_event['id']}/compliance", headers=presenter.headers
        )
        assert response.status_code == 403, response.text

    def test_cannot_approve_attendees(self, client, presenter, assigned_event):
        response = client.post(
            f"/api/events/{assigned_event['id']}/compliance/approve",
            json={"event_attendee_ids": [1], "approved": True},
            headers=presenter.headers,
        )
        assert response.status_code == 403, response.text

    def test_admin_still_reviews_compliance(self, client, admin, assigned_event):
        upload_standard_roster(client, admin.headers, assigned_event["id"])
        response = client.get(
            f"/api/events/{assigned_event['id']}/compliance", headers=admin.headers
        )
        assert response.status_code == 200, response.text
        assert len(response.json()) > 0


class TestCertificateLockdown:
    @pytest.mark.parametrize(
        "method,path,body",
        [
            ("GET", "certificates", None),
            ("GET", "certificates/1/preview", None),
            ("POST", "certificates/1/generate", None),
            ("POST", "certificates/1/send", None),
            (
                "POST",
                "certificates/issue",
                {"full_name": "Walk In", "email": "walkin@example.com", "send_email": False},
            ),
            ("POST", "certificates/approve-all", None),
            ("POST", "certificates/generate-all", None),
            ("POST", "certificates/send-all", None),
            ("GET", "certificates/1/download", None),
        ],
    )
    def test_certificate_actions_forbidden_even_on_own_event(
        self, client, presenter, assigned_event, method, path, body
    ):
        url = f"/api/events/{assigned_event['id']}/{path}"
        if method == "GET":
            response = client.get(url, headers=presenter.headers)
        else:
            response = client.post(url, json=body, headers=presenter.headers)
        assert response.status_code == 403, f"{method} {url}: {response.text}"

    def test_cannot_upload_certificate_template(self, client, presenter, assigned_event):
        response = client.post(
            f"/api/events/{assigned_event['id']}/certificates/template",
            headers=presenter.headers,
            files={"file": ("template.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
        assert response.status_code == 403, response.text


class TestUserManagementLockdown:
    def test_cannot_list_users(self, client, presenter):
        assert client.get("/api/users", headers=presenter.headers).status_code == 403

    def test_cannot_create_users(self, client, presenter):
        response = client.post(
            "/api/users",
            json={
                "email": "sneaky@example.com",
                "full_name": "Sneaky",
                "role": "admin",
                "password": "Password123!",
            },
            headers=presenter.headers,
        )
        assert response.status_code == 403, response.text

    def test_cannot_update_users(self, client, presenter, admin):
        response = client.patch(
            f"/api/users/{admin.id}",
            json={"is_active": False},
            headers=presenter.headers,
        )
        assert response.status_code == 403, response.text


class TestSettingsLockdown:
    def test_settings_reveal_no_configuration_to_presenters(self, client, presenter):
        response = client.get("/api/settings", headers=presenter.headers)
        assert response.status_code == 200, response.text
        body = response.json()
        # Only their own account: no ops / environment configuration leaks.
        assert body["current_user"]["email"] == presenter.email
        assert set(body) == {"current_user"}

    def test_settings_still_include_configuration_for_admins(self, client, admin):
        body = client.get("/api/settings", headers=admin.headers).json()
        assert {"organization", "retention_years", "email_delivery_mode", "smtp_configured", "environment"} <= set(body)

    def test_cannot_read_survey_template(self, client, presenter):
        response = client.get("/api/settings/survey-template", headers=presenter.headers)
        assert response.status_code == 403, response.text

    def test_cannot_edit_survey_template(self, client, presenter):
        response = client.put(
            "/api/settings/survey-template",
            json={"questions": [{"id": "s1", "label": "Hacked?", "type": "text"}]},
            headers=presenter.headers,
        )
        assert response.status_code == 403, response.text


class TestSurveyDataLockdown:
    @pytest.mark.parametrize(
        "path",
        ["/api/survey-responses", "/api/survey-responses.csv", "/api/survey-insights"],
    )
    def test_survey_response_data_is_admin_only(self, client, presenter, path):
        response = client.get(path, headers=presenter.headers)
        assert response.status_code == 403, response.text

    def test_survey_qr_only_for_assigned_events(
        self, client, presenter, assigned_event, foreign_event
    ):
        ok = client.get(
            f"/api/events/{assigned_event['id']}/survey-qr", headers=presenter.headers
        )
        assert ok.status_code == 200, ok.text
        hidden = client.get(
            f"/api/events/{foreign_event['id']}/survey-qr", headers=presenter.headers
        )
        assert hidden.status_code == 404, hidden.text


class TestReportingAndSystemLockdown:
    @pytest.mark.parametrize(
        "path",
        [
            "/api/audit-logs",
            "/api/reports/columns",
            "/api/reports/annual/2026",
            "/api/notifications",
            "/api/notifications/unread-count",
            "/api/system/health",
        ],
    )
    def test_admin_surfaces_are_forbidden(self, client, presenter, path):
        response = client.get(path, headers=presenter.headers)
        assert response.status_code == 403, response.text

    def test_notification_writes_are_forbidden(self, client, presenter):
        assert (
            client.post("/api/notifications/read-all", headers=presenter.headers).status_code
            == 403
        )
        assert (
            client.post("/api/notifications/1/read", headers=presenter.headers).status_code
            == 403
        )

    def test_attendee_search_is_scoped_to_assigned_events(
        self, client, admin, presenter, assigned_event, foreign_event
    ):
        upload_standard_roster(client, admin.headers, foreign_event["id"])
        response = client.get("/api/attendees/search?q=Alice", headers=presenter.headers)
        assert response.status_code == 200, response.text
        assert response.json() == []

        upload_standard_roster(client, admin.headers, assigned_event["id"])
        response = client.get("/api/attendees/search?q=Alice", headers=presenter.headers)
        assert response.status_code == 200, response.text
        assert {row["event_id"] for row in response.json()} == {assigned_event["id"]}


class TestEventToolsScopedToAssignment:
    """QR/distribution tools work for the presenter's own session only; other
    presenters' events stay completely invisible (404, never data)."""

    @pytest.mark.parametrize("path", ["qr-sheet", "checkin-qr", "test-qr", "survey-qr"])
    def test_qr_endpoints_hidden_for_foreign_events(
        self, client, presenter, foreign_event, path
    ):
        response = client.get(
            f"/api/events/{foreign_event['id']}/{path}", headers=presenter.headers
        )
        assert response.status_code == 404, response.text

    def test_distribution_hidden_for_foreign_events(
        self, client, presenter, foreign_event
    ):
        response = client.post(
            f"/api/events/{foreign_event['id']}/distribute", headers=presenter.headers
        )
        assert response.status_code == 404, response.text
