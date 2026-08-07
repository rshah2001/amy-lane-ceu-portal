"""The one place the application asks what time it is.

Timestamps in this codebase are already timezone-aware UTC everywhere
(``datetime.now(timezone.utc)``, ``DateTime(timezone=True)`` columns). *Dates*
were not: ``date.today()`` reads the host's local timezone, so "is this event
upcoming?" and "has this record passed its retention date?" answered differently
depending on which machine asked. On a US-hosted box that boundary moves by
4-5 hours against UTC, and on a redeploy to a differently-configured host it can
move again without a single line of code changing -- an event stops being
"upcoming" up to a day early or late, and nothing in the product explains why.

``utc_today()`` makes the boundary explicit and identical everywhere: a date
comparison is taken against the same instant the timestamps are taken against.
The stored ``event_date`` is a bare calendar date with no timezone of its own,
so *some* zone has to be chosen to compare it to "now"; choosing UTC (the zone
every other point in time here already uses) is the only choice that is stable
across hosts.
"""

from datetime import date, datetime, timezone


def utc_now() -> datetime:
    """The current instant, timezone-aware in UTC."""
    return datetime.now(timezone.utc)


def utc_today() -> date:
    """Today's calendar date in UTC.

    Use this instead of ``date.today()`` for any boundary the product's
    behaviour depends on; ``date.today()`` is the host's local date.
    """
    return utc_now().date()
