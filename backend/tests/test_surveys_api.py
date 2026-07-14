"""Public survey submission: every response is kept as its own row, even when
the same attendee (same email) submits more than once."""
from helpers_api import create_event, upload_csv


def submit(client, token, answers, full_name="Sam Lee", email="sam.lee@example.com"):
    return client.post(
        f"/api/public/surveys/{token}",
        json={"full_name": full_name, "email": email, "answers": answers},
    )


class TestSurveySubmission:
    def test_submission_is_recorded(self, client, admin):
        event = create_event(client, admin.headers)
        response = submit(client, event["survey_token"], {"liked": "Great pacing"})
        assert response.status_code == 200, response.text
        assert response.json() == {"status": "submitted"}

        rows = client.get(
            f"/api/survey-responses?event_id={event['id']}", headers=admin.headers
        ).json()
        assert len(rows) == 1
        assert rows[0]["email"] == "sam.lee@example.com"
        assert rows[0]["answers"] == {"liked": "Great pacing"}

    def test_repeat_submissions_from_same_email_all_persist(self, client, admin):
        event = create_event(client, admin.headers)
        first = submit(client, event["survey_token"], {"liked": "First response"})
        second = submit(client, event["survey_token"], {"liked": "Second response"})
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text

        rows = client.get(
            f"/api/survey-responses?event_id={event['id']}", headers=admin.headers
        ).json()
        assert len(rows) == 2
        assert {row["email"] for row in rows} == {"sam.lee@example.com"}
        answers = {row["answers"]["liked"] for row in rows}
        assert answers == {"First response", "Second response"}

    def test_unknown_token_returns_404(self, client):
        response = submit(client, "not-a-real-token", {"liked": "n/a"})
        assert response.status_code == 404, response.text

    def test_web_submissions_survive_survey_file_upload(self, client, admin):
        event = create_event(client, admin.headers)
        submit(client, event["survey_token"], {"liked": "Web response"})

        upload_csv(
            client,
            admin.headers,
            event["id"],
            "survey",
            "Full Name,Email,Completed\nPat Doe,pat.doe@example.com,Yes\n",
        )

        rows = client.get(
            f"/api/survey-responses?event_id={event['id']}", headers=admin.headers
        ).json()
        by_email = {row["email"]: row for row in rows}
        assert "sam.lee@example.com" in by_email, "web submission was wiped by the file import"
        assert by_email["sam.lee@example.com"]["answers"] == {"liked": "Web response"}
        assert "pat.doe@example.com" in by_email

        compliance = client.get(
            f"/api/events/{event['id']}/compliance", headers=admin.headers
        ).json()
        flags = {row["email"]: row["survey_completed"] for row in compliance}
        assert flags["sam.lee@example.com"] is True
        assert flags["pat.doe@example.com"] is True

    def test_choice_question_accepts_configured_option(self, client, admin):
        event = create_event(client, admin.headers)
        scale = ["Strongly Agree", "Agree", "Neither Agree or Disagree", "Disagree", "Strongly Disagree"]
        updated = client.put(
            f"/api/events/{event['id']}",
            headers=admin.headers,
            json={
                "survey_questions": [
                    {"id": "pace", "label": "The pace was right", "type": "choice", "options": scale},
                    {"id": "improve", "label": "What could we improve?"},
                ]
            },
        )
        assert updated.status_code == 200, updated.text

        public = client.get(f"/api/public/surveys/{event['survey_token']}").json()
        assert public["questions"][0]["type"] == "choice"
        assert public["questions"][0]["options"] == scale
        assert public["questions"][1]["type"] == "text"

        response = submit(client, event["survey_token"], {"pace": "Agree", "improve": "Nothing"})
        assert response.status_code == 200, response.text
        rows = client.get(
            f"/api/survey-responses?event_id={event['id']}", headers=admin.headers
        ).json()
        assert rows[0]["answers"] == {"pace": "Agree", "improve": "Nothing"}

    def test_choice_question_rejects_answer_outside_options(self, client, admin):
        event = create_event(client, admin.headers)
        client.put(
            f"/api/events/{event['id']}",
            headers=admin.headers,
            json={
                "survey_questions": [
                    {"id": "pace", "label": "The pace was right", "type": "choice", "options": ["Agree", "Disagree"]},
                ]
            },
        )
        response = submit(client, event["survey_token"], {"pace": "Whatever I want"})
        assert response.status_code == 422, response.text

    def test_choice_question_requires_two_options(self, client, admin):
        event = create_event(client, admin.headers)
        response = client.put(
            f"/api/events/{event['id']}",
            headers=admin.headers,
            json={
                "survey_questions": [
                    {"id": "pace", "label": "The pace was right", "type": "choice", "options": ["Agree"]},
                ]
            },
        )
        assert response.status_code == 422, response.text

    def test_insights_keep_choice_answers_out_of_themes(self, client, admin):
        event = create_event(client, admin.headers)
        client.put(
            f"/api/events/{event['id']}",
            headers=admin.headers,
            json={
                "survey_questions": [
                    {"id": "pace", "label": "The pace was right", "type": "choice",
                     "options": ["Strongly Agree", "Disagree"]},
                    {"id": "improve", "label": "What could we improve?"},
                ]
            },
        )
        submit(client, event["survey_token"], {"pace": "Strongly Agree", "improve": "More handouts please"})
        insights = client.get(
            f"/api/survey-insights?event_id={event['id']}", headers=admin.headers
        ).json()
        assert insights["answers_by_question"]["pace"] == ["Strongly Agree"]
        themes = {item["theme"] for item in insights["common_themes"]}
        assert "handouts" in themes
        assert "strongly" not in themes and "agree" not in themes

    def test_reuploading_survey_file_replaces_only_file_rows(self, client, admin):
        event = create_event(client, admin.headers)
        submit(client, event["survey_token"], {"liked": "Web response"})
        file_row = "Full Name,Email,Completed\nPat Doe,pat.doe@example.com,Yes\n"
        upload_csv(client, admin.headers, event["id"], "survey", file_row)
        upload_csv(client, admin.headers, event["id"], "survey", file_row)

        rows = client.get(
            f"/api/survey-responses?event_id={event['id']}", headers=admin.headers
        ).json()
        emails = [row["email"] for row in rows]
        # One web row survives both imports; the file row is replaced, not duplicated.
        assert sorted(emails) == ["pat.doe@example.com", "sam.lee@example.com"]
