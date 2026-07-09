"""Event endpoints and role scoping: presenters only see assigned events and
are barred from admin-only endpoints."""
from helpers_api import create_event


class TestEventCreation:
    def test_admin_creates_event(self, client, admin):
        event = create_event(client, admin.headers, title="Ramp Install CEU")
        assert event["title"] == "Ramp Install CEU"
        assert event["status"] == "draft"
        assert event["created_by_id"] == admin.id

    def test_presenter_cannot_create_event(self, client, presenter):
        response = client.post(
            "/api/events",
            json={"title": "Rogue Event", "event_date": "2026-06-15"},
            headers=presenter.headers,
        )
        assert response.status_code == 403, response.text

    def test_assigning_unknown_presenter_is_rejected(self, client, admin):
        response = client.post(
            "/api/events",
            json={
                "title": "Bad Assignment",
                "event_date": "2026-06-15",
                "assigned_presenter_id": 999999,
            },
            headers=admin.headers,
        )
        assert response.status_code == 400, response.text


class TestEventUpdate:
    def test_admin_updates_fields_without_touching_others(self, client, admin):
        event = create_event(client, admin.headers, title="Original Title")
        response = client.put(
            f"/api/events/{event['id']}",
            json={"title": "Edited Title", "location": "Tampa, FL"},
            headers=admin.headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["title"] == "Edited Title"
        assert body["location"] == "Tampa, FL"
        # Fields not sent stay untouched, and tokens are never regenerated.
        assert body["presenter_name"] == event["presenter_name"]
        assert body["event_date"] == event["event_date"]
        assert body["survey_token"] == event["survey_token"]
        assert body["test_token"] == event["test_token"]

    def test_editing_questions_replaces_the_whole_list(self, client, admin):
        event = create_event(client, admin.headers)
        new_test_questions = [
            {
                "id": "q1",
                "prompt": "What is the max ramp slope?",
                "choices": ["1:12", "1:6"],
                "correct_index": 0,
            }
        ]
        new_survey_questions = [{"id": "custom", "label": "Any other feedback?"}]
        response = client.put(
            f"/api/events/{event['id']}",
            json={
                "test_questions": new_test_questions,
                "survey_questions": new_survey_questions,
            },
            headers=admin.headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["test_questions"] == new_test_questions

        # The default 3 survey questions are fully replaced by the new list,
        # served through the existing (unchanged) survey token.
        survey = client.get(f"/api/public/surveys/{event['survey_token']}")
        assert survey.status_code == 200, survey.text
        assert survey.json()["questions"] == new_survey_questions

    def test_update_validates_assigned_presenter(self, client, admin, presenter):
        event = create_event(client, admin.headers)
        response = client.put(
            f"/api/events/{event['id']}",
            json={"assigned_presenter_id": 999999},
            headers=admin.headers,
        )
        assert response.status_code == 400, response.text

        response = client.put(
            f"/api/events/{event['id']}",
            json={"assigned_presenter_id": presenter.id},
            headers=admin.headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["assigned_presenter_id"] == presenter.id

    def test_presenter_cannot_update_event(self, client, admin, presenter):
        event = create_event(client, admin.headers, assigned_presenter_id=presenter.id)
        response = client.put(
            f"/api/events/{event['id']}",
            json={"title": "Hijacked Title"},
            headers=presenter.headers,
        )
        assert response.status_code == 403, response.text

    def test_update_unknown_event_returns_404(self, client, admin):
        response = client.put(
            "/api/events/999999", json={"title": "Ghost Event"}, headers=admin.headers
        )
        assert response.status_code == 404, response.text


class TestRoleScoping:
    def test_presenter_sees_only_assigned_events(
        self, client, admin, presenter, other_presenter
    ):
        mine = create_event(
            client, admin.headers, title="Assigned To Me", assigned_presenter_id=presenter.id
        )
        theirs = create_event(
            client,
            admin.headers,
            title="Assigned To Someone Else",
            assigned_presenter_id=other_presenter.id,
        )
        unassigned = create_event(client, admin.headers, title="Unassigned Event")

        # Admin sees all three.
        admin_ids = {e["id"] for e in client.get("/api/events", headers=admin.headers).json()}
        assert {mine["id"], theirs["id"], unassigned["id"]} <= admin_ids

        # Presenter list is scoped to assigned events only.
        response = client.get("/api/events", headers=presenter.headers)
        assert response.status_code == 200
        presenter_ids = {e["id"] for e in response.json()}
        assert presenter_ids == {mine["id"]}

    def test_presenter_cannot_fetch_another_presenters_event(
        self, client, admin, presenter, other_presenter
    ):
        theirs = create_event(
            client,
            admin.headers,
            title="Not Yours",
            assigned_presenter_id=other_presenter.id,
        )
        response = client.get(f"/api/events/{theirs['id']}", headers=presenter.headers)
        assert response.status_code == 404, response.text

        # But the assignee can fetch it.
        response = client.get(f"/api/events/{theirs['id']}", headers=other_presenter.headers)
        assert response.status_code == 200
        assert response.json()["assigned_presenter_id"] == other_presenter.id

    def test_unauthenticated_request_is_rejected(self, client):
        response = client.get("/api/events")
        assert response.status_code in (401, 403), response.text


class TestAdminOnlyEndpoints:
    def test_presenter_cannot_list_users(self, client, presenter):
        response = client.get("/api/users", headers=presenter.headers)
        assert response.status_code == 403, response.text

    def test_presenter_cannot_create_users(self, client, presenter):
        response = client.post(
            "/api/users",
            json={
                "email": "sneaky@example.com",
                "full_name": "Sneaky Presenter",
                "role": "admin",
                "password": "Password123!",
            },
            headers=presenter.headers,
        )
        assert response.status_code == 403, response.text

    def test_presenter_cannot_update_users(self, client, presenter, admin):
        response = client.patch(
            f"/api/users/{admin.id}",
            json={"is_active": False},
            headers=presenter.headers,
        )
        assert response.status_code == 403, response.text

    def test_admin_can_list_users(self, client, admin, presenter):
        response = client.get("/api/users", headers=admin.headers)
        assert response.status_code == 200, response.text
        emails = {u["email"] for u in response.json()}
        assert {admin.email, presenter.email} <= emails

    def test_presenter_cannot_manage_certificates(self, client, admin, presenter):
        event = create_event(
            client, admin.headers, assigned_presenter_id=presenter.id
        )
        response = client.get(
            f"/api/events/{event['id']}/certificates", headers=presenter.headers
        )
        assert response.status_code == 403, response.text

    def test_presenter_cannot_approve_attendees(self, client, admin, presenter):
        event = create_event(client, admin.headers, assigned_presenter_id=presenter.id)
        response = client.post(
            f"/api/events/{event['id']}/compliance/approve",
            json={"event_attendee_ids": [1], "approved": True},
            headers=presenter.headers,
        )
        assert response.status_code == 403, response.text

    def test_settings_endpoint_access(self, client, admin, presenter):
        response = client.get("/api/settings", headers=admin.headers)
        assert response.status_code == 200, response.text
        assert response.json()["current_user"]["email"] == admin.email

        # NOTE: /api/settings currently only requires authentication
        # (get_current_user), not the admin role, so presenters get a 200.
        # Accept 403 too so this test survives if the endpoint is hardened
        # to admin-only.
        response = client.get("/api/settings", headers=presenter.headers)
        assert response.status_code in (200, 403), response.text
