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
    # Hand the attendee straight to their next step so they don't retype
    # their name: internal links carry tokens, external modes carry the URL.
    next_steps: dict[str, str] = {}
    if event.test_mode == "internal" and event.test_token and event.test_questions:
        next_steps["test_token"] = event.test_token
    elif event.test_mode == "external" and event.post_test_url:
        next_steps["post_test_url"] = event.post_test_url
    if event.survey_mode == "internal" and event.survey_token:
        next_steps["survey_token"] = event.survey_token
    elif event.survey_mode == "external" and event.external_survey_url:
        next_steps["external_survey_url"] = event.external_survey_url
    return {"status": "checked_in", **next_steps}


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


def _event_qr_links(event: TrainingEvent) -> list[tuple[str, str]]:
    """The public links an attendee needs during a session, in slide order."""
    links: list[tuple[str, str]] = []
    if event.checkin_token:
        links.append(("Check in", f"{settings.public_frontend_url}/?checkin={event.checkin_token}"))
    if event.test_mode == "internal" and event.test_token and event.test_questions:
        links.append(("Post-test", f"{settings.public_frontend_url}/?test={event.test_token}"))
    elif event.test_mode == "external" and event.post_test_url:
        links.append(("Post-test", event.post_test_url))
    if event.survey_mode == "internal" and event.survey_token:
        links.append(("Feedback survey", f"{settings.public_frontend_url}/?survey={event.survey_token}"))
    elif event.survey_mode == "external" and event.external_survey_url:
        links.append(("Feedback survey", event.external_survey_url))
    return links


@router.get("/events/{event_id}/qr-sheet")
def qr_sheet(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """One printable PDF with every QR the presenter needs on a slide:
    check-in, post-test, and survey, side by side with labels."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas as pdf_canvas

    event = get_visible_event(db, event_id, current_user)
    links = _event_qr_links(event)
    if not links:
        raise HTTPException(status_code=409, detail="This event has no shareable links yet")

    output = io.BytesIO()
    page = pdf_canvas.Canvas(output, pagesize=letter)
    width, height = letter

    title = event.title if len(event.title) <= 60 else f"{event.title[:57]}..."
    page.setFont("Helvetica-Bold", 22)
    page.drawCentredString(width / 2, height - 72, title)
    subtitle = event.event_date.strftime("%B %-d, %Y")
    if event.presenter_name:
        subtitle += f"  •  {event.presenter_name}"
    page.setFont("Helvetica", 12)
    page.drawCentredString(width / 2, height - 94, subtitle)

    margin = 40.0
    block_width = (width - 2 * margin) / len(links)
    qr_size = min(block_width - 24, 190.0)
    label_y = height - 170
    for index, (label, url) in enumerate(links):
        center_x = margin + block_width * index + block_width / 2
        page.setFont("Helvetica-Bold", 15)
        page.drawCentredString(center_x, label_y, label)
        qr_png = io.BytesIO()
        qrcode.make(url).save(qr_png, format="PNG")
        qr_png.seek(0)
        page.drawImage(
            ImageReader(qr_png),
            center_x - qr_size / 2,
            label_y - 16 - qr_size,
            qr_size,
            qr_size,
        )
        # Truncate the caption to its own column so neighbours never collide.
        caption = url
        max_caption_width = block_width - 12
        while caption and stringWidth(f"{caption}...", "Helvetica", 6.5) > max_caption_width:
            caption = caption[:-1]
        page.setFont("Helvetica", 6.5)
        page.drawCentredString(
            center_x, label_y - 26 - qr_size, caption if caption == url else f"{caption}..."
        )

    page.setFont("Helvetica-Oblique", 12)
    page.drawCentredString(
        width / 2, label_y - 70 - qr_size, "Scan with your phone camera to open each step."
    )
    page.showPage()
    page.save()
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="event-qr-sheet.pdf"'},
    )
