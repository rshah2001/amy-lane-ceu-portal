"""Regression tests for the confirmed security-audit findings.

One class per finding:

1. CSV formula injection in the report/survey exports (data arrives from
   UNAUTHENTICATED public endpoints).
2. The committed placeholder SECRET_KEY must fail closed everywhere except a
   local development box.
3. Abuse controls on the public write endpoints.
4. Public certificate verification: read-only, rate limited, no anonymous PDF
   regeneration.
5. A non-numeric JWT ``sub`` is a 401, not a 500.
6. The anonymous survey payload is bounded and template-scoped.
"""
import logging

import pytest
from helpers_api import create_event

from app.core import config as config_module
from app.core.config import DEFAULT_SECRET_KEY, Settings, enforce_secret_key
from app.core.rate_limit import reset_public_rate_limits
from app.core.security import create_access_token
from app.services.csv_safe import csv_safe

EVIL = "=cmd|'/C calc'!A1"


def checkin_token(client, headers, event) -> str:
    return client.get(f"/api/events/{event['id']}", headers=headers).json()["checkin_token"]


def tighten_limits(monkeypatch, **overrides) -> None:
    """Point the public limiters at test-sized budgets.

    ``reset`` is what makes the new values take effect: the limiters read the
    settings when they build their guard, then cache it.
    """
    for name, value in overrides.items():
        monkeypatch.setattr(config_module.settings, name, value)
    reset_public_rate_limits()


# --- 1. CSV formula injection ------------------------------------------------


class TestCsvSafeHelper:
    @pytest.mark.parametrize(
        "value",
        [
            "=cmd|'/C calc'!A1",
            "+1+1",
            "@SUM(A1)",
            "-2+3+cmd|'/C calc'!A1",
            "\t=1+1",
            "\r=1+1",
            " =1+1",
        ],
    )
    def test_dangerous_cells_are_quoted(self, value):
        assert csv_safe(value) == f"'{value}"

    @pytest.mark.parametrize("value", ["-5", "-12.5", "+7", "5", "0", " -5"])
    def test_plain_numbers_stay_readable(self, value):
        # The documented tradeoff: a cell that is *only* a number cannot carry a
        # payload, so negative scores/hours are not mangled into '-5.
        assert csv_safe(value) == value

    @pytest.mark.parametrize(
        "value,expected",
        [("Alice Nguyen", "Alice Nguyen"), ("", ""), (None, ""), (12, "12")],
    )
    def test_ordinary_values_pass_through(self, value, expected):
        assert csv_safe(value) == expected


class TestExportsNeutralizeFormulas:
    def test_annual_report_quotes_name_from_public_checkin(self, client, admin):
        event = create_event(client, admin.headers)
        response = client.post(
            f"/api/public/checkin/{checkin_token(client, admin.headers, event)}",
            json={"full_name": EVIL, "email": "attacker@example.com"},
        )
        assert response.status_code == 200, response.text

        report = client.get("/api/reports/annual/2026", headers=admin.headers)
        assert report.status_code == 200, report.text
        assert f"'{EVIL}" in report.text
        for cell in report.text.replace('"', "").replace("\r", "").split(","):
            assert not cell.startswith("="), f"unneutralized formula cell: {cell!r}"

    def test_annual_report_headers_are_not_quoted(self, client, admin):
        create_event(client, admin.headers)
        report = client.get("/api/reports/annual/2026", headers=admin.headers)
        assert report.text.splitlines()[0].startswith("Event,Event Date,Attendee")

    def test_survey_export_quotes_answers_and_location(self, client, admin):
        event = create_event(client, admin.headers)
        submitted = client.post(
            f"/api/public/surveys/{event['survey_token']}",
            json={
                "full_name": EVIL,
                "email": "attacker@example.com",
                "business_location": "@SUM(1+1)",
                "answers": {"liked": EVIL},
            },
        )
        assert submitted.status_code == 200, submitted.text

        export = client.get("/api/survey-responses.csv", headers=admin.headers)
        assert export.status_code == 200, export.text
        body = "\n".join(export.text.splitlines()[1:])
        assert f"'{EVIL}" in body
        assert "'@SUM(1+1)" in body
        for cell in body.replace('"', "").replace("\r", "").split(","):
            assert not cell.startswith(("=", "@")), f"unneutralized formula cell: {cell!r}"

    def test_survey_export_keeps_fixed_headers_verbatim(self, client, admin):
        create_event(client, admin.headers)
        export = client.get("/api/survey-responses.csv", headers=admin.headers)
        assert export.text.splitlines()[0].startswith(
            "Event,Attendee,Email,Company,Business Name / Location,Completed at"
        )


