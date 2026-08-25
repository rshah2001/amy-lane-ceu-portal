"""Delete every training event and its records, to start the portal fresh.

This is a **demo-data reset**, not the retention purge. ``services/retention.py``
deliberately refuses to destroy an issued certificate inside its retention
window, and the DELETE-event route enforces that refusal. This script bypasses
that guard, so it exists on the following terms:

- It is operator-invoked and a dry run unless ``--apply`` is passed, the same
  shape as ``purge_expired``.
- It requires ``--reason`` and writes it to the audit trail. Audit rows outlive
  the events they describe (their event FK is ``SET NULL``), so the fact that
  records existed and were destroyed outside the retention policy is itself
  retained, with the operator's stated justification attached.
- It reports exactly how many issued certificates it is about to destroy, and
  refuses to touch them without ``--force`` once any are found.

Use it only while the portal holds demo data. The moment a certificate has gone
to a real attendee, deleting it makes the claims in
``docs/data-storage-and-retention-confirmation.md`` untrue for that record.

    .venv/bin/python -m scripts.reset_demo_data --reason "pre-launch demo reset"
    .venv/bin/python -m scripts.reset_demo_data --reason "..." --force --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import func, select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.attendee import Attendee
from app.models.certificate import Certificate
from app.models.event_attendee import EventAttendee
from app.models.training_event import TrainingEvent
from app.models.user import User
from app.services import storage
from app.services.audit import record_audit
from app.services.retention import is_issued


def _actor(db, email: str | None) -> User | None:
    if not email:
        return None
    actor = db.scalar(select(User).where(User.email == email))
    if actor is None:
        sys.exit(f"No user with email {email!r}; pass an existing admin or omit --actor.")
    return actor


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--apply", action="store_true", help="Actually delete. Without it, this is a dry run."
    )
    parser.add_argument("--reason", required=True, help="Why, recorded in the audit trail.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Proceed even though certificates have already reached their holders.",
    )
    parser.add_argument(
        "--attendees",
        action="store_true",
        help="Also empty the global attendee directory (people, not event links).",
    )
    parser.add_argument("--actor", help="Email of the admin to attribute the deletion to.")
    args = parser.parse_args()

    with SessionLocal() as db:
        actor = _actor(db, args.actor)
        events = list(db.scalars(select(TrainingEvent).order_by(TrainingEvent.id)))
        if not events:
            print("No events; nothing to reset.")
            return 0

        planned = []
        for event in events:
            certificates = list(
                db.scalars(
                    select(Certificate)
                    .join(EventAttendee)
                    .where(EventAttendee.event_id == event.id)
                )
            )
            attendees = (
                db.scalar(
                    select(func.count(EventAttendee.id)).where(EventAttendee.event_id == event.id)
                )
                or 0
            )
            planned.append(
                (event, certificates, attendees, sum(1 for c in certificates if is_issued(c)))
            )

        total_certificates = sum(len(c) for _, c, _, _ in planned)
        total_issued = sum(issued for _, _, _, issued in planned)

        print(f"Database: {settings.database_url.split('@')[-1]}")
        print(f"{'DELETING' if args.apply else 'WOULD DELETE'} {len(planned)} event(s):\n")
        for event, certificates, attendees, issued in planned:
            print(
                f"  #{event.id:<4} {event.title[:44]:<46} {event.event_date}  "
                f"attendees={attendees:<4} certificates={len(certificates):<4} issued={issued}"
            )
        print(
            f"\n  totals: {total_certificates} certificate(s), "
            f"{total_issued} already issued to a holder"
        )

        if total_issued and not args.force:
            print(
                f"\nRefusing: {total_issued} certificate(s) have been emailed or downloaded and "
                f"are inside the {settings.retention_years}-year retention commitment.\n"
                "If these are demo records, re-run with --force.",
                file=sys.stderr,
            )
            return 1

        if not args.apply:
            print("\nDry run. Re-run with --apply to delete.")
            return 0

        pdf_paths: list[str] = []
        event_ids: list[int] = []
        for event, certificates, attendees, issued in planned:
            record_audit(
                db,
                "demo_reset.event_deleted",
                "training_event",
                event.id,
                actor,
                event.id,
                {
                    "title": event.title,
                    "event_date": event.event_date.isoformat(),
                    "attendees": attendees,
                    "certificates": len(certificates),
                    "certificates_issued": issued,
                    # The whole point of the audit row: this deletion was not
                    # authorised by the retention policy, it overrode it.
                    "retention_override": bool(issued),
                    "reason": args.reason,
                },
            )
            pdf_paths.extend(c.pdf_path for c in certificates if c.pdf_path)
            event_ids.append(event.id)
            # Certificates first: their link relationship carries no ORM delete
            # cascade, so the ORM would otherwise try to NULL a non-nullable FK.
            for certificate in certificates:
                db.delete(certificate)
            db.flush()
            db.delete(event)

        removed_attendees = 0
        if args.attendees:
            directory = list(db.scalars(select(Attendee)))
            removed_attendees = len(directory)
            for attendee in directory:
                db.delete(attendee)

        db.commit()

        # Best-effort file cleanup, after the transaction commits.
        for raw_path in pdf_paths:
            storage.delete_file(Path(raw_path))
        for event_id in event_ids:
            storage.delete_prefix(f"uploads/{event_id}")
            storage.delete_prefix(f"certificates/templates/{event_id}")

        print(f"\nDeleted {len(planned)} event(s) and {total_certificates} certificate(s).")
        if args.attendees:
            print(f"Emptied the attendee directory ({removed_attendees} person record(s)).")
        print("Audit rows for each deletion were kept.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
