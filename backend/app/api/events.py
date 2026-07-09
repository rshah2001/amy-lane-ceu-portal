from collections import Counter
from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.db.session import get_db
from app.models.certificate import Certificate
from app.models.event_attendee import EventAttendee
from app.models.training_event import TrainingEvent
from app.models.user import User
from app.schemas.common import (
    ChartBucket,
    DashboardCharts,
    DashboardStats,
    EventCompliancePoint,
    EventCreate,
    EventOut,
    EventSummary,
    EventUpdate,
)
from app.services.audit import record_audit

PASSING_SCORE = Decimal("80")

router = APIRouter(tags=["Events"])


def visible_event_query(user: User):
    query = select(TrainingEvent)
    if user.role != "admin":
        # Presenters only see events an admin has assigned to them.
        query = query.where(TrainingEvent.assigned_presenter_id == user.id)
    return query


def get_visible_event(db: Session, event_id: int, user: User) -> TrainingEvent:
    event = db.scalar(visible_event_query(user).where(TrainingEvent.id == event_id))
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.get("/dashboard", response_model=DashboardStats)
def dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardStats:
    event_ids = visible_event_query(current_user).with_only_columns(TrainingEvent.id)
    total_events = db.scalar(select(func.count()).select_from(event_ids.subquery())) or 0
    upcoming_events = db.scalar(
        select(func.count()).select_from(
            visible_event_query(current_user)
            .where(TrainingEvent.event_date >= date.today())
            .with_only_columns(TrainingEvent.id)
            .subquery()
        )
    ) or 0
    pending_reviews = db.scalar(
        select(func.count(EventAttendee.id)).where(
            EventAttendee.event_id.in_(event_ids),
            EventAttendee.eligible.is_(True),
            EventAttendee.approved.is_(False),
        )
    ) or 0
    sent = db.scalar(
        select(func.count(Certificate.id))
        .join(EventAttendee)
        .where(EventAttendee.event_id.in_(event_ids), Certificate.sent_at.is_not(None))
    ) or 0
    total_attendees = db.scalar(
        select(func.count(EventAttendee.id)).where(EventAttendee.event_id.in_(event_ids))
    ) or 0
    eligible = db.scalar(
        select(func.count(EventAttendee.id)).where(
            EventAttendee.event_id.in_(event_ids), EventAttendee.eligible.is_(True)
        )
    ) or 0
    return DashboardStats(
        total_events=total_events,
        upcoming_events=upcoming_events,
        pending_reviews=pending_reviews,
        certificates_sent=sent,
        compliance_rate=round((eligible / total_attendees * 100) if total_attendees else 0, 1),
    )


@router.get("/dashboard/charts", response_model=DashboardCharts)
def dashboard_charts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardCharts:
    event_ids = visible_event_query(current_user).with_only_columns(TrainingEvent.id)

    completed = list(
        db.scalars(
            select(EventAttendee).where(
                EventAttendee.event_id.in_(event_ids),
                EventAttendee.test_completed.is_(True),
            )
        )
    )
    bands = ["<60", "60-69", "70-79", "80-89", "90-100"]
    score_counts = {band: 0 for band in bands}
    for link in completed:
        score = float(link.test_score or 0)
        if score < 60:
            score_counts["<60"] += 1
        elif score < 70:
            score_counts["60-69"] += 1
        elif score < 80:
            score_counts["70-79"] += 1
        elif score < 90:
            score_counts["80-89"] += 1
        else:
            score_counts["90-100"] += 1

    recent_events = list(
        db.scalars(visible_event_query(current_user).order_by(TrainingEvent.event_date.desc()).limit(8))
    )
    events_compliance: list[EventCompliancePoint] = []
    for event in reversed(recent_events):
        total = db.scalar(
            select(func.count(EventAttendee.id)).where(EventAttendee.event_id == event.id)
        ) or 0
        eligible = db.scalar(
            select(func.count(EventAttendee.id)).where(
                EventAttendee.event_id == event.id, EventAttendee.eligible.is_(True)
            )
        ) or 0
        events_compliance.append(
            EventCompliancePoint(event_id=event.id, title=event.title, eligible=eligible, total=total)
        )

    sent_dates = db.scalars(
        select(Certificate.sent_at)
        .join(EventAttendee)
        .where(EventAttendee.event_id.in_(event_ids), Certificate.sent_at.is_not(None))
    )
    monthly = Counter(dt.strftime("%Y-%m") for dt in sent_dates if dt)
    today = date.today()
    months: list[ChartBucket] = []
    for offset in range(5, -1, -1):
        month = (today.month - offset - 1) % 12 + 1
        year = today.year + (today.month - offset - 1) // 12
        key = f"{year:04d}-{month:02d}"
        months.append(ChartBucket(label=date(year, month, 1).strftime("%b"), value=monthly.get(key, 0)))

    return DashboardCharts(
        score_distribution=[ChartBucket(label=band, value=score_counts[band]) for band in bands],
        events_compliance=events_compliance,
        monthly_certificates=months,
    )


