"""Certificate issuance through the API plus the public (unauthenticated)
verification endpoint."""
import pytest

from helpers_api import (
    compliance_rows_by_name,
    create_event,
    upload_standard_roster,
)


@pytest.fixture()
def event(client, admin):
    return create_event(client, admin.headers, title="Certificate Flow CEU")


@pytest.fixture()
def rows(client, admin, event):
    upload_standard_roster(client, admin.headers, event["id"])
    return compliance_rows_by_name(client, admin.headers, event["id"])


@pytest.fixture()
def approved_alice(client, admin, event, rows):
    alice_id = rows["Alice Nguyen"]["id"]
    response = client.post(
        f"/api/events/{event['id']}/compliance/approve",
        json={"event_attendee_ids": [alice_id], "approved": True},
        headers=admin.headers,
    )
    assert response.status_code == 200, response.text
    return alice_id


def generate(client, headers, event_id, link_id):
    return client.post(
        f"/api/events/{event_id}/certificates/{link_id}/generate", headers=headers
    )


class TestIssuance:
    def test_generate_requires_approval(self, client, admin, event, rows):
        # Alice is eligible but not yet approved.
        response = generate(client, admin.headers, event["id"], rows["Alice Nguyen"]["id"])
        assert response.status_code == 409, response.text

    def test_generate_certificate_for_approved_attendee(
        self, client, admin, event, approved_alice
    ):
        response = generate(client, admin.headers, event["id"], approved_alice)
        assert response.status_code == 200, response.text
        certificate = response.json()
        assert certificate["certificate_number"].startswith("CEU-")
        assert certificate["event_attendee_id"] == approved_alice
        assert certificate["sent_at"] is None

        # Generating again is idempotent: same certificate comes back.
        again = generate(client, admin.headers, event["id"], approved_alice)
        assert again.status_code == 200
        assert again.json()["certificate_number"] == certificate["certificate_number"]

        # And it shows up in the admin certificate list.
        listing = client.get(
            f"/api/events/{event['id']}/certificates", headers=admin.headers
        )
        assert listing.status_code == 200
        numbers = [c["certificate_number"] for c in listing.json()]
        assert numbers == [certificate["certificate_number"]]

    def test_presenter_cannot_generate_certificates(
        self, client, admin, presenter, event, approved_alice
    ):
        response = generate(client, presenter.headers, event["id"], approved_alice)
        assert response.status_code == 403, response.text

    def test_unknown_link_returns_404(self, client, admin, event, approved_alice):
        response = generate(client, admin.headers, event["id"], 999999)
        assert response.status_code == 404, response.text

    def test_send_certificate_records_sent_at(
        self, client, admin, event, approved_alice
    ):
        generate(client, admin.headers, event["id"], approved_alice)
        # Email delivery mode is forced to "log" by the test fixtures, so this
        # exercises the send path without real SMTP traffic.
        response = client.post(
            f"/api/events/{event['id']}/certificates/{approved_alice}/send",
            headers=admin.headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["sent_at"] is not None
        assert body["last_sent_to"] == "alice.nguyen@example.com"


class TestPublicVerification:
    def test_valid_certificate_verifies_without_auth(
        self, client, admin, event, approved_alice
    ):
        number = generate(client, admin.headers, event["id"], approved_alice).json()[
            "certificate_number"
        ]
        # Deliberately no Authorization header: this endpoint is public.
        response = client.get(f"/api/public/verify/{number}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["valid"] is True
        assert body["certificate_number"] == number
        assert body["attendee_name"] == "Alice Nguyen"
        assert body["event_title"] == "Certificate Flow CEU"
        assert body["status"] == "generated"

    def test_instructor_falls_back_to_presenter_name(
        self, client, admin, event, approved_alice
    ):
        # The event was created without a course_instructor (the field is being
        # retired from the UI), so verification surfaces the presenter instead.
        number = generate(client, admin.headers, event["id"], approved_alice).json()[
            "certificate_number"
        ]
        response = client.get(f"/api/public/verify/{number}")
        assert response.status_code == 200, response.text
        assert response.json()["course_instructor"] == "Jordan Miles"

    def test_explicit_instructor_still_wins_over_presenter(
        self, client, admin, event, approved_alice
    ):
        update = client.put(
            f"/api/events/{event['id']}",
            json={"course_instructor": "Dr. Casey Wren"},
            headers=admin.headers,
        )
        assert update.status_code == 200, update.text
        number = generate(client, admin.headers, event["id"], approved_alice).json()[
            "certificate_number"
        ]
        response = client.get(f"/api/public/verify/{number}")
        assert response.json()["course_instructor"] == "Dr. Casey Wren"

    def test_certificate_generates_with_long_multi_presenter_name(
        self, client, admin, event, approved_alice
    ):
        # presenter_name may hold several names (~60 chars); the certificate
        # must still render and download without failing.
        long_names = "Jane Doe, John Smith & Dr. Alexandria Featherstone-Whitaker Jr."
        assert len(long_names) >= 60
        update = client.put(
            f"/api/events/{event['id']}",
            json={"presenter_name": long_names, "course_instructor": None},
            headers=admin.headers,
        )
        assert update.status_code == 200, update.text
        number = generate(client, admin.headers, event["id"], approved_alice).json()[
            "certificate_number"
        ]
        download = client.get(f"/api/public/verify/{number}/download")
        assert download.status_code == 200, download.text
        assert download.content.startswith(b"%PDF")
        verify = client.get(f"/api/public/verify/{number}")
        assert verify.json()["course_instructor"] == long_names

    def test_unknown_certificate_number_is_invalid(self, client):
        response = client.get("/api/public/verify/CEU-00000-DOESNOTEXIST")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["valid"] is False
        assert body["certificate_number"] is None
        assert body["attendee_name"] is None

    def test_public_download_marks_certificate_downloaded(
        self, client, admin, event, approved_alice
    ):
        number = generate(client, admin.headers, event["id"], approved_alice).json()[
            "certificate_number"
        ]
        response = client.get(f"/api/public/verify/{number}/download")
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "application/pdf"
        assert response.content.startswith(b"%PDF")

        # The first public download flips the lifecycle status.
        verify = client.get(f"/api/public/verify/{number}")
        assert verify.json()["status"] == "downloaded"

    def test_download_of_unknown_certificate_returns_404(self, client):
        response = client.get("/api/public/verify/CEU-00000-DOESNOTEXIST/download")
        assert response.status_code == 404, response.text


class TestManualIssue:
    def test_admin_issues_certificate_to_anyone(self, client, admin, event):
        response = client.post(
            f"/api/events/{event['id']}/certificates/issue",
            json={"full_name": "Walk In", "email": "walk.in@example.com"},
            headers=admin.headers,
        )
        assert response.status_code == 201, response.text
        number = response.json()["certificate_number"]
        assert number.startswith("CEU-")

        verify = client.get(f"/api/public/verify/{number}").json()
        assert verify["valid"] is True
        assert verify["attendee_name"] == "Walk In"

        rows = client.get(
            f"/api/events/{event['id']}/compliance", headers=admin.headers
        ).json()
        row = next(r for r in rows if r["email"] == "walk.in@example.com")
        assert row["approved"] is True
        assert row["eligible"] is False  # never attended or tested — by design

    def test_issue_with_send_email_records_sent_at(self, client, admin, event):
        response = client.post(
            f"/api/events/{event['id']}/certificates/issue",
            json={"full_name": "Mail Me", "email": "mail.me@example.com", "send_email": True},
            headers=admin.headers,
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["sent_at"] is not None
        assert body["last_sent_to"] == "mail.me@example.com"

    def test_reissue_returns_the_same_certificate(self, client, admin, event):
        payload = {"full_name": "Once Only", "email": "once.only@example.com"}
        first = client.post(
            f"/api/events/{event['id']}/certificates/issue", json=payload, headers=admin.headers
        ).json()
        second = client.post(
            f"/api/events/{event['id']}/certificates/issue", json=payload, headers=admin.headers
        ).json()
        assert first["certificate_number"] == second["certificate_number"]

    def test_presenter_cannot_manually_issue(self, client, admin, presenter):
        event = create_event(client, admin.headers, assigned_presenter_id=presenter.id)
        response = client.post(
            f"/api/events/{event['id']}/certificates/issue",
            json={"full_name": "Walk In", "email": "walk.in@example.com"},
            headers=presenter.headers,
        )
        assert response.status_code == 403


class TestOverrideApprove:
    def test_override_approves_ineligible_attendee(self, client, admin, event, rows):
        bob_id = rows["Bob Ramos"]["id"]  # scored 70 — ineligible
        blocked = client.post(
            f"/api/events/{event['id']}/compliance/approve",
            json={"event_attendee_ids": [bob_id], "approved": True},
            headers=admin.headers,
        )
        assert blocked.status_code == 409

        overridden = client.post(
            f"/api/events/{event['id']}/compliance/approve",
            json={"event_attendee_ids": [bob_id], "approved": True, "override": True},
            headers=admin.headers,
        )
        assert overridden.status_code == 200, overridden.text
        assert overridden.json()[0]["approved"] is True

        generated = generate(client, admin.headers, event["id"], bob_id)
        assert generated.status_code == 200, generated.text

    def test_override_survives_recalculation(self, client, admin, event, rows):
        bob_id = rows["Bob Ramos"]["id"]
        client.post(
            f"/api/events/{event['id']}/compliance/approve",
            json={"event_attendee_ids": [bob_id], "approved": True, "override": True},
            headers=admin.headers,
        )
        # The compliance listing recalculates eligibility; approval must stick.
        rows_after = client.get(
            f"/api/events/{event['id']}/compliance", headers=admin.headers
        ).json()
        bob = next(r for r in rows_after if r["id"] == bob_id)
        assert bob["approved"] is True
        assert bob["compliance_status"] == "approved"
