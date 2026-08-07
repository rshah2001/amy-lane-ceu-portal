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
- Names are compared in a normalized form (accents stripped, "Last, First"
  flipped to natural order) so the same person typed into a QR check-in and
  written on a sign-in sheet resolves to one record. An exact-name miss falls
  back to a *confirmed* variant match (middle initial / generational suffix
  only); anything less certain is left as two records for a human to judge,
  because a false merge silently denies one of two people their certificate.

Both the stored ``email`` and the matching key come from ``normalize_email``,
so eligibility ("is this address sendable?") and matching never disagree about
what an attendee's address is.

Batch loading: a file import resolves one attendee per row, which naively is
two SELECTs per row plus one per link. ``EventRoster`` loads everything an
import can match in a handful of queries and answers from memory instead.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.attendee import Attendee
from app.models.event_attendee import EventAttendee
from app.services.identity import (
    core_name,
    humanize_name,
    is_valid_email,
    names_are_variants,
    normalize_email,
    normalize_name,
    split_name,
)


class EventRoster:
    """Everything one import may match, loaded once instead of per row.

    Holds the event's current roster (attendees + their event links) plus every
    attendee that owns one of the emails appearing in the file, and is kept up
    to date as rows create new attendees and links. Resolution against it must
    mirror the SQL in ``match_or_create_attendee`` exactly, including the
    "lowest id wins" ordering, so batching can never change *which* attendee a
    row resolves to.
    """

    def __init__(self, db: Session, event_id: int, emails: set[str] | None = None) -> None:
        self.event_id = event_id
        self._by_email: dict[str, Attendee] = {}
        self._by_name: dict[str, list[Attendee]] = {}
        self._by_core_name: dict[str, list[Attendee]] = {}
        self._on_event: set[int] = set()
        self._links: dict[int, EventAttendee] = {}

        links = list(
            db.scalars(
                select(EventAttendee)
                .where(EventAttendee.event_id == event_id)
                .order_by(EventAttendee.attendee_id)
            )
        )
        self._links = {link.attendee_id: link for link in links}
        roster = (
            list(
                db.scalars(
                    select(Attendee)
                    .join(EventAttendee, EventAttendee.attendee_id == Attendee.id)
                    .where(EventAttendee.event_id == event_id)
                    .order_by(Attendee.id)
                )
            )
            if links
            else []
        )
        for attendee in roster:
            self._register_on_event(attendee)
        # Emails are a cross-event identity, so the file's addresses have to be
        # looked up globally — but as one IN (...) query, not one per row.
        wanted = {email for email in (emails or set()) if email}
        if wanted:
            for attendee in db.scalars(
                select(Attendee)
                .where(Attendee.normalized_email.in_(sorted(wanted)))
                .order_by(Attendee.id)
            ):
                self._register_email(attendee)

    def _register_email(self, attendee: Attendee) -> None:
        key = attendee.normalized_email
        if not key:
            return
        current = self._by_email.get(key)
        # "Lowest id wins" mirrors the ORDER BY in the un-batched query. A
        # freshly created attendee has no id until flush; treat it as newest.
        if current is None or (attendee.id or 0) < (current.id or 0):
            self._by_email[key] = attendee

    def _register_on_event(self, attendee: Attendee) -> None:
        self._register_email(attendee)
        # Keyed on the Python object: a row-created attendee has no id until
        # it is flushed, and the same object must not be indexed twice.
        if id(attendee) in self._on_event:
            return
        self._on_event.add(id(attendee))
        self._by_name.setdefault(attendee.normalized_name or "", []).append(attendee)
        self._by_core_name.setdefault(core_name(attendee.full_name), []).append(attendee)

    def by_email(self, norm_email: str) -> Attendee | None:
        return self._by_email.get(norm_email)

    def named(self, norm_name: str, email_less_only: bool) -> list[Attendee]:
        return [
            attendee
            for attendee in self._by_name.get(norm_name, [])
            if not (email_less_only and attendee.normalized_email)
        ]

    def variant_candidates(self, full_name: str) -> list[Attendee]:
        key = core_name(full_name)
        if not key:
            return []
        return [
            attendee
            for attendee in self._by_core_name.get(key, [])
            if names_are_variants(attendee.full_name, full_name)
        ]

    def link(self, attendee_id: int) -> EventAttendee | None:
        return self._links.get(attendee_id)

    def add_attendee(self, attendee: Attendee) -> None:
        """Record an attendee the import just created or just pulled onto the
        event, so later rows in the same file dedupe against it."""
        self._register_on_event(attendee)

    def add_link(self, link: EventAttendee) -> None:
        self._links[link.attendee_id] = link


