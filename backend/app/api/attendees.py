"""Correcting an attendee's identity — the repair for a mistyped email.

An attendee's address reaches this system from a sign-in sheet, an OCR pass
over one, a spreadsheet export, or a phone typing it into a QR check-in. When
it is wrong the certificate cannot be delivered, and until this existed there
was no way to fix it anywhere in the product: the roster showed the bad
address, eligibility said "Missing or invalid email", and the only remedy was
to remove the person and re-upload a corrected file. Names arrive by the same
routes and get mangled the same way.

Three things make this more than a field update, and each is handled below:

1. **Normalization.** The correction is written through the same
   ``identity``/``attendee_match`` normalization the import path uses. A
   correction stored in a different shape than an import would produce is a
   correction that matching disagrees with -- the next upload of the same
   person would create a second record beside the one just fixed.

2. **Email is the global identity key.** ``attendee_match`` matches on
   ``normalized_email`` across every event, so pointing attendee A at an
   address that already belongs to attendee B is a *merge*, not an edit.
   It is refused: see ``_conflicting_attendees``.

3. **A certificate is a credential.** The public verification portal reports
   ``link.attendee.full_name`` live, so renaming somebody retroactively
   changes who the record says a certificate belongs to. Refused once the
   certificate has reached its holder: see ``_delivered_certificates``.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import require_admin
from app.db.session import get_db
from app.models.attendee import Attendee
from app.models.certificate import Certificate
from app.models.event_attendee import EventAttendee
from app.models.user import User
from app.schemas.common import AttendeeCorrection, AttendeeCorrectionOut
from app.services.attendee_match import FULL_NAME_MAX_LENGTH
from app.services.audit import record_audit
from app.services.certificates import reissue_certificate_pdf
from app.services.compliance import recalculate_event
from app.services.identity import (
    NAME_PART_MAX_LENGTH,
    humanize_name,
    normalize_email,
    normalize_name,
    split_name,
)
from app.services.retention import is_issued

router = APIRouter(prefix="/attendees", tags=["Attendees"])


def _load_attendee(db: Session, attendee_id: int) -> Attendee:
    attendee = db.scalar(select(Attendee).where(Attendee.id == attendee_id))
    if not attendee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendee not found")
    return attendee


def _links_for(db: Session, attendee_id: int) -> list[EventAttendee]:
    """Every event link this attendee has, with its certificate loaded.

    Eager-loaded because the guards below touch the certificate of each link,
    and an attendee who has been to a dozen events would otherwise cost a query
    each.
    """
    return list(
        db.scalars(
            select(EventAttendee)
            .options(selectinload(EventAttendee.certificate))
            .where(EventAttendee.attendee_id == attendee_id)
            .order_by(EventAttendee.id)
        )
    )


def _conflicting_attendees(
    db: Session, attendee: Attendee, norm_email: str
) -> list[Attendee]:
    """Other attendee records that already own this address.

    ``normalized_email`` has an index but no unique constraint, so in principle
    more than one row can hold the same key; all of them are reported.
    """
    return list(
        db.scalars(
            select(Attendee)
            .where(Attendee.normalized_email == norm_email, Attendee.id != attendee.id)
            .order_by(Attendee.id)
        )
    )


def _delivered_certificates(links: list[EventAttendee]) -> list[Certificate]:
    """Certificates of this attendee's that have reached their holder.

    ``is_issued`` is the same predicate the roster-removal guard and the
    retention floor use: emailed, or downloaded by the holder from the public
    portal. A generated-but-undelivered certificate is deliberately *not* in
    this set — its number has never left the system.
    """
    return [
        link.certificate
        for link in links
        if link.certificate is not None and is_issued(link.certificate)
    ]


def _rename_undelivered_certificate(link: EventAttendee, certificate: Certificate, new_name: str) -> None:
    """Carry a name correction into an undelivered certificate's record.

    The stored ``event_snapshot`` is what a re-issue renders from, so leaving it
    alone would mean the PDF kept printing the misspelling forever while the
    verification portal (which reads the live attendee) showed the corrected
    name — the same certificate saying two different things about whose it is.

    Only ``fields.attendee_name`` is touched. Re-snapshotting from the live
    event would silently pull in every unrelated edit made to the event since
    the certificate was issued, which is precisely what the snapshot exists to
    prevent.
    """
    snapshot = certificate.event_snapshot
    fields = snapshot.get("fields") if isinstance(snapshot, dict) else None
    if isinstance(fields, dict) and fields.get("attendee_name"):
        updated = dict(snapshot)
        updated["fields"] = {**fields, "attendee_name": new_name}
        certificate.event_snapshot = updated
    # A row with no usable snapshot (written before snapshots existed) is left
    # alone deliberately: fabricating one here would hand the renderer a record
    # that never existed. reissue_certificate_pdf already falls back to live
    # event data in that case, and the live attendee now carries the correction.
    #
    # Re-rendered in place so the file on disk and the record agree. Safe only
    # because nothing has been handed out — this is never reached for a
    # delivered certificate.
    reissue_certificate_pdf(link, certificate, output_path=Path(certificate.pdf_path))


@router.patch("/{attendee_id}", response_model=AttendeeCorrectionOut)
def correct_attendee(
    attendee_id: int,
    payload: AttendeeCorrection,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> AttendeeCorrectionOut:
    """Correct an attendee's email address and/or name.

    Admin-only and audited with before/after values: this edits a compliance
    record, and the trail of who changed an attendee's identity, when, and from
    what is the reason the endpoint is allowed to exist at all.

    Correcting an email re-runs eligibility for every event the attendee is on,
    because ``has_valid_email`` gates certificate issue — an admin who fixes an
    address sees that person become eligible without re-uploading anything.

    Refused with a 409 in two cases, both explained in the response body:
    an address that already belongs to somebody else (that is a merge), and an
    attendee holding a certificate that has already been delivered.
    """
    attendee = _load_attendee(db, attendee_id)

    # --- Work out the corrected values, in the import path's normal form -----
    new_email = attendee.email
    new_norm_email = attendee.normalized_email
    if payload.email is not None:
        # normalize_email is the same function the import and the public forms
        # write through; storing anything else here would make matching and
        # eligibility disagree about what this attendee's address is.
        new_norm_email = normalize_email(str(payload.email))
        if not new_norm_email:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="That does not look like a deliverable email address",
            )
        new_email = new_norm_email

    new_full_name = attendee.full_name
    if payload.full_name is not None:
        # humanize_name flips "Smith, Bob" the way an import would, so a
        # correction typed in export order lands identically to an imported one.
        new_full_name = humanize_name(payload.full_name)[:FULL_NAME_MAX_LENGTH]
        if not new_full_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A name is required",
            )

    changed: list[str] = []
    if new_norm_email != attendee.normalized_email or new_email != attendee.email:
        changed.append("email")
    if new_full_name != attendee.full_name:
        changed.append("full_name")

    before = {"full_name": attendee.full_name, "email": attendee.email}
    links = _links_for(db, attendee_id)

    if not changed:
        # A no-op restatement is not an error, and must not trip the guards
        # below: refusing to "change" a name to the name it already has would
        # be a confusing way to say nothing happened.
        return AttendeeCorrectionOut(
            attendee_id=attendee.id, full_name=attendee.full_name, email=attendee.email
        )

    # --- Guard: is this address already somebody else's identity? -----------
    if "email" in changed and new_norm_email:
        conflicts = _conflicting_attendees(db, attendee, new_norm_email)
        if conflicts:
            names = ", ".join(f"{other.full_name} (#{other.id})" for other in conflicts)
            record_audit(
                db,
                "attendee.correction_blocked",
                "attendee",
                attendee.id,
                current_user,
                details={
                    "reason": "email_belongs_to_another_attendee",
                    "before": before,
                    "requested_email": new_norm_email,
                    "conflicting_attendee_ids": [other.id for other in conflicts],
                },
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"{new_norm_email} is already the identity of {names}. Email "
                    "addresses identify people across every event here, so pointing "
                    f"{attendee.full_name} at this one would merge two attendee "
                    "records — including their events, results and certificates — "
                    "rather than correct a typo. Merging is not something this "
                    "endpoint does. If they are genuinely the same person, remove "
                    "the duplicate from its events and re-upload the roster; if "
                    "they are two people, one of the two addresses is wrong."
                ),
            )

    # --- Guard: has a certificate already reached this person? --------------
    # The public verification portal answers with the *live* attendee name, so
    # a rename here would retroactively change who a certificate in somebody's
    # hands says it belongs to. The email is refused alongside it rather than
    # separately: this record is one identity, and there is no meaningful state
    # in which half of it may be rewritten under an issued credential. The
    # existing remedy for a certificate in the wrong name is revocation
    # (DELETE /events/{id}/compliance/{link_id}?include_sent=true), which keeps
    # the withdrawn document on record and lets a corrected one be issued.
    delivered = _delivered_certificates(links)
    if delivered:
        numbers = ", ".join(certificate.certificate_number for certificate in delivered)
        record_audit(
            db,
            "attendee.correction_blocked",
            "attendee",
            attendee.id,
            current_user,
            details={
                "reason": "certificate_already_delivered",
                "before": before,
                "certificate_numbers": [c.certificate_number for c in delivered],
            },
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{attendee.full_name} already holds a delivered certificate "
                f"({numbers}). Correcting their details would change who that "
                "credential belongs to, including in the public verification "
                "portal where somebody may be checking it right now. Revoke the "
                "certificate first — it stays on record and verifies as revoked — "
                "then correct the details and issue a new one."
            ),
        )

    # --- Apply -------------------------------------------------------------
    attendee.full_name = new_full_name
    attendee.normalized_name = normalize_name(new_full_name)[:FULL_NAME_MAX_LENGTH]
    # first/last are the same convenience split the import derives, kept in step
    # so search and reports do not keep showing the old spelling.
    split_first, split_last = split_name(new_full_name)
    attendee.first_name = (split_first or "")[:NAME_PART_MAX_LENGTH] or None
    attendee.last_name = (split_last or "")[:NAME_PART_MAX_LENGTH] or None
    attendee.email = new_email
    attendee.normalized_email = new_norm_email

    certificates_updated: list[str] = []
    if "full_name" in changed:
        for link in links:
            certificate = link.certificate
            # A revoked certificate is skipped: it is the record of what was
            # issued and then withdrawn, and rewriting a withdrawn document is
            # not a correction. The email is not printed on a certificate, so an
            # email-only change never re-renders anything.
            if certificate is not None and not certificate.is_revoked:
                _rename_undelivered_certificate(link, certificate, new_full_name)
                certificates_updated.append(certificate.certificate_number)

    # --- Re-run eligibility -------------------------------------------------
    # has_valid_email gates certificate issue, so a corrected address has to be
    # reflected in every event this person is on, not just the one the admin
    # happened to be looking at.
    was_eligible = {link.id: link.eligible for link in links}
    events = sorted({link.event_id for link in links})
    newly_eligible: list[int] = []
    for event_id in events:
        for link in recalculate_event(db, event_id):
            if link.attendee_id == attendee.id and link.eligible and not was_eligible.get(link.id):
                newly_eligible.append(link.id)

    record_audit(
        db,
        "attendee.corrected",
        "attendee",
        attendee.id,
        current_user,
        details={
            "changed": changed,
            "before": before,
            "after": {"full_name": attendee.full_name, "email": attendee.email},
            "reason": payload.reason,
            "events_recalculated": events,
            "newly_eligible_event_attendee_ids": sorted(newly_eligible),
            "certificates_updated": sorted(certificates_updated),
        },
    )
    db.commit()
    db.refresh(attendee)
    return AttendeeCorrectionOut(
        attendee_id=attendee.id,
        full_name=attendee.full_name,
        email=attendee.email,
        changed=changed,
        events_recalculated=events,
        newly_eligible=sorted(newly_eligible),
        certificates_updated=sorted(certificates_updated),
    )
