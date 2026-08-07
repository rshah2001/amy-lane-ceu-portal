from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user
from app.api.events import get_visible_event
from app.db.session import get_db
from app.models.event_attendee import EventAttendee
from app.models.user import User
from app.services.audit import record_audit
from app.services.emailer import send_invite_email
from app.services.identity import is_valid_email

router = APIRouter(prefix="/events/{event_id}/distribute", tags=["Distribution"])

NO_EMAIL_REASON = "No valid email address on file for this attendee"

# How many per-recipient problems the audit entry keeps verbatim. The response
# always carries every recipient; the audit log only needs enough to know what
# went wrong on a 500-person event without storing a novel per distribution.
MAX_AUDITED_PROBLEMS = 50


# These live here rather than in app.schemas.common because they describe this
# one endpoint's report and nothing else reads them.
class DistributionRecipient(BaseModel):
    """One attendee's outcome, so the UI can say who and why, not just how many.

    ``retryable`` separates the two kinds of problem: a delivery failure is
    worth pressing "retry" on, a missing address is not -- that one needs the
    roster fixed first, and retrying it forever would never send anything.
    """

    link_id: int
    attendee_id: int
    full_name: str
    email: str | None
    status: Literal["sent", "skipped", "failed"]
    reason: str | None = None
    retryable: bool = False


class DistributionReport(BaseModel):
    total: int
    sent: int
    skipped: int
    failed: int
    recipients: list[DistributionRecipient]


@router.post("", response_model=DistributionReport)
def distribute(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DistributionReport:
    event = get_visible_event(db, event_id, current_user)
    links = list(
        db.scalars(
            select(EventAttendee)
            .options(joinedload(EventAttendee.attendee))
            .where(EventAttendee.event_id == event_id, EventAttendee.registered.is_(True))
            .order_by(EventAttendee.id)
        ).unique()
    )
    recipients: list[DistributionRecipient] = []
    for link in links:
        email = link.attendee.email
        outcome = DistributionRecipient(
            link_id=link.id,
            attendee_id=link.attendee_id,
            full_name=link.attendee.full_name,
            email=email,
            status="sent",
        )
        if not is_valid_email(email):
            outcome.status = "skipped"
            outcome.reason = NO_EMAIL_REASON
        else:
            try:
                send_invite_email(event, link.attendee.full_name, email)
                link.invite_sent_at = datetime.now(timezone.utc)
            except Exception as exc:  # noqa: BLE001 - report any delivery failure per attendee
                outcome.status = "failed"
                outcome.reason = str(exc)
                outcome.retryable = True
        recipients.append(outcome)

    counts = {status: 0 for status in ("sent", "skipped", "failed")}
    for outcome in recipients:
        counts[outcome.status] += 1
    problems = [outcome for outcome in recipients if outcome.status != "sent"]
    record_audit(
        db,
        "event.distributed",
        "training_event",
        event.id,
        current_user,
        event.id,
        {
            **counts,
            "total": len(recipients),
            # The reasons, not just the tally: a distribution that mailed
            # nobody has to be explainable after the fact.
            "problems": [
                {
                    "attendee_id": outcome.attendee_id,
                    "full_name": outcome.full_name,
                    "status": outcome.status,
                    "reason": outcome.reason,
                }
                for outcome in problems[:MAX_AUDITED_PROBLEMS]
            ],
            "problems_truncated": max(0, len(problems) - MAX_AUDITED_PROBLEMS),
        },
    )
    db.commit()
    return DistributionReport(total=len(recipients), **counts, recipients=recipients)
