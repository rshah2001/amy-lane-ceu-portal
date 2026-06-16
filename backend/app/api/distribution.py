from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user
from app.api.events import get_visible_event
from app.db.session import get_db
from app.models.event_attendee import EventAttendee
from app.models.user import User
from app.schemas.common import DistributionResult
from app.services.audit import record_audit
from app.services.emailer import send_invite_email
from app.services.identity import is_valid_email

router = APIRouter(prefix="/events/{event_id}/distribute", tags=["Distribution"])


@router.post("", response_model=DistributionResult)
def distribute(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DistributionResult:
    event = get_visible_event(db, event_id, current_user)
    links = list(
        db.scalars(
            select(EventAttendee)
            .options(joinedload(EventAttendee.attendee))
            .where(EventAttendee.event_id == event_id, EventAttendee.registered.is_(True))
            .order_by(EventAttendee.id)
        ).unique()
    )
    sent = 0
    skipped: list[str] = []
    failed: list[str] = []
    for link in links:
        email = link.attendee.email
        if not is_valid_email(email):
            skipped.append(f"{link.attendee.full_name} (no valid email)")
            continue
        try:
            send_invite_email(event, link.attendee.full_name, email)
            link.invite_sent_at = datetime.now(timezone.utc)
            sent += 1
        except Exception as exc:  # noqa: BLE001 - report any delivery failure per attendee
            failed.append(f"{link.attendee.full_name}: {exc}")
    record_audit(
        db,
        "event.distributed",
        "training_event",
        event.id,
        current_user,
        event.id,
        {"sent": sent, "skipped": len(skipped), "failed": len(failed)},
    )
    db.commit()
    return DistributionResult(sent=sent, skipped=skipped, failed=failed)
