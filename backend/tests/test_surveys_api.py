"""Public survey submission: every response is kept as its own row, even when
the same attendee (same email) submits more than once."""
from helpers_api import create_event, upload_csv


def submit(client, token, answers, full_name="Sam Lee", email="sam.lee@example.com", **extra):
    return client.post(
        f"/api/public/surveys/{token}",
        json={"full_name": full_name, "email": email, "answers": answers, **extra},
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

    def test_named_submission_links_attendee_and_stores_location(self, client, admin):
        event = create_event(client, admin.headers)
        response = submit(
            client,
            event["survey_token"],
            {"liked": "Great pacing"},
            business_location="Mobility Works - Orlando",
        )
        assert response.status_code == 200, response.text

        rows = client.get(
            f"/api/survey-responses?event_id={event['id']}", headers=admin.headers
        ).json()
        assert len(rows) == 1
        assert rows[0]["attendee_id"] is not None
        assert rows[0]["full_name"] == "Sam Lee"
        assert rows[0]["email"] == "sam.lee@example.com"
        assert rows[0]["business_location"] == "Mobility Works - Orlando"

        compliance = client.get(
            f"/api/events/{event['id']}/compliance", headers=admin.headers
        ).json()
        flags = {row["email"]: row["survey_completed"] for row in compliance}
        assert flags["sam.lee@example.com"] is True

    def test_anonymous_submission_without_name_or_email(self, client, admin):
        event = create_event(client, admin.headers)
        response = submit(
            client, event["survey_token"], {"liked": "Blind feedback"}, full_name=None, email=None
        )
        assert response.status_code == 200, response.text

        rows = client.get(
            f"/api/survey-responses?event_id={event['id']}", headers=admin.headers
        ).json()
        assert len(rows) == 1
        assert rows[0]["attendee_id"] is None
        assert rows[0]["full_name"] is None
        assert rows[0]["email"] is None
        assert rows[0]["answers"] == {"liked": "Blind feedback"}
        # No attendee record is created for anonymous feedback.
        compliance = client.get(
            f"/api/events/{event['id']}/compliance", headers=admin.headers
        ).json()
        assert compliance == []

    def test_blank_strings_are_treated_as_anonymous(self, client, admin):
        event = create_event(client, admin.headers)
        response = submit(
            client, event["survey_token"], {"liked": "Blank identity"}, full_name="  ", email=""
        )
        assert response.status_code == 200, response.text
        rows = client.get(
            f"/api/survey-responses?event_id={event['id']}", headers=admin.headers
        ).json()
        assert rows[0]["attendee_id"] is None

    def test_submission_with_only_business_location(self, client, admin):
        event = create_event(client, admin.headers)
        response = submit(
            client,
            event["survey_token"],
            {"liked": "Nice venue"},
            full_name=None,
            email=None,
            business_location="Superior Van & Mobility, Louisville KY",
        )
        assert response.status_code == 200, response.text

        rows = client.get(
            f"/api/survey-responses?event_id={event['id']}", headers=admin.headers
        ).json()
        assert len(rows) == 1
        assert rows[0]["attendee_id"] is None
        assert rows[0]["business_location"] == "Superior Van & Mobility, Louisville KY"

    def test_name_only_submission_still_creates_attendee(self, client, admin):
        event = create_event(client, admin.headers)
        response = submit(client, event["survey_token"], {"liked": "Solid"}, email=None)
        assert response.status_code == 200, response.text
        rows = client.get(
            f"/api/survey-responses?event_id={event['id']}", headers=admin.headers
        ).json()
        assert rows[0]["attendee_id"] is not None
        assert rows[0]["full_name"] == "Sam Lee"
        assert rows[0]["email"] is None

    def test_provided_name_must_still_be_two_characters(self, client, admin):
        event = create_event(client, admin.headers)
        response = submit(client, event["survey_token"], {"liked": "x"}, full_name="A")
        assert response.status_code == 422, response.text

    def test_csv_export_includes_business_location_and_anonymous_rows(self, client, admin):
        event = create_event(client, admin.headers)
        submit(
            client,
            event["survey_token"],
            {"liked": "Great pacing"},
            business_location="Mobility Works - Orlando",
        )
        submit(client, event["survey_token"], {"liked": "Blind feedback"}, full_name=None, email=None)

        response = client.get(
            f"/api/survey-responses.csv?event_id={event['id']}", headers=admin.headers
        )
        assert response.status_code == 200, response.text
        lines = response.text.strip().splitlines()
        header = lines[0]
        assert "Business Name / Location" in header
        body = "\n".join(lines[1:])
        assert "Mobility Works - Orlando" in body
        assert "Anonymous" in body

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
