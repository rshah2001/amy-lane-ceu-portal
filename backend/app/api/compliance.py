from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, require_admin
from app.api.events import get_visible_event
from app.db.session import get_db
from app.models.attendee import Attendee
from app.models.event_attendee import EventAttendee
from app.models.user import User
from app.schemas.common import ApprovalRequest, ComplianceRow
from app.services.audit import record_audit
from app.services.compliance import lifecycle_status, recalculate_event

router = APIRouter(prefix="/events/{event_id}/compliance", tags=["Compliance"])


def serialize_link(link: EventAttendee) -> ComplianceRow:
    certificate = link.certificate
    return ComplianceRow(
        id=link.id,
        attendee_id=link.attendee_id,
        full_name=link.attendee.full_name,
        email=link.attendee.email,
        company=link.attendee.company,
        registered=link.registered,
        attended=link.attended,
        test_completed=link.test_completed,
        test_score=float(link.test_score) if link.test_score is not None else None,
        survey_completed=link.survey_completed,
        has_valid_email=link.has_valid_email,
        eligible=link.eligible,
        approved=link.approved,
        compliance_status=link.compliance_status,
        lifecycle_status=lifecycle_status(link),
        eligibility_reasons=link.eligibility_reasons,
        certificate_id=certificate.id if certificate else None,
        certificate_number=certificate.certificate_number if certificate else None,
        certificate_sent_at=certificate.sent_at if certificate else None,
        certificate_downloaded_at=certificate.downloaded_at if certificate else None,
    )


@router.get("", response_model=list[ComplianceRow])
def review_compliance(
    event_id: int,
    eligibility: str | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ComplianceRow]:
    get_visible_event(db, event_id, current_user)
    recalculate_event(db, event_id)
    db.commit()
    query = (
        select(EventAttendee)
        .options(
            joinedload(EventAttendee.attendee),
            joinedload(EventAttendee.certificate),
        )
        .where(EventAttendee.event_id == event_id)
    )
    if eligibility == "eligible":
        query = query.where(EventAttendee.eligible.is_(True))
    elif eligibility == "ineligible":
        query = query.where(EventAttendee.eligible.is_(False))
    if search:
        query = query.join(Attendee).where(
            (Attendee.full_name.ilike(f"%{search}%")) | (Attendee.email.ilike(f"%{search}%"))
        )
    links = db.scalars(query.order_by(EventAttendee.id)).unique()
    return [serialize_link(link) for link in links]


@router.post("/approve", response_model=list[ComplianceRow])
def approve_attendees(
    event_id: int,
    payload: ApprovalRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> list[ComplianceRow]:
    get_visible_event(db, event_id, current_user)
    links = list(
        db.scalars(
            select(EventAttendee)
            .options(joinedload(EventAttendee.attendee), joinedload(EventAttendee.certificate))
            .where(
                EventAttendee.event_id == event_id,
                EventAttendee.id.in_(payload.event_attendee_ids),
            )
        ).unique()
    )
    if len(links) != len(set(payload.event_attendee_ids)):
        raise HTTPException(status_code=404, detail="One or more attendees were not found")
    for link in links:
        overridden = payload.approved and not link.eligible
        if overridden and not payload.override:
            raise HTTPException(
                status_code=409,
                detail=f"{link.attendee.full_name} is not eligible and cannot be approved",
            )
        link.approved = payload.approved
        link.approved_by_id = current_user.id if payload.approved else None
        link.approved_at = datetime.now(timezone.utc) if payload.approved else None
        link.compliance_status = "approved" if payload.approved else "eligible"
        record_audit(
            db,
            "attendee.approved_override" if overridden else
            "attendee.approved" if payload.approved else "attendee.approval_revoked",
            "event_attendee",
            link.id,
            current_user,
            event_id,
            {"waived_requirements": link.eligibility_reasons} if overridden else None,
        )
    db.commit()
    return [serialize_link(link) for link in links]

