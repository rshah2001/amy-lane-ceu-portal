"""Regression tests for attendee identity matching across events.

A name alone is not a global identity: two different people sharing a name
(with no email) must never collapse into one Attendee across events. An email
IS a cross-event identity: the same address on two events stays one Attendee
linked to both. These tests exercise the upload path end-to-end and check both
the Attendee/EventAttendee tables and the compliance review output.
"""
from sqlalchemy import select

from app.models.attendee import Attendee
from app.models.event_attendee import EventAttendee
from helpers_api import compliance_rows_by_name, create_event, upload_csv

NAME_ONLY_CSV = "Name\nTaylor Reed\n"
EMAILED_CSV = "Name,Email\nTaylor Reed,taylor.reed@example.com\n"


def _taylor_attendees(db_session) -> list[Attendee]:
    return list(
        db_session.scalars(
            select(Attendee).where(Attendee.normalized_name == "taylor reed").order_by(Attendee.id)
        )
    )


def _event_ids_linked(db_session, attendee_id: int) -> list[int]:
    return list(
        db_session.scalars(
            select(EventAttendee.event_id).where(EventAttendee.attendee_id == attendee_id)
        )
    )


class TestNameOnlyMatchingIsEventScoped:
    def test_same_name_no_email_on_two_events_stays_two_people(self, client, admin, db_session):
        event_a = create_event(client, admin.headers)
        event_b = create_event(client, admin.headers, title="Different Event, Different Taylor")
        for event in (event_a, event_b):
            response = upload_csv(client, admin.headers, event["id"], "attendance", NAME_ONLY_CSV)
            assert response.status_code == 201, response.text

        attendees = _taylor_attendees(db_session)
        assert len(attendees) == 2, "same name without email must not merge across events"
        linked = {event_id for a in attendees for event_id in _event_ids_linked(db_session, a.id)}
        assert linked == {event_a["id"], event_b["id"]}
        for attendee in attendees:
            assert len(_event_ids_linked(db_session, attendee.id)) == 1, (
                "each name-only attendee must be linked only to its own event"
            )

    def test_same_name_no_email_uploaded_twice_to_same_event_dedupes(
        self, client, admin, db_session
    ):
        event = create_event(client, admin.headers)
        for _ in range(2):
            response = upload_csv(client, admin.headers, event["id"], "attendance", NAME_ONLY_CSV)
            assert response.status_code == 201, response.text

        attendees = _taylor_attendees(db_session)
        assert len(attendees) == 1, "re-uploads within one event must dedupe by name"
        assert _event_ids_linked(db_session, attendees[0].id) == [event["id"]]

    def test_compliance_review_does_not_leak_other_events_attendee(
        self, client, admin, db_session
    ):
        # Event A's Taylor has an email; event B's sign-in sheet lists a
        # different, email-less Taylor. B's compliance review must show its own
        # Taylor (no email), never A's record.
        event_a = create_event(client, admin.headers)
        event_b = create_event(client, admin.headers, title="Second Event")
        response = upload_csv(client, admin.headers, event_a["id"], "registration", EMAILED_CSV)
        assert response.status_code == 201, response.text
        response = upload_csv(client, admin.headers, event_b["id"], "attendance", NAME_ONLY_CSV)
        assert response.status_code == 201, response.text

        rows_a = compliance_rows_by_name(client, admin.headers, event_a["id"])
        rows_b = compliance_rows_by_name(client, admin.headers, event_b["id"])
        assert len(rows_a) == 1 and len(rows_b) == 1
        assert rows_a["Taylor Reed"]["attendee_id"] != rows_b["Taylor Reed"]["attendee_id"]
        assert rows_a["Taylor Reed"]["email"] == "taylor.reed@example.com"
        assert rows_b["Taylor Reed"]["email"] is None, (
            "event B's name-only attendee must not inherit event A's email"
        )

    def test_same_name_different_email_stays_two_people_even_in_one_event(
        self, client, admin, db_session
    ):
        event = create_event(client, admin.headers)
        csv_text = (
            "Name,Email\n"
            "Taylor Reed,taylor.reed@example.com\n"
            "Taylor Reed,taylor.reed@othercompany.com\n"
        )
        response = upload_csv(client, admin.headers, event["id"], "registration", csv_text)
        assert response.status_code == 201, response.text
        attendees = _taylor_attendees(db_session)
        assert len(attendees) == 2, "same name with different emails is two different people"


class TestEmailIsCrossEventIdentity:
    def test_same_email_on_two_events_is_one_attendee_linked_to_both(
        self, client, admin, db_session
    ):
        event_a = create_event(client, admin.headers)
        event_b = create_event(client, admin.headers, title="Second Event")
        for event in (event_a, event_b):
            response = upload_csv(client, admin.headers, event["id"], "attendance", EMAILED_CSV)
            assert response.status_code == 201, response.text

        attendees = _taylor_attendees(db_session)
        assert len(attendees) == 1, "the same email across events is one person"
        assert sorted(_event_ids_linked(db_session, attendees[0].id)) == sorted(
            [event_a["id"], event_b["id"]]
        )

    def test_email_upload_backfills_same_events_name_only_attendee(
        self, client, admin, db_session
    ):
        # A sign-in sheet row without an email, followed by a registration
        # export with the email, is the same person on the same event.
        event = create_event(client, admin.headers)
        response = upload_csv(client, admin.headers, event["id"], "attendance", NAME_ONLY_CSV)
        assert response.status_code == 201, response.text
        response = upload_csv(client, admin.headers, event["id"], "registration", EMAILED_CSV)
        assert response.status_code == 201, response.text

        attendees = _taylor_attendees(db_session)
        assert len(attendees) == 1
        assert attendees[0].email == "taylor.reed@example.com"
        assert _event_ids_linked(db_session, attendees[0].id) == [event["id"]]

    def test_email_upload_does_not_adopt_other_events_name_only_attendee(
        self, client, admin, db_session
    ):
        # The email-miss name fallback is event-scoped too: an emailed Taylor
        # on event B must not backfill into event A's name-only Taylor.
        event_a = create_event(client, admin.headers)
        event_b = create_event(client, admin.headers, title="Second Event")
        response = upload_csv(client, admin.headers, event_a["id"], "attendance", NAME_ONLY_CSV)
        assert response.status_code == 201, response.text
        response = upload_csv(client, admin.headers, event_b["id"], "registration", EMAILED_CSV)
        assert response.status_code == 201, response.text

        attendees = _taylor_attendees(db_session)
        assert len(attendees) == 2
        emails = sorted((a.email or "") for a in attendees)
        assert emails == ["", "taylor.reed@example.com"]
