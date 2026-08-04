"""Attendee Search: cross-event by default, narrowable to one event.

The unfiltered default answers "which events has this person attended?", which
is also why reviewing a single event's roster there needs the event_id filter —
without it the page shows every event's attendees at once.
"""
import pytest

from helpers_api import create_event, upload_csv, upload_standard_roster


@pytest.fixture()
def two_events(client, admin):
    first = create_event(client, admin.headers, title="July 7 Session", event_date="2026-07-07")
    second = create_event(client, admin.headers, title="July 14 Session", event_date="2026-07-14")
    upload_standard_roster(client, admin.headers, first["id"])
    upload_csv(
        client,
        admin.headers,
        second["id"],
        "attendance",
        "Name,Email\nErin Vasquez,erin@example.com\n",
    )
    return first, second


def search(client, headers, **params) -> list[dict]:
    query = "&".join(f"{key}={value}" for key, value in params.items())
    response = client.get(f"/api/attendees/search{'?' + query if query else ''}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


class TestAttendeeSearchEventFilter:
    def test_unfiltered_search_spans_every_event(self, client, admin, two_events):
        rows = search(client, admin.headers)
        assert {row["event_title"] for row in rows} == {"July 7 Session", "July 14 Session"}

    def test_event_filter_returns_only_that_roster(self, client, admin, two_events):
        _, second = two_events
        rows = search(client, admin.headers, event_id=second["id"])
        assert [row["full_name"] for row in rows] == ["Erin Vasquez"]
        assert {row["event_id"] for row in rows} == {second["id"]}

    def test_event_filter_combines_with_the_text_query(self, client, admin, two_events):
        first, second = two_events
        assert search(client, admin.headers, q="Alice", event_id=first["id"])
        assert search(client, admin.headers, q="Alice", event_id=second["id"]) == []

    def test_filtering_to_an_empty_event_returns_nothing(self, client, admin, two_events):
        empty = create_event(client, admin.headers, title="Nobody Here Yet")
        assert search(client, admin.headers, event_id=empty["id"]) == []

    def test_event_filter_narrows_but_never_widens_for_a_presenter(
        self, client, admin, presenter
    ):
        """Asserting both directions: without the assigned event returning rows,
        an empty result for the unassigned one would prove nothing — a query that
        always returned [] would pass just as well."""
        assigned = create_event(
            client, admin.headers, title="Assigned Session", assigned_presenter_id=presenter.id
        )
        unassigned = create_event(client, admin.headers, title="Someone Else's Session")
        upload_standard_roster(client, admin.headers, assigned["id"])
        upload_standard_roster(client, admin.headers, unassigned["id"])

        visible = search(client, presenter.headers, event_id=assigned["id"])
        assert {row["event_id"] for row in visible} == {assigned["id"]}
        assert "Alice Nguyen" in {row["full_name"] for row in visible}

        # Same roster contents, but this event belongs to nobody they teach.
        assert search(client, presenter.headers, event_id=unassigned["id"]) == []
        # And the unfiltered default never leaks it either.
        assert {row["event_id"] for row in search(client, presenter.headers)} == {assigned["id"]}