# --- 2. Default SECRET_KEY fails closed outside local development ------------


class TestSecretKeyEnforcement:
    @pytest.fixture(autouse=True)
    def not_under_pytest(self, monkeypatch):
        """Pretend we are a real deployment.

        The suite itself runs on the placeholder key, so the check exempts test
        runs; these cases have to look past that exemption.
        """
        monkeypatch.setattr(config_module, "running_under_pytest", lambda: False)

    @pytest.mark.parametrize("environment", ["staging", "preview", "production", "prod"])
    @pytest.mark.parametrize("key", [DEFAULT_SECRET_KEY, ""])
    def test_placeholder_key_is_rejected_outside_development(self, environment, key):
        settings = Settings(environment=environment, secret_key=key)
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            enforce_secret_key(settings)

    def test_development_is_allowed_but_warns_loudly(self, caplog):
        settings = Settings(environment="development", secret_key=DEFAULT_SECRET_KEY)
        with caplog.at_level(logging.WARNING, logger=config_module.logger.name):
            enforce_secret_key(settings)
        assert any("SECRET_KEY" in record.message for record in caplog.records)

    @pytest.mark.parametrize("environment", ["development", "staging", "production"])
    def test_a_real_key_is_accepted_everywhere(self, environment):
        enforce_secret_key(Settings(environment=environment, secret_key="a-real-unique-key"))

    def test_test_runs_keep_working_on_the_placeholder(self, monkeypatch):
        monkeypatch.setattr(config_module, "running_under_pytest", lambda: True)
        enforce_secret_key(Settings(environment="production", secret_key=DEFAULT_SECRET_KEY))


# --- 3. Abuse controls on the public write endpoints -------------------------


class TestPublicWriteRateLimits:
    def test_checkin_stops_after_the_budget(self, client, admin, monkeypatch):
        tighten_limits(monkeypatch, public_write_rate_limit=3)
        event = create_event(client, admin.headers)
        token = checkin_token(client, admin.headers, event)

        for index in range(3):
            response = client.post(
                f"/api/public/checkin/{token}",
                json={"full_name": f"Scripted {index}", "email": f"bot{index}@example.com"},
            )
            assert response.status_code == 200, response.text

        blocked = client.post(
            f"/api/public/checkin/{token}",
            json={"full_name": "Scripted 4", "email": "bot4@example.com"},
        )
        assert blocked.status_code == 429, blocked.text
        assert int(blocked.headers["retry-after"]) > 0

    def test_survey_stops_after_the_budget(self, client, admin, monkeypatch):
        tighten_limits(monkeypatch, public_write_rate_limit=2)
        event = create_event(client, admin.headers)
        for _ in range(2):
            assert (
                client.post(
                    f"/api/public/surveys/{event['survey_token']}",
                    json={"answers": {"liked": "Fine"}},
                ).status_code
                == 200
            )
        blocked = client.post(
            f"/api/public/surveys/{event['survey_token']}",
            json={"answers": {"liked": "Fine"}},
        )
        assert blocked.status_code == 429

    def test_post_test_stops_after_the_budget(self, client, admin, monkeypatch):
        tighten_limits(monkeypatch, public_write_rate_limit=1)
        event = create_event(
            client,
            admin.headers,
            test_mode="internal",
            test_questions=[{"id": "q1", "prompt": "2 + 2?", "choices": ["3", "4"], "correct_index": 1}],
        )
        payload = {"full_name": "Sam Lee", "email": "sam.lee@example.com", "answers": {"q1": 1}}
        assert client.post(f"/api/public/tests/{event['test_token']}", json=payload).status_code == 200
        blocked = client.post(f"/api/public/tests/{event['test_token']}", json=payload)
        assert blocked.status_code == 429

    def test_each_event_token_has_its_own_budget(self, client, admin, monkeypatch):
        tighten_limits(monkeypatch, public_write_rate_limit=1)
        first = create_event(client, admin.headers)
        second = create_event(client, admin.headers, title="Second CEU Event")
        body = {"answers": {"liked": "Fine"}}
        assert client.post(f"/api/public/surveys/{first['survey_token']}", json=body).status_code == 200
        assert client.post(f"/api/public/surveys/{first['survey_token']}", json=body).status_code == 429
        # A different event is unaffected: one hammered token must not shut the
        # whole portal for everyone else.
        assert client.post(f"/api/public/surveys/{second['survey_token']}", json=body).status_code == 200

    def test_each_client_ip_has_its_own_budget(self, client, admin, monkeypatch):
        tighten_limits(monkeypatch, public_write_rate_limit=1)
        event = create_event(client, admin.headers)
        url = f"/api/public/surveys/{event['survey_token']}"
        body = {"answers": {"liked": "Fine"}}
        assert client.post(url, json=body, headers={"X-Forwarded-For": "203.0.113.9"}).status_code == 200
        assert client.post(url, json=body, headers={"X-Forwarded-For": "203.0.113.9"}).status_code == 429
        # A whole classroom checks in from different phones at once; one busy
        # attendee must not lock out the next.
        assert client.post(url, json=body, headers={"X-Forwarded-For": "203.0.113.10"}).status_code == 200

    def test_limiter_can_be_switched_off(self, client, admin, monkeypatch):
        tighten_limits(monkeypatch, public_write_rate_limit=1, public_rate_limit_enabled=False)
        event = create_event(client, admin.headers)
        for _ in range(5):
            response = client.post(
                f"/api/public/surveys/{event['survey_token']}",
                json={"answers": {"liked": "Fine"}},
            )
            assert response.status_code == 200, response.text


