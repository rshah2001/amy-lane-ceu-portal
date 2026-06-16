from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.models.certificate import Certificate
from app.models.event_attendee import EventAttendee
from app.schemas.common import VerificationOut
from app.services.audit import record_audit
from app.services.compliance import lifecycle_status

router = APIRouter(prefix="/public/verify", tags=["Verification"])


def _load(db: Session, certificate_number: str) -> Certificate | None:
    return db.scalar(
        select(Certificate)
        .options(
            joinedload(Certificate.event_attendee).joinedload(EventAttendee.attendee),
            joinedload(Certificate.event_attendee).joinedload(EventAttendee.event),
        )
        .where(Certificate.certificate_number == certificate_number.strip())
    )


@router.get("/{certificate_number}", response_model=VerificationOut)
def verify_certificate(certificate_number: str, db: Session = Depends(get_db)) -> VerificationOut:
    certificate = _load(db, certificate_number)
    if not certificate:
        return VerificationOut(valid=False)
    link = certificate.event_attendee
    event = link.event
    return VerificationOut(
        valid=True,
        certificate_number=certificate.certificate_number,
        attendee_name=link.attendee.full_name,
        event_title=event.title,
        event_date=event.event_date,
        ceu_hours=event.ceu_hours,
        course_instructor=event.course_instructor or event.presenter_name,
        generated_at=certificate.generated_at,
        status=lifecycle_status(link),
    )


@router.get("/{certificate_number}/download")
def download_verified_certificate(
    certificate_number: str, db: Session = Depends(get_db)
) -> FileResponse:
    certificate = _load(db, certificate_number)
    if not certificate or not Path(certificate.pdf_path).exists():
        raise HTTPException(status_code=404, detail="Certificate not found")
    # First public fetch marks the certificate as downloaded (truthful lifecycle).
    if not certificate.downloaded_at:
        certificate.downloaded_at = datetime.now(timezone.utc)
        record_audit(
            db,
            "certificate.downloaded",
            "certificate",
            certificate.id,
            None,
            certificate.event_attendee.event_id,
        )
        db.commit()
    return FileResponse(
        certificate.pdf_path,
        media_type="application/pdf",
        filename=f"{certificate.certificate_number}.pdf",
    )