def _match_by_name(
    db: Session,
    event_id: int,
    norm_name: str,
    email_less_only: bool,
    roster: EventRoster | None,
) -> Attendee | None:
    # Name-only matching is scoped to this event's roster: a name is not a
    # global identity and must never merge attendees across events.
    if roster is not None:
        candidates = roster.named(norm_name, email_less_only)
        return min(candidates, key=lambda a: a.id or 0) if candidates else None
    query = (
        select(Attendee)
        .join(EventAttendee, EventAttendee.attendee_id == Attendee.id)
        .where(EventAttendee.event_id == event_id, Attendee.normalized_name == norm_name)
        .order_by(Attendee.id)
    )
    if email_less_only:
        # The incoming email matched nobody: only merge with a same-name
        # attendee on this event who has no usable email yet (backfill).
        # The same name with a different email is a different person.
        query = query.where(Attendee.normalized_email.is_(None))
    return db.scalar(query)


def _match_by_variant(
    db: Session,
    event_id: int,
    full_name: str,
    norm_name: str,
    email_less_only: bool,
    roster: EventRoster | None,
    notes: list[str] | None,
) -> Attendee | None:
    """Same-event fallback for "Bob Smith" vs "Bob A. Smith" vs "Bob Smith Jr.".

    Deliberately timid: it merges only when exactly one attendee on the event
    is a confirmed variant of this name. Two or more candidates means the file
    cannot tell us who this is, so we keep them apart and ask for a human.
    """
    first = norm_name.split()[0] if norm_name else ""
    if not first:
        return None
    if roster is not None:
        candidates = roster.variant_candidates(full_name)
    else:
        # Narrow in SQL by the first token, then confirm in Python: the
        # variant rules (middle initials, suffixes) are not expressible in a
        # portable indexed predicate.
        rough = db.scalars(
            select(Attendee)
            .join(EventAttendee, EventAttendee.attendee_id == Attendee.id)
            .where(
                EventAttendee.event_id == event_id,
                Attendee.normalized_name.like(f"{first} %"),
            )
            .order_by(Attendee.id)
        )
        candidates = [a for a in rough if names_are_variants(a.full_name, full_name)]
    if email_less_only:
        candidates = [a for a in candidates if not a.normalized_email]
    candidates = [a for a in candidates if a.normalized_name != norm_name]
    if not candidates:
        return None
    if len(candidates) > 1:
        if notes is not None:
            others = ", ".join(sorted(f'"{a.full_name}"' for a in candidates))
            notes.append(
                f'"{full_name}" could be any of {others} already on this event — '
                "added as a separate person; add email addresses to link them."
            )
        return None
    match = candidates[0]
    if notes is not None:
        notes.append(
            f'Matched "{full_name}" to "{match.full_name}" already on this event '
            "(same name apart from a middle initial or suffix) — confirm they "
            "are the same person."
        )
    return match


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
    roster: EventRoster | None = None,
    notes: list[str] | None = None,
) -> Attendee:
    # Public form input arrives untrimmed and Teams/registration exports write
    # "Last, First"; normalize both here so a QR check-in typed "Smith, Bob"
    # resolves to the sign-in sheet's "Bob Smith" instead of a second record.
    full_name = humanize_name(full_name)
    email = email.strip() if email and email.strip() else None
    norm_email = normalize_email(email)
    norm_name = normalize_name(full_name)

    attendee: Attendee | None = None
    if norm_email:
        attendee = (
            roster.by_email(norm_email)
            if roster is not None
            else db.scalar(
                select(Attendee).where(Attendee.normalized_email == norm_email).order_by(Attendee.id)
            )
        )
    if attendee is None and norm_name:
        attendee = _match_by_name(db, event_id, norm_name, bool(norm_email), roster)
    if attendee is None and norm_name:
        attendee = _match_by_variant(
            db, event_id, full_name, norm_name, bool(norm_email), roster, notes
        )

    if attendee:
        if norm_email and not is_valid_email(attendee.email):
            # Store the normalized address, not the raw text. "Bob Smith
            # <bob@x.com>" and "mailto:bob@x.com" match fine but are not
            # sendable, and eligibility checks the stored address — writing the
            # normalized form keeps matching, eligibility and delivery agreed.
            attendee.email = norm_email
            attendee.normalized_email = norm_email
            if roster is not None:
                roster.add_attendee(attendee)
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
        email=norm_email or email,
        normalized_email=norm_email,
        company=company,
        license_number=license_number,
    )
    db.add(attendee)
    db.flush()
    if roster is not None:
        # Every caller links the attendee to the event immediately after, so
        # later rows in the same file must already see it on the roster.
        roster.add_attendee(attendee)
    return attendee


def get_or_create_link(
    db: Session,
    event_id: int,
    attendee_id: int,
    *,
    roster: EventRoster | None = None,
) -> EventAttendee:
    link = roster.link(attendee_id) if roster is not None else None
    if link is None and roster is None:
        link = db.scalar(
            select(EventAttendee).where(
                EventAttendee.event_id == event_id,
                EventAttendee.attendee_id == attendee_id,
            )
        )
    if not link:
        link = EventAttendee(event_id=event_id, attendee_id=attendee_id)
        db.add(link)
        if roster is None:
            db.flush()
        else:
            # An import knows its own links from the roster, so there is no
            # need to make each one visible to a query immediately; leaving
            # them pending lets SQLAlchemy insert them as one batch. The caller
            # must flush before it queries these links back (process_rows does).
            roster.add_link(link)
    return link
