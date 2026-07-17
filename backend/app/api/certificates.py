from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import require_admin
from app.core.config import settings
from app.api.events import get_visible_event
from app.db.session import get_db
from app.models.certificate import Certificate
from app.models.certificate_email_log import CertificateEmailLog
from app.models.event_attendee import EventAttendee
from app.models.training_event import TrainingEvent
from app.models.user import User
from app.schemas.common import BulkActionResult, CertificateOut, ManualIssueRequest
from app.services.attendee_match import get_or_create_link, match_or_create_attendee
from app.services.audit import record_audit
from app.services.certificates import certificate_snapshot, generate_certificate_pdf, make_certificate_number
from app.services.compliance import recalculate_event
from app.services.csv_import import save_upload
from app.services.emailer import send_certificate_email
from app.services import storage

router = APIRouter(prefix="/events/{event_id}/certificates", tags=["Certificates"])
TEMPLATE_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg"}


def get_link(db: Session, event_id: int, link_id: int) -> EventAttendee:
    link = db.scalar(
        select(EventAttendee)
        .options(
            joinedload(EventAttendee.attendee),
            joinedload(EventAttendee.event),
            joinedload(EventAttendee.certificate),
        )
        .where(EventAttendee.event_id == event_id, EventAttendee.id == link_id)
    )
    if not link:
        raise HTTPException(status_code=404, detail="Event attendee not found")
    return link


def maybe_mark_event_completed(db: Session, event: TrainingEvent, current_user: User) -> bool:
    """Flip the event to "completed" once every approved attendee's certificate
    has been sent. Approved-but-ungenerated and generated-but-unsent
    certificates both block completion. Never un-completes: attendees added to
    a completed event later (e.g. a manual issue) leave the status alone.
    Adds the status change and an audit row to the session; the caller commits.
    """
    if event.status == "completed":
        return False
    # The session runs with autoflush=False; push pending sent_at updates to
    # the DB so the counts below see the sends from this request.
    db.flush()
    approved_count = db.scalar(
        select(func.count(EventAttendee.id)).where(
            EventAttendee.event_id == event.id,
            EventAttendee.approved.is_(True),
        )
    )
    if not approved_count:
        return False
    unsent_count = db.scalar(
        select(func.count(EventAttendee.id))
        .outerjoin(Certificate, Certificate.event_attendee_id == EventAttendee.id)
        .where(
            EventAttendee.event_id == event.id,
            EventAttendee.approved.is_(True),
            or_(Certificate.id.is_(None), Certificate.sent_at.is_(None)),
        )
    )
    if unsent_count:
        return False
    event.status = "completed"
    record_audit(
        db,
        "event.completed",
        "training_event",
        event.id,
        current_user,
        event.id,
        {"trigger": "all_certificates_sent"},
    )
    return True


def ensure_pdf(link: EventAttendee, certificate: Certificate) -> Path:
    # The free-tier host has an ephemeral disk, so a generated cert PDF can
    # disappear on redeploy while its DB row persists. First try to restore it
    # from the storage backend (Supabase, when configured); otherwise re-create
    # it from the same immutable data (identical output) so send/download work.
    path = Path(certificate.pdf_path)
    if not storage.ensure_local(path):
        generate_certificate_pdf(link, certificate.certificate_number, output_path=path)
    return path