@router.get("/events", response_model=list[EventOut])
def list_events(
    status_filter: str | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TrainingEvent]:
    query = visible_event_query(current_user)
    if status_filter:
        query = query.where(TrainingEvent.status == status_filter)
    if search:
        query = query.where(TrainingEvent.title.ilike(f"%{search}%"))
    return list(db.scalars(query.order_by(TrainingEvent.event_date.desc())))


@router.post("/events", response_model=EventOut, status_code=201)
def create_event(
    payload: EventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> TrainingEvent:
    data = payload.model_dump()
    presenter_id = data.get("assigned_presenter_id")
    if presenter_id is not None:
        presenter = db.scalar(select(User).where(User.id == presenter_id))
        if not presenter or not presenter.is_active:
            raise HTTPException(status_code=400, detail="Assigned presenter not found")
    event = TrainingEvent(
        **data,
        created_by_id=current_user.id,
        survey_token=uuid4().hex,
        test_token=uuid4().hex,
        checkin_token=uuid4().hex,
        survey_questions=[
            {"id": "liked", "label": "What did you like about this course?"},
            {"id": "improve", "label": "What could we improve?"},
            {"id": "learned", "label": "What is one thing you learned?"},
        ],
    )
    db.add(event)
    db.flush()
    record_audit(db, "event.created", "training_event", event.id, current_user, event.id)
    db.commit()
    db.refresh(event)
    return event


@router.put("/events/{event_id}", response_model=EventOut)
def update_event(
    event_id: int,
    payload: EventUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> TrainingEvent:
    event = get_visible_event(db, event_id, current_user)
    # Only apply fields the client explicitly sent; editing test_questions /
    # survey_questions replaces the whole list. Tokens are never regenerated.
    data = payload.model_dump(exclude_unset=True)
    presenter_id = data.get("assigned_presenter_id")
    if presenter_id is not None:
        presenter = db.scalar(select(User).where(User.id == presenter_id))
        if not presenter or not presenter.is_active:
            raise HTTPException(status_code=400, detail="Assigned presenter not found")
    for field, value in data.items():
        setattr(event, field, value)
    record_audit(
        db,
        "event.updated",
        "training_event",
        event.id,
        current_user,
        event.id,
        {"fields": sorted(data.keys())},
    )
    db.commit()
    db.refresh(event)
    return event


@router.get("/events/{event_id}", response_model=EventOut)
def get_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TrainingEvent:
    return get_visible_event(db, event_id, current_user)


@router.get("/events/{event_id}/summary", response_model=EventSummary)
def event_summary(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EventSummary:
    get_visible_event(db, event_id, current_user)
    links = list(db.scalars(select(EventAttendee).where(EventAttendee.event_id == event_id)))
    total = len(links)
    eligible = sum(1 for link in links if link.eligible)
    certificates_generated = db.scalar(
        select(func.count(Certificate.id)).join(EventAttendee).where(EventAttendee.event_id == event_id)
    ) or 0
    certificates_sent = db.scalar(
        select(func.count(Certificate.id))
        .join(EventAttendee)
        .where(EventAttendee.event_id == event_id, Certificate.sent_at.is_not(None))
    ) or 0
    return EventSummary(
        event_id=event_id,
        total_attendees=total,
        registered=sum(1 for link in links if link.registered),
        attended=sum(1 for link in links if link.attended),
        test_passed=sum(
            1 for link in links if link.test_completed and link.test_score is not None and link.test_score >= PASSING_SCORE
        ),
        survey_completed=sum(1 for link in links if link.survey_completed),
        eligible=eligible,
        approved=sum(1 for link in links if link.approved),
        certificates_generated=certificates_generated,
        certificates_sent=certificates_sent,
        compliance_rate=round(eligible / total * 100, 1) if total else 0.0,
    )
