"""Admin-editable default survey questions: the template seeds new events at
creation time; existing events keep their own copy."""
from helpers_api import create_event

DEFAULT_IDS = ["liked", "improve", "learned"]


class TestSurveyTemplate:
    def test_returns_builtin_defaults_when_unset(self, client, admin):
        response = client.get("/api/settings/survey-template", headers=admin.headers)
        assert response.status_code == 200, response.text
        assert [question["id"] for question in response.json()["questions"]] == DEFAULT_IDS

    def test_template_seeds_new_events_but_not_existing_ones(self, client, admin):
        existing = create_event(client, admin.headers)
        scale = ["Strongly Agree", "Agree", "Neither Agree or Disagree", "Disagree", "Strongly Disagree"]
        response = client.put(
            "/api/settings/survey-template",
            headers=admin.headers,
            json={
                "questions": [
                    {"id": "pace", "label": "The pace of the course was right", "type": "choice", "options": scale},
                    {"id": "improve", "label": "What could we improve?"},
                ]
            },
        )
        assert response.status_code == 200, response.text

        created = create_event(client, admin.headers)
        assert created["survey_questions"] == [
            {"id": "pace", "label": "The pace of the course was right", "type": "choice", "options": scale},
            {"id": "improve", "label": "What could we improve?", "type": "text", "options": []},
        ]

        untouched = client.get(f"/api/events/{existing['id']}", headers=admin.headers).json()
        assert [question["id"] for question in untouched["survey_questions"]] == DEFAULT_IDS

    def test_empty_template_resets_to_builtin_defaults(self, client, admin):
        client.put(
            "/api/settings/survey-template",
            headers=admin.headers,
            json={"questions": [{"id": "only", "label": "Only question"}]},
        )
        response = client.put("/api/settings/survey-template", headers=admin.headers, json={"questions": []})
        assert response.status_code == 200, response.text
        assert [question["id"] for question in response.json()["questions"]] == DEFAULT_IDS

    def test_choice_question_needs_two_options(self, client, admin):
        response = client.put(
            "/api/settings/survey-template",
            headers=admin.headers,
            json={"questions": [{"id": "pace", "label": "Pace was right", "type": "choice", "options": ["Agree"]}]},
        )
        assert response.status_code == 422, response.text

    def test_presenter_cannot_read_or_edit_template(self, client, presenter):
        assert client.get("/api/settings/survey-template", headers=presenter.headers).status_code == 403
        assert (
            client.put("/api/settings/survey-template", headers=presenter.headers, json={"questions": []}).status_code == 403
        )
