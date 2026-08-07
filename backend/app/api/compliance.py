from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
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
from app.models.training_event import TrainingEvent
from app.models.user import User
from app.schemas.common import ApprovalRequest, ComplianceRow, RosterRemovalResult
from app.services import storage
from app.services.audit import record_audit
from app.services.compliance import evaluate_link, lifecycle_status, recalculate_event
from app.services.retention import is_retained, retained_until

router = APIRouter(prefix="/events/{event_id}/compliance", tags=["Compliance"])

# Matches Certificate.revoked_reason. Bounded here as well so an over-long
# reason is a 422 rather than a database error at flush time.
REASON_MAX_LENGTH = 500


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
        certificate_revoked_at=certificate.revoked_at if certificate else None,
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


def _revoke(
    db: Session,
    event: TrainingEvent,
    link: EventAttendee,
    certificate: Certificate,
    current_user: User,
    reason: str | None,
) -> None:
    """Withdraw an issued certificate and take its holder off the roster.

    Neither the row nor the PDF is touched: the certificate number keeps
    resolving in the public portal, where it now answers "revoked" instead of
    "valid", which is the only way somebody holding the document can be told it
    no longer counts. Re-revoking is a no-op on the certificate itself so a
    repeated request cannot rewrite who revoked it and when, but it still
    detaches and still audits.
    """
    if not certificate.is_revoked:
        certificate.revoked_at = datetime.now(timezone.utc)
        certificate.revoked_by_id = current_user.id
        certificate.revoked_reason = (reason or "").strip() or None
    _detach_from_roster(link)
    record_audit(
        db,
        "certificate.revoked",
        "certificate",
        certificate.id,
        current_user,
        event.id,
        {
            "attendee_id": link.attendee_id,
            "event_attendee_id": link.id,
            "full_name": link.attendee.full_name,
            "email": link.attendee.email,
            "certificate_number": certificate.certificate_number,
            "certificate_sent": certificate.sent_at is not None,
            "certificate_downloaded": certificate.downloaded_at is not None,
            "reason": certificate.revoked_reason,
            # Says when this record may finally be destroyed, so the audit
            # entry explains on its own why the row is still here.
            "retained_until": retained_until(event, [certificate]).isoformat(),
        },
    )


def _detach_from_roster(link: EventAttendee) -> None:
    """Strip the participation an attendee cannot keep, without deleting them.

    Used only on the revocation path, where the link row itself has to survive
    (see ``_remove_links``). It clears everything that makes the person an
    active roster member — so they stop counting toward the event's compliance
    rate, its completion check, and the certificate queues — while leaving the
    identity the certificate hangs off intact.
    """
    link.registered = False
    link.attended = False
    link.checked_in_at = None
    link.test_completed = False
    link.test_score = None
    link.survey_completed = False
    link.approved = False
    link.approved_at = None
    link.approved_by_id = None
    # eligible / eligibility_reasons / compliance_status are indexed and read
    # straight out of the database by the reports and dashboard queries, so they
    # are re-derived here rather than left stale until the next compliance GET
    # happens to recalculate the event.
    evaluate_link(link)


