"""Public check-in next-step handoff, the printable QR sheet, and email Reply-To."""
from unittest.mock import patch

from helpers_api import create_event

from app.services import emailer


def checkin(client, token, name="Sam Lee", email="sam.lee@example.com"):
    return client.post(f"/api/public/checkin/{token}", json={"full_name": name, "email": email})


def get_checkin_token(client, headers, event):
    return client.get(f"/api/events/{event['id']}", headers=headers).json()["checkin_token"]


class TestCheckinNextSteps:
    def test_internal_test_and_survey_tokens_returned(self, client, admin):
        event = create_event(
            client,
            admin.headers,
            test_mode="internal",
            test_questions=[
                {"id": "q1", "prompt": "2 + 2?", "choices": ["3", "4"], "correct_index": 1}
            ],
        )
        response = checkin(client, get_checkin_token(client, admin.headers, event))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "checked_in"
        assert body["test_token"] == event["test_token"]
        assert body["survey_token"] == event["survey_token"]

    def test_external_modes_return_urls(self, client, admin):
        event = create_event(
            client,
            admin.headers,
            test_mode="external",
            post_test_url="https://forms.example.com/quiz",
            survey_mode="external",
            external_survey_url="https://forms.example.com/survey",
        )
        body = checkin(client, get_checkin_token(client, admin.headers, event)).json()
        assert body["post_test_url"] == "https://forms.example.com/quiz"
        assert body["external_survey_url"] == "https://forms.example.com/survey"
        assert "test_token" not in body
        assert "survey_token" not in body

    def test_internal_test_without_questions_offers_no_test_step(self, client, admin):
        event = create_event(client, admin.headers, test_mode="internal")
        body = checkin(client, get_checkin_token(client, admin.headers, event)).json()
        assert "test_token" not in body


class TestQrSheet:
    def test_returns_pdf_attachment(self, client, admin):
        event = create_event(client, admin.headers)
        response = client.get(f"/api/events/{event['id']}/qr-sheet", headers=admin.headers)
        assert response.status_code == 200, response.text
        assert response.content.startswith(b"%PDF")
        assert "qr-sheet.pdf" in response.headers["content-disposition"]

    def test_presenter_cannot_fetch_unassigned_event_sheet(self, client, admin, presenter):
        event = create_event(client, admin.headers)
        response = client.get(f"/api/events/{event['id']}/qr-sheet", headers=presenter.headers)
        assert response.status_code == 404


class TestReplyTo:
    def test_reply_to_header_set_when_configured(self):
        with patch.object(emailer.settings, "reply_contact_email", "amy@example.org"):
            message = emailer._build_message("someone@example.com", "Hello")
        assert message["Reply-To"] == "amy@example.org"

    def test_reply_to_absent_by_default(self):
        with patch.object(emailer.settings, "reply_contact_email", None):
            message = emailer._build_message("someone@example.com", "Hello")
        assert message["Reply-To"] is None
