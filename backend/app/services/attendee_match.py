"""Shared attendee resolution for uploads and public, identity-based submissions.

Matching rules:

- An email is a genuine cross-event identity: when the incoming record has a
  usable email, match globally on the normalized email, so the same person
  attending two events stays one Attendee linked to both.
- A bare name is NOT a global identity: name matching only ever considers
  attendees already linked to the same event, so two different people who
  happen to share a name (or lack an email) never collapse into one record
  across events.
- A record whose email matches nobody may still merge, by name, with a
  same-event attendee who has no usable email yet — that is how a survey or
  post-test submission backfills the email missing from a sign-in sheet row.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.attendee import Attendee
from app.models.event_attendee import EventAttendee
from app.services.identity import normalize_email, normalize_name, split_name


def match_or_create_attendee(
    db: Session,
    event_id: int,
    full_name: str,
    email: str | None,
    *,
    first_name: str | None = None,
    last_name: str | None = None,
    company: str | None = None,
    license_number: str | None = None,
) -> Attendee:
    # Public form input arrives untrimmed; collapse stray whitespace before it
    # is stored so display names and matching keys stay clean.
    full_name = " ".join((full_name or "").split())
    email = email.strip() if email and email.strip() else None
    norm_email = normalize_email(email)
    norm_name = normalize_name(full_name)

    attendee: Attendee | None = None
    if norm_email:
        attendee = db.scalar(
            select(Attendee).where(Attendee.normalized_email == norm_email).order_by(Attendee.id)
        )
    if attendee is None and norm_name:
        # Name-only matching is scoped to this event's roster: a name is not a
        # global identity and must never merge attendees across events.
        query = (
            select(Attendee)
            .join(EventAttendee, EventAttendee.attendee_id == Attendee.id)
            .where(
                EventAttendee.event_id == event_id,
                Attendee.normalized_name == norm_name,
            )
            .order_by(Attendee.id)
        )
        if norm_email:
            # The incoming email matched nobody: only merge with a same-name
            # attendee on this event who has no usable email yet (backfill).
            # The same name with a different email is a different person.
            query = query.where(Attendee.normalized_email.is_(None))
        attendee = db.scalar(query)

    if attendee:
        if email and not attendee.email:
            attendee.email = email
            attendee.normalized_email = norm_email
        if company and not attendee.company:
            attendee.company = company
        if license_number and not attendee.license_number:
            attendee.license_number = license_number
        return attendee

    split_first, split_last = split_name(full_name)
    attendee = Attendee(
        first_name=first_name or split_first,
        last_name=last_name or split_last,
        full_name=full_name,
        normalized_name=norm_name,
        email=email,
        normalized_email=norm_email,
        company=company,
        license_number=license_number,
    )
    db.add(attendee)
    db.flush()
    return attendee


def get_or_create_link(db: Session, event_id: int, attendee_id: int) -> EventAttendee:
    link = db.scalar(
        select(EventAttendee).where(
            EventAttendee.event_id == event_id,
            EventAttendee.attendee_id == attendee_id,
        )
    )
    if not link:
        link = EventAttendee(event_id=event_id, attendee_id=attendee_id)
        db.add(link)
        db.flush()
    return link
