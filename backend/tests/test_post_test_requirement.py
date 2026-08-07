"""Events that have no post-test.

The eligibility rules used to block on ``test_completed`` unconditionally, with
no equivalent of ``survey_required``, so an event that simply has no post-test
marked every attendee permanently ineligible and no certificate could ever be
issued. The requirement is now an explicit per-event flag that defaults to TRUE:
credit is never granted just because the setup was incomplete.
"""
from __future__ import annotations

from helpers_api import (
    ATTENDANCE_CSV,
    REGISTRATION_CSV,
    compliance_rows_by_name,
    create_event,
    upload_csv,
)


def roster_without_a_post_test(client, headers, event_id: int) -> None:
    for file_type, csv_text in (("registration", REGISTRATION_CSV), ("attendance", ATTENDANCE_CSV)):
        response = upload_csv(client, headers, event_id, file_type, csv_text)
        assert response.status_code == 201, response.text


def update_event(client, headers, event_id: int, **fields) -> dict:
    response = client.put(f"/api/events/{event_id}", json=fields, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


class TestDefaultsToRequired:
    def test_new_events_require_a_post_test(self, client, admin):
        event = create_event(client, admin.headers, title="Unconfigured CEU")
        assert event["test_required"] is True

    def test_attendee_without_a_post_test_stays_ineligible_by_default(self, client, admin):
        """The pre-existing behaviour, deliberately preserved."""
        event = create_event(client, admin.headers, title="Requires A Post Test")
        roster_without_a_post_test(client, admin.headers, event["id"])
        alice = compliance_rows_by_name(client, admin.headers, event["id"])["Alice Nguyen"]
        assert alice["eligible"] is False
        assert "Post-test not completed" in alice["eligibility_reasons"]
        assert alice["lifecycle_status"] == "pending_test"


class TestExplicitlyNoPostTest:
    def test_attendance_alone_makes_an_attendee_eligible(self, client, admin):
        event = create_event(
            client, admin.headers, title="Attendance Only CEU", test_required=False
        )
        assert event["test_required"] is False
        roster_without_a_post_test(client, admin.headers, event["id"])
        rows = compliance_rows_by_name(client, admin.headers, event["id"])

        alice = rows["Alice Nguyen"]
        assert alice["eligible"] is True
        assert alice["eligibility_reasons"] == []
        assert alice["lifecycle_status"] == "eligible"

        # The other rules still apply: Cara's email is malformed, Dan never
        # attended. Dropping the post-test does not drop everything else.
        assert rows["Cara Fields"]["eligibility_reasons"] == ["Missing or invalid email"]
        assert rows["Dan Poe"]["eligibility_reasons"] == ["Not found on attendance sheet"]

    def test_turning_the_requirement_off_recovers_blocked_attendees(self, client, admin):
        """The live-event failure mode: four attendees, all blocked, no way out."""
        event = create_event(client, admin.headers, title="Rescue The Blocked Event")
        roster_without_a_post_test(client, admin.headers, event["id"])
        before = compliance_rows_by_name(client, admin.headers, event["id"])
        assert all(row["eligible"] is False for row in before.values())

        update_event(client, admin.headers, event["id"], test_required=False)

        after = compliance_rows_by_name(client, admin.headers, event["id"])
        assert after["Alice Nguyen"]["eligible"] is True
        assert after["Bob Ramos"]["eligible"] is True

    def test_certificate_can_then_be_issued(self, client, admin):
        event = create_event(
            client, admin.headers, title="No Post Test CEU", test_required=False
        )
        roster_without_a_post_test(client, admin.headers, event["id"])
        link_id = compliance_rows_by_name(client, admin.headers, event["id"])["Alice Nguyen"]["id"]
        approve = client.post(
            f"/api/events/{event['id']}/compliance/approve",
            json={"event_attendee_ids": [link_id], "approved": True},
            headers=admin.headers,
        )
        assert approve.status_code == 200, approve.text
        generated = client.post(
            f"/api/events/{event['id']}/certificates/{link_id}/generate", headers=admin.headers
        )
        assert generated.status_code == 200, generated.text


class TestMisconfigurationWarning:
    """An event that requires a post-test it does not have blocks everyone."""

    def test_warning_on_an_event_with_no_post_test_configured(self, client, admin):
        event = create_event(client, admin.headers, title="Requires A Missing Test")
        assert len(event["configuration_warnings"]) == 1
        assert "post-test" in event["configuration_warnings"][0]

        fetched = client.get(f"/api/events/{event['id']}", headers=admin.headers).json()
        assert fetched["configuration_warnings"] == event["configuration_warnings"]

        listed = client.get("/api/events", headers=admin.headers).json()
        assert listed[0]["configuration_warnings"] == event["configuration_warnings"]

    def test_no_warning_once_an_external_post_test_is_linked(self, client, admin):
        event = create_event(
            client,
            admin.headers,
            title="External Test CEU",
            post_test_url="https://forms.example.com/post-test",
        )
        assert event["configuration_warnings"] == []

    def test_no_warning_once_test_questions_exist(self, client, admin):
        event = create_event(client, admin.headers, title="Internal Test CEU")
        updated = update_event(
            client,
            admin.headers,
            event["id"],
            test_questions=[
                {
                    "id": "q1",
                    "prompt": "Which control is primary?",
                    "choices": ["Hand control", "Foot pedal"],
                    "correct_index": 0,
                }
            ],
        )
        assert updated["configuration_warnings"] == []

    def test_no_warning_when_the_event_has_no_post_test_on_purpose(self, client, admin):
        event = create_event(
            client, admin.headers, title="Attendance Only CEU", test_required=False
        )
        assert event["configuration_warnings"] == []

    def test_warning_returns_if_the_requirement_is_switched_back_on(self, client, admin):
        event = create_event(
            client, admin.headers, title="Attendance Only CEU", test_required=False
        )
        updated = update_event(client, admin.headers, event["id"], test_required=True)
        assert len(updated["configuration_warnings"]) == 1
