"""Date boundaries are taken in UTC, not in the host's local timezone.

``date.today()`` reads whatever timezone the machine is configured for, so the
dashboard's "upcoming events" boundary and the retention cutoff both moved with
the host. Every *timestamp* in this codebase is already timezone-aware UTC;
these tests pin that the *dates* now agree with them.
"""
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from helpers_api import create_event

from app.core.clock import utc_now, utc_today

BACKEND_DIR = Path(__file__).resolve().parents[1]


class TestUtcToday:
    def test_matches_the_utc_date_of_now(self):
        assert utc_today() == datetime.now(timezone.utc).date()
        assert utc_now().tzinfo is timezone.utc

    @pytest.mark.parametrize(
        "tz", ["UTC", "Pacific/Kiritimati", "Pacific/Midway", "America/New_York"]
    )
    def test_is_the_same_date_whatever_the_host_timezone_is(self, tz):
        """The regression itself.

        Kiritimati is UTC+14 and Midway is UTC-11, so for most of any given day
        ``date.today()`` under those two disagrees by a whole day -- which is
        exactly how an event silently stopped being "upcoming" a day early
        after a redeploy. ``utc_today()`` cannot move, whatever TZ says.
        """
        original = os.environ.get("TZ")
        try:
            os.environ["TZ"] = tz
            time.tzset()
            assert utc_today() == datetime.now(timezone.utc).date()
        finally:
            if original is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = original
            time.tzset()


class TestDashboardUpcomingBoundary:
    def _dashboard(self, client, headers):
        response = client.get("/api/dashboard", headers=headers)
        assert response.status_code == 200, response.text
        return response.json()

    def test_boundary_follows_utc_today(self, client, admin):
        """An event dated *today* counts as upcoming; yesterday's does not."""
        today = utc_today()
        create_event(client, admin.headers, title="Yesterday", event_date=str(today - timedelta(days=1)))
        create_event(client, admin.headers, title="Today", event_date=str(today))
        create_event(client, admin.headers, title="Tomorrow", event_date=str(today + timedelta(days=1)))

        assert self._dashboard(client, admin.headers)["upcoming_events"] == 2

    def test_the_dashboard_reads_the_shared_clock(self, client, admin):
        # Pinning the wiring: with the clock moved forward a week, the events
        # inside that week stop being upcoming. If anything reintroduces
        # date.today() here, this stops tracking.
        today = utc_today()
        create_event(client, admin.headers, title="Soon", event_date=str(today + timedelta(days=3)))
        create_event(client, admin.headers, title="Later", event_date=str(today + timedelta(days=30)))

        assert self._dashboard(client, admin.headers)["upcoming_events"] == 2
        with patch("app.api.events.utc_today", return_value=today + timedelta(days=7)):
            assert self._dashboard(client, admin.headers)["upcoming_events"] == 1


class TestRetentionUsesTheSameClock:
    """The seven-year retention cutoff is a date boundary too, and the one with
    the least room for a host's timezone to have an opinion."""

    def _old_event(self, db_session, admin):
        from app.models.training_event import TrainingEvent

        event = TrainingEvent(
            title="Old CEU", event_date=date(2020, 1, 1), created_by_id=admin.id
        )
        db_session.add(event)
        db_session.commit()
        return event

    def test_expiry_default_comes_from_utc_today(self, db_session, admin):
        from app.services.retention import find_expired_events

        self._old_event(db_session, admin)
        # Called without an explicit date, the cutoff falls back to the shared
        # UTC clock rather than the host's local one.
        with patch("app.services.retention.utc_today", return_value=date(2021, 1, 1)):
            assert find_expired_events(db_session) == []
        with patch("app.services.retention.utc_today", return_value=date(2030, 1, 1)):
            expired = find_expired_events(db_session)
        assert [event.title for event, _certificates in expired] == ["Old CEU"]

    def test_an_explicit_date_still_wins(self, db_session, admin):
        from app.services.retention import find_expired_events

        self._old_event(db_session, admin)
        # The rehearsal path (`--as-of`) must not be affected by the change.
        assert find_expired_events(db_session, today=date(2021, 1, 1)) == []
        assert len(find_expired_events(db_session, today=date(2030, 1, 1))) == 1


class TestNoLocalDateBoundariesRemain:
    def test_date_today_is_not_used_anywhere_in_the_application(self):
        """A grep-style guard, in the spirit of the migration drift check.

        ``date.today()`` is not wrong everywhere in principle, but every place
        it appeared in this application was a boundary that users can observe,
        and each one silently depended on the host's configuration. Re-adding
        one should be a deliberate act with a reason, not an accident.
        """
        offenders = []
        for path in sorted((BACKEND_DIR / "app").rglob("*.py")):
            if path.name == "clock.py":
                # clock.py names it in prose to explain what it replaces.
                continue
            for number, line in enumerate(path.read_text().splitlines(), start=1):
                if re.search(r"\bdate\.today\(\)", line):
                    offenders.append(f"{path.relative_to(BACKEND_DIR)}:{number}")
        assert offenders == [], (
            "date.today() is host-local; use app.core.clock.utc_today(): "
            + ", ".join(offenders)
        )