# --- 4. Public certificate verification --------------------------------------


@pytest.fixture()
def issued_certificate(client, admin):
    """An event with one manually issued (and therefore generated) certificate."""
    event = create_event(client, admin.headers)
    response = client.post(
        f"/api/events/{event['id']}/certificates/issue",
        json={"full_name": "Walk In", "email": "walk.in@example.com"},
        headers=admin.headers,
    )
    assert response.status_code == 201, response.text
    return {"event": event, **response.json()}


class TestPublicVerificationHardening:
    def test_public_lookup_still_works_without_auth(self, client, issued_certificate):
        # The legitimate "is this certificate real?" use case must survive.
        response = client.get(f"/api/public/verify/{issued_certificate['certificate_number']}")
        assert response.status_code == 200, response.text
        assert response.json()["valid"] is True
        assert response.json()["attendee_name"] == "Walk In"

    def test_verify_never_marks_the_certificate_downloaded(
        self, client, db_session, issued_certificate
    ):
        from app.models.certificate import Certificate

        number = issued_certificate["certificate_number"]
        for _ in range(3):
            assert client.get(f"/api/public/verify/{number}").status_code == 200

        certificate = db_session.get(Certificate, issued_certificate["id"])
        db_session.refresh(certificate)
        assert certificate.downloaded_at is None, "an anonymous lookup is not a delivery"
        assert client.get(f"/api/public/verify/{number}").json()["status"] == "generated"

    def test_a_real_download_still_marks_it(self, client, issued_certificate):
        number = issued_certificate["certificate_number"]
        assert client.get(f"/api/public/verify/{number}/download").status_code == 200
        assert client.get(f"/api/public/verify/{number}").json()["status"] == "downloaded"

    def test_anonymous_caller_cannot_trigger_pdf_regeneration(
        self, client, db_session, issued_certificate
    ):
        from pathlib import Path

        from app.models.certificate import Certificate

        certificate = db_session.get(Certificate, issued_certificate["id"])
        path = Path(certificate.pdf_path)
        path.unlink()

        response = client.get(f"/api/public/verify/{certificate.certificate_number}/download")
        assert response.status_code == 409, response.text
        assert not path.exists(), "the public route must not re-render the PDF"
        db_session.refresh(certificate)
        assert certificate.downloaded_at is None, "a failed fetch is not a download"

    def test_admin_download_still_regenerates_a_missing_pdf(
        self, client, admin, db_session, issued_certificate
    ):
        from pathlib import Path

        from app.models.certificate import Certificate

        certificate = db_session.get(Certificate, issued_certificate["id"])
        Path(certificate.pdf_path).unlink()

        response = client.get(
            f"/api/events/{issued_certificate['event']['id']}/certificates/{certificate.id}/download",
            headers=admin.headers,
        )
        assert response.status_code == 200, response.text
        assert response.content.startswith(b"%PDF")

    def test_verification_is_rate_limited(self, client, monkeypatch, issued_certificate):
        tighten_limits(monkeypatch, public_verify_rate_limit=2)
        number = issued_certificate["certificate_number"]
        for _ in range(2):
            assert client.get(f"/api/public/verify/{number}").status_code == 200
        blocked = client.get(f"/api/public/verify/{number}")
        assert blocked.status_code == 429
        assert int(blocked.headers["retry-after"]) > 0

    def test_verification_budget_is_separate_from_the_write_budget(
        self, client, admin, monkeypatch, issued_certificate
    ):
        tighten_limits(monkeypatch, public_write_rate_limit=1, public_verify_rate_limit=10)
        event = create_event(client, admin.headers, title="Another CEU Event")
        body = {"answers": {"liked": "Fine"}}
        assert client.post(f"/api/public/surveys/{event['survey_token']}", json=body).status_code == 200
        assert client.post(f"/api/public/surveys/{event['survey_token']}", json=body).status_code == 429
        # Verification lookups keep working while a survey token is locked out.
        assert client.get(f"/api/public/verify/{issued_certificate['certificate_number']}").status_code == 200


