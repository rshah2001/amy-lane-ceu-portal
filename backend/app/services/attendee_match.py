"""Shared attendee resolution for public, identity-based submissions.

Mirrors the matching used by the file importer so that survey and post-test
submissions made through public links resolve to the same Attendee record,
backfilling an email when one was previously missing.
"""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.attendee import Attendee
from app.models.event_attendee import EventAttendee
from app.services.identity import normalize_email, normalize_name, split_name


def match_or_create_attendee(db: Session, full_name: str, email: str | None) -> Attendee:
    # Public form input arrives untrimmed; collapse stray whitespace before it
    # is stored so display names and matching keys stay clean.
    full_name = " ".join((full_name or "").split())
    email = email.strip() if email and email.strip() else None
    norm_email = normalize_email(email)
    norm_name = normalize_name(full_name)
    clauses = []
    if norm_email:
        clauses.append(Attendee.normalized_email == norm_email)
    if norm_name:
        clauses.append(Attendee.normalized_name == norm_name)
    attendee = (
        db.scalar(select(Attendee).where(or_(*clauses)).order_by(Attendee.id)) if clauses else None
    )
    if attendee:
        if not attendee.email and email:
            attendee.email = email
            attendee.normalized_email = norm_email
        return attendee
    first, last = split_name(full_name)
    attendee = Attendee(
        first_name=first,
        last_name=last,
        full_name=full_name,
        normalized_name=norm_name,
        email=email,
        normalized_email=norm_email,
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
