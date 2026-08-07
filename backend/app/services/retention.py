"""Record retention: the minimum-retention guard and the operator-run purge.

The provider attestation (``docs/data-storage-and-retention-confirmation.md``)
commits to two things about retention, and this module implements both:

1. **Records are retained for seven years** from the associated training event.
   ``retention_block`` turns that into an enforced floor: an event that still
   holds an issued certificate inside its retention window cannot be deleted,
   by an admin or by anything else.
2. **Records are securely deleted after the retention period.**
   ``purge_expired`` finds events whose whole retention window has elapsed and
   removes their database rows and stored files.

Deliberately NOT scheduled
--------------------------
Nothing here is wired to a scheduler, a startup hook, or a background task, and
``purge_expired`` is a **dry run unless it is passed apply=True**. A process
that silently destroys compliance records on a timer is not something to switch
on without the record owner's explicit decision -- one wrong ``retention_years``
and seven years of certificates are gone with no way back. The purge is run by
an operator, on purpose:

    # show what would be purged (safe, changes nothing)
    python -m app.services.retention

    # actually purge
    python -m app.services.retention --apply

Turning this into a scheduled job is a decision for the record owner, and it
should keep the dry-run output as its review step.
"""
from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.certificate import Certificate
from app.models.event_attendee import EventAttendee
from app.models.training_event import TrainingEvent
from app.models.user import User
from app.services import storage
from app.services.audit import record_audit

logger = logging.getLogger("app.retention")


def _add_years(value: date, years: int) -> date:
    """value + N years, moving Feb 29 to Feb 28 in a non-leap year."""
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, month=3, day=1)


def is_issued(certificate: Certificate) -> bool:
    """True once a certificate has reached its holder.

    Same definition the roster-removal guard uses: the certificate was emailed
    (``sent_at``) or the holder pulled it from the public verification portal
    (``downloaded_at``). Those are the documents somebody is relying on, and the
    ones the retention commitment is about.
    """
    return certificate.sent_at is not None or certificate.downloaded_at is not None


def retained_until(event: TrainingEvent, certificates: list[Certificate]) -> date:
    """The first date on which an event's records may be destroyed.

    The attestation runs the clock from the training event's date. Certificates
    are sometimes issued weeks later, so the anchor is the later of the event
    date and the newest issue date -- retention is a floor, and rounding it up
    is the safe direction.
    """
    anchor = event.event_date
    for certificate in certificates:
        issued_on = certificate.generated_at
        if issued_on is None:
            continue
        if isinstance(issued_on, datetime):
            issued_on = issued_on.date()
        anchor = max(anchor, issued_on)
    return _add_years(anchor, settings.retention_years)


@dataclass(frozen=True)
class RetentionBlock:
    """Why an event may not be deleted yet, in terms an admin can act on."""

    certificates: int
    retained_until: date

    @property
    def message(self) -> str:
        return (
            f"This event has {self.certificates} issued certificate"
            f"{'s' if self.certificates != 1 else ''} that must be kept for "
            f"{settings.retention_years} years under our CEU record-retention commitment. "
            f"Deleting the event would destroy them. It can be deleted on or after "
            f"{self.retained_until.isoformat()}. To take the event out of use now, "
            f"remove attendees who have no issued certificate, or ask an administrator "
            f"to run the retention purge once the period has elapsed."
        )


def retention_block(db: Session, event: TrainingEvent, today: date | None = None) -> RetentionBlock | None:
    """None when the event is safe to delete, otherwise why it is not.

    An event with no issued certificate carries no retention obligation (a
    draft, a cancelled session, a mistake) and stays freely deletable.
    """
    today = today or date.today()
    certificates = _event_certificates(db, event.id)
    issued = [certificate for certificate in certificates if is_issued(certificate)]
    if not issued:
        return None
    deletable_on = retained_until(event, issued)
    if today >= deletable_on:
        return None
    return RetentionBlock(certificates=len(issued), retained_until=deletable_on)


def _event_certificates(db: Session, event_id: int) -> list[Certificate]:
    return list(
        db.scalars(
            select(Certificate).join(EventAttendee).where(EventAttendee.event_id == event_id)
        )
    )


@dataclass
class PurgedEvent:
    """What one event contributed to a purge (also the audit payload)."""

    event_id: int
    title: str
    event_date: date
    retained_until: date
    attendees: int
    certificates: int
    certificates_issued: int

    def as_details(self) -> dict:
        return {
            "title": self.title,
            "event_date": self.event_date.isoformat(),
            "retained_until": self.retained_until.isoformat(),
            "attendees": self.attendees,
            "certificates": self.certificates,
            "certificates_issued": self.certificates_issued,
            "retention_years": settings.retention_years,
        }


