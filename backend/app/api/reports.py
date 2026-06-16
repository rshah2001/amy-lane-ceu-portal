import csv
import io
from datetime import date

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, require_admin
from app.db.session import get_db
from app.models.attendee import Attendee
from app.models.audit_log import AuditLog
from app.models.event_attendee import EventAttendee
from app.models.training_event import TrainingEvent
from app.models.user import User
from app.schemas.common import AttendeeSearchRow, ReportColumn

router = APIRouter(tags=["Reports"])

# Selectable report columns: key -> (header, value extractor). Lets the report
# builder pick exactly what an association renewal or audit needs.
REPORT_COLUMNS: dict[str, tuple[str, object]] = {
    "event": ("Event", lambda link: link.event.title),
    "event_date": ("Event Date", lambda link: link.event.event_date.isoformat()),
    "event_type": ("Event Type", lambda link: link.event.event_type),
    "ceu_hours": ("CEU Hours", lambda link: str(link.event.ceu_hours)),
    "course_instructor": ("Course Instructor", lambda link: link.event.course_instructor or link.event.presenter_name or ""),
    "attendee": ("Attendee", lambda link: link.attendee.full_name),
    "email": ("Email", lambda link: link.attendee.email or ""),
    "company": ("Company", lambda link: link.attendee.company or ""),
    "test_score": ("Test Score", lambda link: str(link.test_score) if link.test_score is not None else ""),
    "attended": ("Attended", lambda link: "Yes" if link.attended else "No"),
    "survey_completed": ("Survey Completed", lambda link: "Yes" if link.survey_completed else "No"),
    "eligible": ("Eligible", lambda link: "Yes" if link.eligible else "No"),
    "approved": ("Approved", lambda link: "Yes" if link.approved else "No"),
    "certificate_number": ("Certificate Number", lambda link: link.certificate.certificate_number if link.certificate else ""),
    "certificate_sent_at": (
        "Certificate Sent At",
        lambda link: link.certificate.sent_at.isoformat() if link.certificate and link.certificate.sent_at else "",
    ),
}
DEFAULT_REPORT_COLUMNS = [
    "event", "event_date", "attendee", "email", "company",
    "test_score", "eligible", "approved", "certificate_number", "certificate_sent_at",
]


@router.get("/attendees/search", response_model=list[AttendeeSearchRow])
def attendee_search(
    q: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AttendeeSearchRow]:
    query = (
        select(EventAttendee)
        .options(
            joinedload(EventAttendee.attendee),
            joinedload(EventAttendee.event),
            joinedload(EventAttendee.certificate),
        )
        .join(Attendee)
        .join(TrainingEvent)
    )
    if current_user.role != "admin":
        query = query.where(TrainingEvent.assigned_presenter_id == current_user.id)
    if q:
        query = query.where(
            (Attendee.full_name.ilike(f"%{q}%"))
            | (Attendee.email.ilike(f"%{q}%"))
            | (Attendee.company.ilike(f"%{q}%"))
        )
    links = db.scalars(query.order_by(Attendee.full_name).limit(200)).unique()
    return [
        AttendeeSearchRow(
            attendee_id=link.attendee_id,
            full_name=link.attendee.full_name,
            email=link.attendee.email,
            company=link.attendee.company,
            event_id=link.event_id,
            event_title=link.event.title,
            event_date=link.event.event_date,
            eligible=link.eligible,
            approved=link.approved,
            certificate_number=link.certificate.certificate_number if link.certificate else None,
        )
        for link in links
    ]


@router.get("/audit-logs")
def audit_logs(
    event_id: int | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[dict]:
    query = select(AuditLog)
    if event_id:
        query = query.where(AuditLog.event_id == event_id)
    logs = db.scalars(query.order_by(AuditLog.created_at.desc()).limit(max(1, min(limit, 1000))))
    return [
        {
            "id": log.id,
            "actor_id": log.actor_id,
            "event_id": log.event_id,
            "action": log.action,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "details": log.details,
            "created_at": log.created_at,
        }
        for log in logs
    ]


@router.get("/reports/columns", response_model=list[ReportColumn])
def report_columns(_: User = Depends(require_admin)) -> list[ReportColumn]:
    return [ReportColumn(key=key, label=header) for key, (header, _extract) in REPORT_COLUMNS.items()]


@router.get("/reports/annual/{year}")
def annual_report(
    year: int,
    event_type: str | None = None,
    eligibility: str | None = None,
    columns: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> StreamingResponse:
    selected = [key for key in (columns.split(",") if columns else DEFAULT_REPORT_COLUMNS) if key in REPORT_COLUMNS]
    if not selected:
        selected = DEFAULT_REPORT_COLUMNS

    start = date(year, 1, 1)
    end = date(year + 1, 1, 1)
    query = (
        select(EventAttendee)
        .options(
            joinedload(EventAttendee.attendee),
            joinedload(EventAttendee.event),
            joinedload(EventAttendee.certificate),
        )
        .join(TrainingEvent)
        .where(TrainingEvent.event_date >= start, TrainingEvent.event_date < end)
    )
    if event_type:
        query = query.where(TrainingEvent.event_type == event_type)
    if eligibility == "eligible":
        query = query.where(EventAttendee.eligible.is_(True))
    elif eligibility == "ineligible":
        query = query.where(EventAttendee.eligible.is_(False))
    links = db.scalars(query.order_by(TrainingEvent.event_date, EventAttendee.id)).unique()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([REPORT_COLUMNS[key][0] for key in selected])
    for link in links:
        writer.writerow([REPORT_COLUMNS[key][1](link) for key in selected])

    response = StreamingResponse(iter([output.getvalue()]), media_type="text/csv")
    response.headers["Content-Disposition"] = f'attachment; filename="ceu-annual-report-{year}.csv"'
    return response

