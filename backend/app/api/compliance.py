from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import require_admin
from app.api.events import get_visible_event
from app.db.session import get_db
from app.models.attendee import Attendee
from app.models.certificate import Certificate
from app.models.event_attendee import EventAttendee
from app.models.survey_result import SurveyResult
from app.models.test_result import TestResult
from app.models.user import User
from app.schemas.common import ApprovalRequest, ComplianceRow, RosterRemovalResult
from app.services import storage
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
    # Compliance review is an admin-only surface: presenters hand in documents
    # but never see per-attendee eligibility, scores, or approval state.
    current_user: User = Depends(require_admin),
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


def _already_issued(certificate: Certificate) -> bool:
    """Has this certificate reached its holder?

    Two ways, and both leave a live credential in someone's hands: we emailed
    it (sent_at), or the holder pulled the PDF themselves from the public
    verification portal (downloaded_at — written only by that public route).
    A generated-but-undelivered certificate is not in this category: its number
    has never left the system, so a routine cleanup may drop it.
    """
    return certificate.sent_at is not None or certificate.downloaded_at is not None


def _remove_links(
    db: Session,
    event_id: int,
    links: list[EventAttendee],
    current_user: User,
    *,
    include_sent: bool,
) -> tuple[int, list[str], list[str]]:
    """Detach attendees from one event, returning (removed, kept, pdf paths).

    Everything that belongs to the attendee *on this event* goes with the link:
    the certificate (and its email logs, by cascade) plus the event's test and
    survey results — leaving those behind would resurface them in reports and
    in the re-import guards that protect web submissions. The global Attendee
    record is untouched, matching how deleting a whole event behaves.
    """
    removed = 0
    kept: list[str] = []
    pdf_paths: list[str] = []
    removed_attendee_ids: list[int] = []
    for link in links:
        certificate = link.certificate
        if certificate is not None and not include_sent and _already_issued(certificate):
            # The holder has this certificate and can still look its number up
            # in the public verification portal; dropping it takes an explicit
            # override rather than a routine roster cleanup.
            kept.append(link.attendee.full_name)
            continue
        record_audit(
            db,
            "attendee.removed",
            "event_attendee",
            link.id,
            current_user,
            event_id,
            {
                "attendee_id": link.attendee_id,
                "full_name": link.attendee.full_name,
                "email": link.attendee.email,
                **(
                    {
                        "certificate_number": certificate.certificate_number,
                        "certificate_sent": certificate.sent_at is not None,
                        "certificate_downloaded": certificate.downloaded_at is not None,
                    }
                    if certificate
                    else {}
                ),
            },
        )
        # Deleted explicitly for the same reason as in delete_event: the
        # relationship carries no ORM cascade, so the ORM would otherwise try
        # to NULL a non-nullable FK.
        if certificate is not None:
            pdf_paths.append(certificate.pdf_path)
            db.delete(certificate)
        # Read the FK before marking the row deleted, so the batched result
        # cleanup below cannot depend on a flushed/expired attribute.
        removed_attendee_ids.append(link.attendee_id)
        db.delete(link)
        removed += 1
    # One statement per table instead of two per attendee. Anonymous survey
    # rows (attendee_id IS NULL) never match, so blind feedback survives a
    # roster clear by design.
    if removed_attendee_ids:
        db.execute(
            delete(TestResult).where(
                TestResult.event_id == event_id,
                TestResult.attendee_id.in_(removed_attendee_ids),
            )
        )
        db.execute(
            delete(SurveyResult).where(
                SurveyResult.event_id == event_id,
                SurveyResult.attendee_id.in_(removed_attendee_ids),
            )
        )
    db.flush()
    return removed, kept, pdf_paths


@router.delete("", response_model=RosterRemovalResult)
def clear_roster(
    event_id: int,
    include_sent: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> RosterRemovalResult:
    """Empty this event's attendee roster.

    The repair for a roster that picked up the wrong people (e.g. names merged
    in from another event before matching was scoped): clear it, then upload
    the sign-in sheet again to rebuild it from the file alone.
    """
    get_visible_event(db, event_id, current_user)
    links = list(
        db.scalars(
            select(EventAttendee)
            .options(joinedload(EventAttendee.attendee), joinedload(EventAttendee.certificate))
            .where(EventAttendee.event_id == event_id)
        ).unique()
    )
    removed, kept, pdf_paths = _remove_links(
        db, event_id, links, current_user, include_sent=include_sent
    )
    record_audit(
        db,
        "roster.cleared",
        "training_event",
        event_id,
        current_user,
        event_id,
        {"removed": removed, "kept": len(kept), "include_sent": include_sent},
    )
    db.commit()
    # Best-effort file cleanup once the transaction is durable.
    for raw_path in pdf_paths:
        storage.delete_file(Path(raw_path))
    return RosterRemovalResult(removed=removed, kept_with_issued_certificates=kept)


@router.delete("/{link_id}", response_model=RosterRemovalResult)
def remove_attendee(
    event_id: int,
    link_id: int,
    include_sent: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> RosterRemovalResult:
    """Remove one attendee from this event (e.g. a name read off the wrong sheet)."""
    get_visible_event(db, event_id, current_user)
    link = db.scalar(
        select(EventAttendee)
        .options(joinedload(EventAttendee.attendee), joinedload(EventAttendee.certificate))
        .where(EventAttendee.id == link_id, EventAttendee.event_id == event_id)
    )
    if not link:
        raise HTTPException(status_code=404, detail="Attendee not found on this event")
    removed, kept, pdf_paths = _remove_links(
        db, event_id, [link], current_user, include_sent=include_sent
    )
    if not removed:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{kept[0]} already has a certificate that reached them. "
                "Removing them revokes that certificate — confirm to proceed."
            ),
        )
    db.commit()
    for raw_path in pdf_paths:
        storage.delete_file(Path(raw_path))
    return RosterRemovalResult(removed=removed, kept_with_issued_certificates=kept)


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