def _remove_links(
    db: Session,
    event: TrainingEvent,
    links: list[EventAttendee],
    current_user: User,
    *,
    include_sent: bool,
    reason: str | None = None,
) -> tuple[int, list[str], list[str], list[str]]:
    """Take attendees off one event, returning (removed, kept, revoked, pdfs).

    Everything that belongs to the attendee *on this event* goes with the link:
    the certificate (and its email logs, by cascade) plus the event's test and
    survey results — leaving those behind would resurface them in reports and
    in the re-import guards that protect web submissions. The global Attendee
    record is untouched, matching how deleting a whole event behaves.

    Except for an issued certificate inside its retention window. That one is
    revoked, never deleted, and its ``EventAttendee`` row is kept alive with it
    — deliberately, because of the foreign keys:

    * ``certificates.event_attendee_id`` is NOT NULL and ``ON DELETE CASCADE``.
      Deleting the link destroys the certificate at the database level no
      matter what this function intends, which is precisely what the seven-year
      retention commitment forbids.
    * Nothing else identifies the certificate's holder. ``event_snapshot``
      captures the document, but the *person* and the *event* are only reachable
      through the link, and the public verification lookup joins through it. A
      certificate whose link is gone could not be reported as revoked-and-issued
      -to-whom; it could only be reported as nonexistent.

    Making the FK nullable was the alternative, and it buys nothing: a
    certificate pointing at NULL is a record we cannot reconstruct, which is the
    same loss as deleting it, only quieter. So the row stays and
    ``_detach_from_roster`` empties it out instead.
    """
    removed = 0
    kept: list[str] = []
    revoked: list[str] = []
    pdf_paths: list[str] = []
    removed_attendee_ids: list[int] = []
    detached_attendee_ids: list[int] = []
    for link in links:
        certificate = link.certificate
        if certificate is not None and _already_issued(certificate):
            if not include_sent:
                # The holder has this certificate and can still look its number
                # up in the public verification portal; touching it takes an
                # explicit override rather than a routine roster cleanup.
                kept.append(link.attendee.full_name)
                continue
            if is_retained(event, certificate):
                _revoke(db, event, link, certificate, current_user, reason)
                revoked.append(link.attendee.full_name)
                detached_attendee_ids.append(link.attendee_id)
                continue
            # Past the retention window there is nothing left to keep, so the
            # original delete behaviour stands.
        record_audit(
            db,
            "attendee.removed",
            "event_attendee",
            link.id,
            current_user,
            event.id,
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
    # roster clear by design. Attendees whose certificate was revoked are in
    # this list too: their event results are the wrong person's scores, and the
    # record the retention commitment is about is the certificate, not the
    # post-test that produced it.
    orphaned_attendee_ids = removed_attendee_ids + detached_attendee_ids
    if orphaned_attendee_ids:
        db.execute(
            delete(TestResult).where(
                TestResult.event_id == event.id,
                TestResult.attendee_id.in_(orphaned_attendee_ids),
            )
        )
        db.execute(
            delete(SurveyResult).where(
                SurveyResult.event_id == event.id,
                SurveyResult.attendee_id.in_(orphaned_attendee_ids),
            )
        )
    db.flush()
    return removed, kept, revoked, pdf_paths


@router.delete("", response_model=RosterRemovalResult)
def clear_roster(
    event_id: int,
    include_sent: bool = False,
    reason: str | None = Query(default=None, max_length=REASON_MAX_LENGTH),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> RosterRemovalResult:
    """Empty this event's attendee roster.

    The repair for a roster that picked up the wrong people (e.g. names merged
    in from another event before matching was scoped): clear it, then upload
    the sign-in sheet again to rebuild it from the file alone.

    ``include_sent`` reaches attendees whose certificate already reached them;
    those certificates are revoked rather than deleted while they are inside the
    retention window, and ``revoked`` in the response names them.
    """
    event = get_visible_event(db, event_id, current_user)
    links = list(
        db.scalars(
            select(EventAttendee)
            .options(joinedload(EventAttendee.attendee), joinedload(EventAttendee.certificate))
            .where(EventAttendee.event_id == event_id)
        ).unique()
    )
    removed, kept, revoked, pdf_paths = _remove_links(
        db, event, links, current_user, include_sent=include_sent, reason=reason
    )
    record_audit(
        db,
        "roster.cleared",
        "training_event",
        event_id,
        current_user,
        event_id,
        {
            "removed": removed,
            "kept": len(kept),
            "revoked": len(revoked),
            "include_sent": include_sent,
        },
    )
    db.commit()
    # Best-effort file cleanup once the transaction is durable. Revoked
    # certificates contribute no paths here — their PDFs are part of the record.
    for raw_path in pdf_paths:
        storage.delete_file(Path(raw_path))
    return RosterRemovalResult(
        removed=removed, kept_with_issued_certificates=kept, revoked=revoked
    )


@router.delete("/{link_id}", response_model=RosterRemovalResult)
def remove_attendee(
    event_id: int,
    link_id: int,
    include_sent: bool = False,
    reason: str | None = Query(default=None, max_length=REASON_MAX_LENGTH),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> RosterRemovalResult:
    """Remove one attendee from this event (e.g. a name read off the wrong sheet).

    With ``include_sent`` this is also the certificate-revocation route: a
    certificate that reached the wrong person is withdrawn here, and ``reason``
    records why on the certificate and in the audit trail.
    """
    event = get_visible_event(db, event_id, current_user)
    link = db.scalar(
        select(EventAttendee)
        .options(joinedload(EventAttendee.attendee), joinedload(EventAttendee.certificate))
        .where(EventAttendee.id == link_id, EventAttendee.event_id == event_id)
    )
    if not link:
        raise HTTPException(status_code=404, detail="Attendee not found on this event")
    removed, kept, revoked, pdf_paths = _remove_links(
        db, event, [link], current_user, include_sent=include_sent, reason=reason
    )
    if not removed and not revoked:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{kept[0]} already has a certificate that reached them. "
                "Removing them revokes that certificate — it stays on record and "
                "verifies publicly as revoked. Confirm to proceed."
            ),
        )
    db.commit()
    for raw_path in pdf_paths:
        storage.delete_file(Path(raw_path))
    return RosterRemovalResult(
        removed=removed, kept_with_issued_certificates=kept, revoked=revoked
    )


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