@dataclass
class PurgeReport:
    """Outcome of a purge run. ``dry_run`` is the default and changes nothing."""

    dry_run: bool
    run_on: date
    retention_years: int
    events: list[PurgedEvent] = field(default_factory=list)

    @property
    def event_count(self) -> int:
        return len(self.events)

    @property
    def certificate_count(self) -> int:
        return sum(entry.certificates for entry in self.events)

    @property
    def attendee_link_count(self) -> int:
        return sum(entry.attendees for entry in self.events)

    def describe(self) -> str:
        header = (
            f"{'[DRY RUN] would purge' if self.dry_run else 'Purged'} "
            f"{self.event_count} event(s), {self.attendee_link_count} attendee record(s) and "
            f"{self.certificate_count} certificate(s) past the "
            f"{self.retention_years}-year retention period (as of {self.run_on.isoformat()})."
        )
        lines = [header]
        for entry in self.events:
            lines.append(
                f"  - event {entry.event_id} {entry.title!r} "
                f"({entry.event_date.isoformat()}, retained until {entry.retained_until.isoformat()}): "
                f"{entry.attendees} attendee record(s), {entry.certificates} certificate(s)"
            )
        if self.dry_run:
            lines.append("Nothing was deleted. Re-run with --apply to delete these records.")
        return "\n".join(lines)


def find_expired_events(db: Session, today: date | None = None) -> list[tuple[TrainingEvent, list[Certificate]]]:
    """Events whose entire retention window has elapsed, with their certificates.

    Only events dated at least ``retention_years`` ago are considered at all;
    each surviving candidate is then re-checked against its certificates' issue
    dates, so a certificate issued late keeps its event alive.
    """
    today = today or date.today()
    cutoff = _add_years(today, -settings.retention_years)
    candidates = list(
        db.scalars(
            select(TrainingEvent)
            .where(TrainingEvent.event_date <= cutoff)
            .order_by(TrainingEvent.event_date)
        )
    )
    expired: list[tuple[TrainingEvent, list[Certificate]]] = []
    for event in candidates:
        certificates = _event_certificates(db, event.id)
        if today >= retained_until(event, certificates):
            expired.append((event, certificates))
    return expired


def purge_expired(
    db: Session,
    *,
    apply: bool = False,
    actor: User | None = None,
    today: date | None = None,
) -> PurgeReport:
    """Delete records past the retention period. Dry run unless apply=True.

    Every purge is logged and, when applied, written to the audit trail. The
    audit row outlives the event it describes (its event FK is SET NULL), so the
    fact that a record existed and was destroyed under the retention policy is
    itself retained.
    """
    today = today or date.today()
    report = PurgeReport(dry_run=not apply, run_on=today, retention_years=settings.retention_years)
    expired = find_expired_events(db, today)

    pdf_paths: list[str] = []
    for event, certificates in expired:
        attendee_count = len(
            list(db.scalars(select(EventAttendee.id).where(EventAttendee.event_id == event.id)))
        )
        entry = PurgedEvent(
            event_id=event.id,
            title=event.title,
            event_date=event.event_date,
            retained_until=retained_until(event, certificates),
            attendees=attendee_count,
            certificates=len(certificates),
            certificates_issued=sum(1 for certificate in certificates if is_issued(certificate)),
        )
        report.events.append(entry)
        if not apply:
            continue
        record_audit(
            db, "retention.purged", "training_event", event.id, actor, event.id, entry.as_details()
        )
        pdf_paths.extend(certificate.pdf_path for certificate in certificates)
        # Certificates go first for the same reason as in the delete-event
        # route: their link relationship carries no ORM delete cascade, so the
        # ORM would otherwise try to NULL a non-nullable FK.
        for certificate in certificates:
            db.delete(certificate)
        db.flush()
        db.delete(event)

    if apply:
        db.commit()
        # File cleanup after the transaction commits: local disk and, when
        # configured, the Supabase Storage bucket.
        for raw_path in pdf_paths:
            storage.delete_file(Path(raw_path))
        for entry in report.events:
            storage.delete_prefix(f"uploads/{entry.event_id}")
            storage.delete_prefix(f"certificates/templates/{entry.event_id}")

    logger.log(logging.INFO if report.events else logging.DEBUG, "%s", report.describe())
    return report


def main(argv: list[str] | None = None) -> int:
    """Operator entrypoint: ``python -m app.services.retention [--apply]``."""
    parser = argparse.ArgumentParser(
        prog="python -m app.services.retention",
        description=(
            "Purge training-event records past the configured retention period "
            f"(currently {settings.retention_years} years). Dry run by default."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete the records. Without this flag nothing is changed.",
    )
    parser.add_argument(
        "--as-of",
        metavar="YYYY-MM-DD",
        help="Evaluate retention as of this date instead of today (for rehearsing a run).",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    as_of = date.fromisoformat(args.as_of) if args.as_of else datetime.now(timezone.utc).date()
    # Imported here so the module stays importable (and testable) without
    # opening a database connection.
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        report = purge_expired(db, apply=args.apply, today=as_of)
    finally:
        db.close()
    print(report.describe())
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
