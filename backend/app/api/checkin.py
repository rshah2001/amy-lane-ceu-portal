import io
from datetime import datetime, timezone

import qrcode
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.events import get_visible_event
from app.core.config import settings
from app.db.session import get_db
from app.models.training_event import TrainingEvent
from app.models.user import User
from app.schemas.common import PublicCheckinOut, PublicCheckinSubmission
from app.services.attendee_match import get_or_create_link, match_or_create_attendee
from app.services.audit import record_audit
from app.services.compliance import recalculate_event

router = APIRouter(tags=["Check-in"])


def get_checkin_event(db: Session, token: str) -> TrainingEvent:
    event = db.scalar(select(TrainingEvent).where(TrainingEvent.checkin_token == token))
    if not event:
        raise HTTPException(status_code=404, detail="Check-in link not found")
    return event


@router.get("/public/checkin/{token}", response_model=PublicCheckinOut)
def public_checkin(token: str, db: Session = Depends(get_db)) -> PublicCheckinOut:
    event = get_checkin_event(db, token)
    return PublicCheckinOut(
        event_title=event.title,
        event_date=event.event_date,
        presenter_name=event.presenter_name,
        location=event.location,
    )


@router.post("/public/checkin/{token}")
def submit_checkin(
    token: str,
    payload: PublicCheckinSubmission,
    db: Session = Depends(get_db),
) -> dict:
    """Self-service attendance: an attendee scans the QR (or opens the link) and
    records their own attendance — works for online or in-person events."""
    event = get_checkin_event(db, token)
    attendee = match_or_create_attendee(db, payload.full_name, str(payload.email))
    link = get_or_create_link(db, event.id, attendee.id)
    link.registered = True
    link.attended = True
    link.checked_in_at = datetime.now(timezone.utc)
    recalculate_event(db, event.id)
    record_audit(
        db,
        "attendee.checked_in",
        "event_attendee",
        link.id,
        None,
        event.id,
        {"attendee_id": attendee.id},
    )
    db.commit()
    return {"status": "checked_in"}


@router.get("/events/{event_id}/checkin-qr")
def checkin_qr(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    event = get_visible_event(db, event_id, current_user)
    if not event.checkin_token:
        raise HTTPException(status_code=409, detail="This event has no check-in link yet")
    url = f"{settings.public_frontend_url}/?checkin={event.checkin_token}"
    image = qrcode.make(url)
    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return StreamingResponse(output, media_type="image/png")
