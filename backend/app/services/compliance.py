from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.event_attendee import EventAttendee
from app.services.identity import is_valid_email

PASSING_SCORE = Decimal("80.00")


def evaluate_link(link: EventAttendee) -> EventAttendee:
    reasons: list[str] = []
    link.has_valid_email = is_valid_email(link.attendee.email)
    if not link.attended:
        reasons.append("Not found on attendance sheet")
    if not link.test_completed:
        reasons.append("Post-test not completed")
    elif link.test_score is None or link.test_score < PASSING_SCORE:
        reasons.append("Post-test score below 80%")
    # The feedback survey is encouraged (it supports association renewals) and
    # only blocks eligibility when the event is configured to require it.
    if link.event.survey_required and not link.survey_completed:
        reasons.append("Feedback survey not completed")
    if not link.has_valid_email:
        reasons.append("Missing or invalid email")

    link.eligibility_reasons = reasons
    link.eligible = not reasons
    if link.approved:
        link.compliance_status = "approved"
    elif link.eligible:
        link.compliance_status = "eligible"
    else:
        link.compliance_status = "ineligible"
    return link


def lifecycle_status(link: EventAttendee) -> str:
    """Single human-facing status spanning the whole certificate lifecycle."""
    certificate = link.certificate
    if certificate:
        if certificate.downloaded_at:
            return "downloaded"
        if certificate.delivered_at:
            return "delivered"
        if certificate.sent_at:
            return "sent"
        return "generated"
    if link.approved:
        return "approved"
    if link.eligible:
        return "eligible"
    if not link.attended:
        return "pending_attendance"
    if not link.test_completed or link.test_score is None or link.test_score < PASSING_SCORE:
        return "pending_test"
    if link.event.survey_required and not link.survey_completed:
        return "pending_survey"
    return "pending"


def recalculate_event(db: Session, event_id: int) -> list[EventAttendee]:
    links = list(
        db.scalars(
            select(EventAttendee)
            .where(EventAttendee.event_id == event_id)
            .order_by(EventAttendee.id)
        )
    )
    for link in links:
        evaluate_link(link)
    db.flush()
    return links

