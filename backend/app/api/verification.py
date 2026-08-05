from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.rate_limit import PublicRateLimit, public_verify_limiter
from app.db.session import get_db
from app.models.certificate import Certificate
from app.models.event_attendee import EventAttendee
from app.schemas.common import VerificationOut
from app.services import storage
from app.services.audit import record_audit
from app.services.compliance import lifecycle_status

router = APIRouter(prefix="/public/verify", tags=["Verification"])

# Both routes are unauthenticated on purpose — "is this certificate real?" has
# to work for an employer or an auditor holding nothing but a printed number.
# That also means anyone can walk certificate numbers, so both are budgeted per
# caller IP + certificate number.
verify_rate_limit = PublicRateLimit("verify", "certificate_number", limiter=public_verify_limiter)


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
def verify_certificate(
    certificate_number: str,
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(verify_rate_limit),
) -> VerificationOut:
    """Read-only certificate lookup.

    This route must never write: an anonymous lookup is not evidence that the
    holder received anything, and ``downloaded_at`` is load-bearing elsewhere
    (it marks a certificate as issued, which blocks routine roster removal and
    drives the lifecycle status). Only the download route below, which actually
    hands over the PDF, may set it.
    """
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
    certificate_number: str,
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(verify_rate_limit),
) -> FileResponse:
    certificate = _load(db, certificate_number)
    if not certificate:
        raise HTTPException(status_code=404, detail="Certificate not found")
    path = Path(certificate.pdf_path)
    if not storage.ensure_local(path):
        # Deliberately no re-render here. Rebuilding a PDF is orders of
        # magnitude more expensive than serving one, so an anonymous caller who
        # can trigger it has a cheap CPU sink. Restoring from the storage
        # backend (above) covers the ephemeral-disk case; when even that misses,
        # an admin re-issues it from the authenticated certificate routes, which
        # still regenerate on demand.
        raise HTTPException(
            status_code=409,
            detail="This certificate file is temporarily unavailable. "
            "Contact the issuing organization for a copy.",
        )
    # Only a genuine handover of the PDF counts as a download.
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
        path,
        media_type="application/pdf",
        filename=f"{certificate.certificate_number}.pdf",
    )