@router.get("", response_model=list[CertificateOut])
def list_certificates(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> list[Certificate]:
    get_visible_event(db, event_id, current_user)
    return list(
        db.scalars(
            select(Certificate)
            .join(EventAttendee)
            .where(EventAttendee.event_id == event_id)
            .order_by(Certificate.generated_at.desc())
        )
    )


@router.post("/template")
async def upload_certificate_template(
    event_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict:
    event = get_visible_event(db, event_id, current_user)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in TEMPLATE_SUFFIXES:
        raise HTTPException(status_code=400, detail="Certificate templates must be PDF, PNG, JPG, or JPEG")
    contents = await file.read()
    if len(contents) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Template exceeds the 15 MB limit")
    version = event.certificate_template_version + 1
    destination = (
        settings.certificates_dir
        / "templates"
        / str(event_id)
        / f"template-v{version}{suffix}"
    )
    save_upload(contents, destination)
    event.certificate_template_path = str(destination)
    event.certificate_template_version = version
    event.certificate_template_updated_at = datetime.now(timezone.utc)
    record_audit(
        db,
        "certificate.template_updated",
        "training_event",
        event.id,
        current_user,
        event.id,
        {"version": version, "filename": file.filename},
    )
    db.commit()
    return {"template_version": version, "filename": file.filename}


@router.get("/{link_id}/preview")
def preview_certificate(
    event_id: int,
    link_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> FileResponse:
    get_visible_event(db, event_id, current_user)
    link = get_link(db, event_id, link_id)
    # Approved covers manually issued / override-approved attendees, who
    # never satisfy the eligibility rules but still get certificates.
    if not (link.eligible or link.approved):
        raise HTTPException(status_code=409, detail="Only eligible or approved attendees can be previewed")
    preview_path = settings.certificates_dir / "previews" / f"{uuid4().hex}.pdf"
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    generate_certificate_pdf(link, "PREVIEW", output_path=preview_path, preview=True)
    return FileResponse(
        preview_path,
        media_type="application/pdf",
        filename=f"{link.attendee.full_name}-certificate-preview.pdf",
    )


@router.post("/{link_id}/generate", response_model=CertificateOut)
def generate_certificate(
    event_id: int,
    link_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Certificate:
    get_visible_event(db, event_id, current_user)
    link = get_link(db, event_id, link_id)
    if not link.approved:
        raise HTTPException(status_code=409, detail="Attendee must be approved first")
    if link.certificate:
        return link.certificate
    number = make_certificate_number(event_id)
    path = generate_certificate_pdf(link, number)
    certificate = Certificate(
        event_attendee_id=link.id,
        certificate_number=number,
        pdf_path=str(path),
        generated_by_id=current_user.id,
        template_version=link.event.certificate_template_version,
        event_snapshot=certificate_snapshot(link),
    )
    db.add(certificate)
    db.flush()
    record_audit(
        db,
        "certificate.generated",
        "certificate",
        certificate.id,
        current_user,
        event_id,
        {"certificate_number": number},
    )
    db.commit()
    db.refresh(certificate)
    return certificate


@router.post("/{link_id}/send", response_model=CertificateOut)
def send_certificate(
    event_id: int,
    link_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Certificate:
    event = get_visible_event(db, event_id, current_user)
    link = get_link(db, event_id, link_id)
    certificate = link.certificate
    if not certificate:
        raise HTTPException(status_code=409, detail="Generate the certificate first")
    if not link.attendee.email:
        raise HTTPException(status_code=409, detail="Attendee has no email address")
    try:
        message_id = send_certificate_email(
            link.attendee.email,
            link.attendee.full_name,
            link.event.title,
            ensure_pdf(link, certificate),
        )
        log = CertificateEmailLog(
            certificate_id=certificate.id,
            recipient_email=link.attendee.email,
            status="sent",
            provider_message_id=message_id,
        )
        certificate.sent_at = datetime.now(timezone.utc)
        certificate.last_sent_to = link.attendee.email
    except Exception as exc:
        log = CertificateEmailLog(
            certificate_id=certificate.id,
            recipient_email=link.attendee.email,
            status="failed",
            error_message=str(exc),
        )
        db.add(log)
        record_audit(
            db,
            "certificate.email_failed",
            "certificate",
            certificate.id,
            current_user,
            event_id,
            {"error": str(exc)},
        )
        db.commit()
        raise HTTPException(status_code=502, detail="Certificate email could not be sent") from exc
    db.add(log)
    record_audit(
        db,
        "certificate.emailed",
        "certificate",
        certificate.id,
        current_user,
        event_id,
        {"recipient": link.attendee.email},
    )
    maybe_mark_event_completed(db, event, current_user)
    db.commit()
    db.refresh(certificate)
    return certificate


@router.post("/issue", response_model=CertificateOut, status_code=201)
def issue_certificate_manually(
    event_id: int,
    payload: ManualIssueRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Certificate:
    """Admin escape hatch: issue a certificate to anyone by name and email,
    bypassing the eligibility rules. The person is added to the event (if not
    already on it), approved, and the manual issue is audited."""
    event = get_visible_event(db, event_id, current_user)
    attendee = match_or_create_attendee(db, event.id, payload.full_name, str(payload.email))
    link = get_or_create_link(db, event.id, attendee.id)
    if not link.approved:
        link.approved = True
        link.approved_by_id = current_user.id
        link.approved_at = datetime.now(timezone.utc)
        link.compliance_status = "approved"
    record_audit(
        db,
        "certificate.manually_issued",
        "event_attendee",
        link.id,
        current_user,
        event_id,
        {
            "attendee": attendee.full_name,
            "email": attendee.email,
            "met_requirements": link.eligible,
            "missing_requirements": link.eligibility_reasons,
        },
    )
    certificate = link.certificate
    if not certificate:
        number = make_certificate_number(event_id)
        path = generate_certificate_pdf(link, number)
        certificate = Certificate(
            event_attendee_id=link.id,
            certificate_number=number,
            pdf_path=str(path),
            generated_by_id=current_user.id,
            template_version=event.certificate_template_version,
            event_snapshot=certificate_snapshot(link),
        )
        db.add(certificate)
        db.flush()
        record_audit(
            db,
            "certificate.generated",
            "certificate",
            certificate.id,
            current_user,
            event_id,
            {"certificate_number": number, "manual_issue": True},
        )
    db.commit()
    db.refresh(certificate)
    if payload.send_email:
        # Reuses the send route's logging/failure handling; a 502 here means
        # the certificate was issued but the email needs a resend.
        return send_certificate(event_id, link.id, db, current_user)
    return certificate


@router.post("/approve-all", response_model=BulkActionResult)
def approve_all_eligible(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> BulkActionResult:
    get_visible_event(db, event_id, current_user)
    recalculate_event(db, event_id)
    links = list(
        db.scalars(
            select(EventAttendee).where(
                EventAttendee.event_id == event_id,
                EventAttendee.eligible.is_(True),
                EventAttendee.approved.is_(False),
            )
        )
    )
    for link in links:
        link.approved = True
        link.approved_by_id = current_user.id
        link.approved_at = datetime.now(timezone.utc)
        link.compliance_status = "approved"
        record_audit(db, "attendee.approved", "event_attendee", link.id, current_user, event_id)
    db.commit()
    return BulkActionResult(action="approve_all", processed=len(links), skipped=0, failed=0)


@router.post("/generate-all", response_model=BulkActionResult)
def generate_all_approved(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> BulkActionResult:
    event = get_visible_event(db, event_id, current_user)
    links = list(
        db.scalars(
            select(EventAttendee)
            .options(joinedload(EventAttendee.attendee), joinedload(EventAttendee.certificate))
            .where(EventAttendee.event_id == event_id, EventAttendee.approved.is_(True))
        ).unique()
    )
    processed = skipped = failed = 0
    details: list[str] = []
    for link in links:
        if link.certificate:
            skipped += 1
            continue
        try:
            number = make_certificate_number(event_id)
            path = generate_certificate_pdf(link, number)
            certificate = Certificate(
                event_attendee_id=link.id,
                certificate_number=number,
                pdf_path=str(path),
                generated_by_id=current_user.id,
                template_version=event.certificate_template_version,
                event_snapshot=certificate_snapshot(link),
            )
            db.add(certificate)
            db.flush()
            record_audit(db, "certificate.generated", "certificate", certificate.id, current_user, event_id, {"certificate_number": number})
            processed += 1
        except Exception as exc:  # noqa: BLE001 - report per-attendee, keep going
            failed += 1
            details.append(f"{link.attendee.full_name}: {exc}")
    db.commit()
    return BulkActionResult(action="generate_all", processed=processed, skipped=skipped, failed=failed, details=details)


@router.post("/send-all", response_model=BulkActionResult)
def send_all_generated(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> BulkActionResult:
    event = get_visible_event(db, event_id, current_user)
    links = list(
        db.scalars(
            select(EventAttendee)
            .options(joinedload(EventAttendee.attendee), joinedload(EventAttendee.event), joinedload(EventAttendee.certificate))
            .where(EventAttendee.event_id == event_id)
        ).unique()
    )
    processed = skipped = failed = 0
    details: list[str] = []
    for link in links:
        certificate = link.certificate
        if not certificate or certificate.sent_at:
            continue
        if not link.attendee.email:
            skipped += 1
            details.append(f"{link.attendee.full_name}: no email")
            continue
        try:
            message_id = send_certificate_email(
                link.attendee.email, link.attendee.full_name, link.event.title, ensure_pdf(link, certificate)
            )
            db.add(CertificateEmailLog(certificate_id=certificate.id, recipient_email=link.attendee.email, status="sent", provider_message_id=message_id))
            certificate.sent_at = datetime.now(timezone.utc)
            certificate.last_sent_to = link.attendee.email
            record_audit(db, "certificate.emailed", "certificate", certificate.id, current_user, event_id, {"recipient": link.attendee.email})
            processed += 1
        except Exception as exc:  # noqa: BLE001 - log failure, continue with the rest
            db.add(CertificateEmailLog(certificate_id=certificate.id, recipient_email=link.attendee.email, status="failed", error_message=str(exc)))
            record_audit(db, "certificate.email_failed", "certificate", certificate.id, current_user, event_id, {"error": str(exc)})
            failed += 1
            details.append(f"{link.attendee.full_name}: {exc}")
    maybe_mark_event_completed(db, event, current_user)
    db.commit()
    return BulkActionResult(action="send_all", processed=processed, skipped=skipped, failed=failed, details=details)


@router.get("/{certificate_id}/download")
def download_certificate(
    event_id: int,
    certificate_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> FileResponse:
    get_visible_event(db, event_id, current_user)
    certificate = db.scalar(
        select(Certificate)
        .options(
            joinedload(Certificate.event_attendee).joinedload(EventAttendee.attendee),
            joinedload(Certificate.event_attendee).joinedload(EventAttendee.event),
        )
        .join(EventAttendee)
        .where(Certificate.id == certificate_id, EventAttendee.event_id == event_id)
    )
    if not certificate:
        raise HTTPException(status_code=404, detail="Certificate not found")
    path = ensure_pdf(certificate.event_attendee, certificate)
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"{certificate.certificate_number}.pdf",
    )
