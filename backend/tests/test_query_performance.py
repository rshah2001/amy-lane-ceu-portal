"""Statement counts on the paths that run once per attendee action.

``recalculate_event`` is called by every public check-in, post-test and survey
submission, and by every compliance review. It reads ``link.attendee`` and
``link.event`` for each link, which without eager loading is one lazy SELECT
per attendee: a single check-in on a 200-person event measured at 207 SELECTs.

The assertions here are deliberately shaped as "the count does not grow with
the roster", not "the count is under N". An absolute threshold drifts as
unrelated features add queries; the invariant that actually matters is that the
work per request is independent of how many people are on the event.
"""
from datetime import date

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy import select

from app.models.attendee import Attendee
from app.models.event_attendee import EventAttendee
from app.models.training_event import TrainingEvent


@pytest.fixture()
def count_selects(engine):
    """Count SELECT statements issued while the context is active."""
    counter = {"selects": 0, "enabled": False}

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        if counter["enabled"] and statement.lstrip().upper().startswith("SELECT"):
            counter["selects"] += 1

    sa_event.listen(engine, "before_cursor_execute", before_cursor_execute)
    yield counter
    sa_event.remove(engine, "before_cursor_execute", before_cursor_execute)


def build_event(db_session, admin_id, *, roster_size: int, token: str) -> TrainingEvent:
    training_event = TrainingEvent(
        title=f"Roster of {roster_size}",
        event_date=date(2026, 6, 15),
        created_by_id=admin_id,
        checkin_token=token,
        test_required=False,
        survey_required=False,
    )
    db_session.add(training_event)
    db_session.flush()
    for index in range(roster_size):
        attendee = Attendee(
            full_name=f"Person {index} {token}",
            normalized_name=f"person {index} {token}",
            email=f"p{index}.{token}@example.com",
            normalized_email=f"p{index}.{token}@example.com",
        )
        db_session.add(attendee)
        db_session.flush()
        db_session.add(
            EventAttendee(
                event_id=training_event.id,
                attendee_id=attendee.id,
                registered=True,
                attended=True,
            )
        )
    db_session.commit()
    return training_event


def checkin(client, token, name, email):
    return client.post(
        f"/api/public/checkin/{token}", json={"full_name": name, "email": email}
    )


class TestPublicCheckinQueryCount:
    def test_cost_does_not_grow_with_the_roster(
        self, client, db_session, admin, count_selects
    ):
        build_event(db_session, admin.id, roster_size=10, token="small")
        build_event(db_session, admin.id, roster_size=120, token="large")

        count_selects["enabled"] = True
        count_selects["selects"] = 0
        assert checkin(client, "small", "New Small", "new.small@example.com").status_code == 200
        small = count_selects["selects"]

        count_selects["selects"] = 0
        assert checkin(client, "large", "New Large", "new.large@example.com").status_code == 200
        large = count_selects["selects"]
        count_selects["enabled"] = False

        # Before the eager load this was ~13 vs ~123: one extra SELECT for
        # every additional attendee on the event.
        assert small == large, f"{small} SELECTs on 10 attendees, {large} on 120"
        # And the absolute number stays in single digits, which is what makes
        # the equality above meaningful rather than accidentally satisfied.
        assert large < 20, large

    def test_recalculate_event_is_a_handful_of_statements(
        self, db_session, admin, count_selects
    ):
        from app.services.compliance import recalculate_event

        training_event = build_event(db_session, admin.id, roster_size=150, token="service")
        db_session.expire_all()

        count_selects["enabled"] = True
        count_selects["selects"] = 0
        links = recalculate_event(db_session, training_event.id)
        count_selects["enabled"] = False

        assert len(links) == 150
        # One for the links, one for the batched attendees, one for the batched
        # event. Anything near 150 means the eager loads were dropped.
        assert count_selects["selects"] <= 5, count_selects["selects"]

    def test_eligibility_is_still_correct_after_the_eager_load(
        self, client, db_session, admin, count_selects
    ):
        """The optimisation must not change a single answer."""
        from app.services.compliance import recalculate_event

        training_event = build_event(db_session, admin.id, roster_size=3, token="correct")
        # One attendee's address is junk, so exactly one row must come back
        # ineligible for the email reason.
        broken = db_session.scalar(
            select(Attendee).where(Attendee.email == "p1.correct@example.com")
        )
        broken.email = "not-an-address"
        broken.normalized_email = None
        db_session.commit()

        links = recalculate_event(db_session, training_event.id)
        db_session.commit()
        by_email = {link.attendee.email: link for link in links}
        assert by_email["not-an-address"].eligible is False
        assert by_email["not-an-address"].eligibility_reasons == ["Missing or invalid email"]
        assert by_email["p0.correct@example.com"].eligible is True
        assert by_email["p2.correct@example.com"].eligible is True