# --- 5. Malformed JWT subject ------------------------------------------------


class TestMalformedTokenSubject:
    @pytest.mark.parametrize("subject", ["not-a-number", "", "1; DROP TABLE users"])
    def test_non_numeric_subject_is_401_not_500(self, client, subject):
        token = create_access_token(subject, "admin")
        response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401, response.text

    def test_valid_subject_still_authenticates(self, client, admin):
        response = client.get("/api/auth/me", headers=admin.headers)
        assert response.status_code == 200, response.text
        assert response.json()["id"] == admin.id


# --- 6. Bounded survey answers ----------------------------------------------


class TestSurveyAnswerLimits:
    def test_template_questions_are_accepted(self, client, admin):
        event = create_event(client, admin.headers)
        response = client.post(
            f"/api/public/surveys/{event['survey_token']}",
            json={"answers": {"liked": "Great", "improve": "Nothing", "learned": "Lots"}},
        )
        assert response.status_code == 200, response.text

    def test_question_ids_outside_the_template_are_rejected(self, client, admin):
        event = create_event(client, admin.headers)
        response = client.post(
            f"/api/public/surveys/{event['survey_token']}",
            json={"answers": {"liked": "Great", "injected_key": "junk"}},
        )
        assert response.status_code == 422, response.text
        assert "injected_key" in response.text

    def test_too_many_answers_are_rejected(self, client, admin):
        event = create_event(client, admin.headers)
        response = client.post(
            f"/api/public/surveys/{event['survey_token']}",
            json={"answers": {f"q{index}": "x" for index in range(51)}},
        )
        assert response.status_code == 422, response.text

    def test_oversized_answer_is_rejected(self, client, admin):
        event = create_event(client, admin.headers)
        response = client.post(
            f"/api/public/surveys/{event['survey_token']}",
            json={"answers": {"liked": "x" * 4001}},
        )
        assert response.status_code == 422, response.text

    def test_answer_at_the_limit_is_accepted(self, client, admin):
        event = create_event(client, admin.headers)
        response = client.post(
            f"/api/public/surveys/{event['survey_token']}",
            json={"answers": {"liked": "x" * 4000}},
        )
        assert response.status_code == 200, response.text

    def test_oversized_question_id_is_rejected(self, client, admin):
        event = create_event(client, admin.headers)
        response = client.post(
            f"/api/public/surveys/{event['survey_token']}",
            json={"answers": {"q" * 101: "x"}},
        )
        assert response.status_code == 422, response.text
