import csv
import io
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone

import qrcode
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.api.events import get_visible_event
from app.core.config import settings
from app.db.session import get_db
from app.models.attendee import Attendee
from app.models.survey_result import SurveyResult
from app.models.training_event import TrainingEvent
from app.models.user import User
from app.schemas.common import (
    PublicSurveyOut,
    PublicSurveySubmission,
    SurveyInsights,
    SurveyResponseRow,
)
from app.services.attendee_match import get_or_create_link, match_or_create_attendee
from app.services.audit import record_audit
from app.services.compliance import recalculate_event
from app.services.survey_ai import summarize_survey_answers

router = APIRouter(tags=["Surveys"])
STOP_WORDS = {
    "about", "after", "again", "also", "and", "because", "course", "from",
    "have", "just", "more", "that", "the", "this", "very", "was", "were",
    "what", "with", "would", "your",
}


def get_survey_event(db: Session, token: str) -> TrainingEvent:
    event = db.scalar(select(TrainingEvent).where(TrainingEvent.survey_token == token))
    if not event or event.survey_mode != "internal":
        raise HTTPException(status_code=404, detail="Survey not found")
    return event


@router.get("/public/surveys/{token}", response_model=PublicSurveyOut)
def public_survey(token: str, db: Session = Depends(get_db)) -> PublicSurveyOut:
    event = get_survey_event(db, token)
    return PublicSurveyOut(
        event_title=event.title,
        event_date=event.event_date,
        presenter_name=event.presenter_name,
        questions=event.survey_questions,
    )


@router.post("/public/surveys/{token}")
def submit_public_survey(
    token: str,
    payload: PublicSurveySubmission,
    db: Session = Depends(get_db),
) -> dict:
    event = get_survey_event(db, token)
    # Choice questions only accept one of their configured options.
    options_for = {
        str(question.get("id")): question.get("options") or []
        for question in event.survey_questions or []
        if question.get("type") == "choice"
    }
    for question_id, answer in payload.answers.items():
        if question_id in options_for and answer not in options_for[question_id]:
            raise HTTPException(
                status_code=422,
                detail="One of the answers is not a valid option for its question.",
            )
    # Name and email are both optional: with neither, the response is stored
    # anonymously (no attendee linked); with either one, we match/create an
    # attendee from whatever identity was given, as before.
    attendee = None
    if payload.full_name or payload.email:
        attendee = match_or_create_attendee(
            db,
            event.id,
            payload.full_name or "",
            str(payload.email) if payload.email else None,
        )
    # Every submission is kept as its own row: the same attendee may answer
    # more than once and admins want to see all responses, not just the last.
    result = SurveyResult(
        event_id=event.id,
        attendee_id=attendee.id if attendee else None,
        business_location=payload.business_location,
        source="web",
    )
    db.add(result)
    result.completed = True
    result.completed_at = datetime.now(timezone.utc)
    result.raw_payload = payload.answers
    if attendee:
        link = get_or_create_link(db, event.id, attendee.id)
        link.survey_completed = True
    db.flush()
    recalculate_event(db, event.id)
    record_audit(
        db,
        "survey.submitted",
        "survey_result",
        result.id,
        None,
        event.id,
        {"attendee_id": attendee.id if attendee else None},
    )
    db.commit()
    return {"status": "submitted"}


@router.get("/events/{event_id}/survey-qr")
def survey_qr(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    event = get_visible_event(db, event_id, current_user)
    if event.survey_mode == "external" and event.external_survey_url:
        url = event.external_survey_url
    elif event.survey_token:
        url = f"{settings.public_frontend_url}/?survey={event.survey_token}"
    else:
        raise HTTPException(status_code=409, detail="This event has no survey link yet")
    image = qrcode.make(url)
    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return StreamingResponse(output, media_type="image/png")


def _response_query(db: Session, event_id: int | None, attendee_id: int | None, search: str | None):
    # Outer join: anonymous submissions have no attendee row.
    query = (
        select(SurveyResult, Attendee, TrainingEvent)
        .outerjoin(Attendee, SurveyResult.attendee_id == Attendee.id)
        .join(TrainingEvent, SurveyResult.event_id == TrainingEvent.id)
        .where(SurveyResult.completed.is_(True))
        .order_by(SurveyResult.completed_at.desc())
    )
    if event_id:
        query = query.where(SurveyResult.event_id == event_id)
    if attendee_id:
        query = query.where(SurveyResult.attendee_id == attendee_id)
    if search:
        term = f"%{search.strip()}%"
        query = query.where(or_(Attendee.full_name.ilike(term), Attendee.email.ilike(term)))
    return query


@router.get("/survey-responses", response_model=list[SurveyResponseRow])
def list_survey_responses(
    event_id: int | None = None,
    attendee_id: int | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[SurveyResponseRow]:
    rows = db.execute(_response_query(db, event_id, attendee_id, search)).all()
    return [
        SurveyResponseRow(
            id=result.id,
            event_id=result.event_id,
            event_title=event.title,
            attendee_id=attendee.id if attendee else None,
            full_name=attendee.full_name if attendee else None,
            email=attendee.email if attendee else None,
            company=attendee.company if attendee else None,
            business_location=result.business_location,
            completed_at=result.completed_at,
            answers=result.raw_payload or {},
        )
        for result, attendee, event in rows
    ]


@router.get("/survey-responses.csv")
def export_survey_responses(
    event_id: int | None = None,
    attendee_id: int | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> StreamingResponse:
    rows = db.execute(_response_query(db, event_id, attendee_id, search)).all()
    # Build a label map (question id -> prompt) from the events involved so the
    # CSV header reads like the survey, then a stable union of question columns.
    label_for: dict[str, str] = {}
    question_keys: list[str] = []
    for _result, _attendee, event in rows:
        for question in event.survey_questions or []:
            qid = str(question.get("id", ""))
            if qid and qid not in label_for:
                label_for[qid] = str(question.get("label") or question.get("prompt") or qid)
    for result, _attendee, _event in rows:
        for qid in (result.raw_payload or {}):
            if qid not in question_keys:
                question_keys.append(qid)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["Event", "Attendee", "Email", "Company", "Business Name / Location", "Completed at"]
        + [label_for.get(qid, qid) for qid in question_keys]
    )
    for result, attendee, event in rows:
        answers = result.raw_payload or {}
        writer.writerow(
            [
                event.title,
                attendee.full_name if attendee else "Anonymous",
                (attendee.email if attendee else None) or "",
                (attendee.company if attendee else None) or "",
                result.business_location or "",
                result.completed_at.isoformat() if result.completed_at else "",
            ]
            + [str(answers.get(qid, "")) for qid in question_keys]
        )
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=survey_responses.csv"},
    )


@router.get("/survey-insights", response_model=SurveyInsights)
def survey_insights(
    event_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> SurveyInsights:
    query = select(SurveyResult).where(SurveyResult.completed.is_(True))
    if event_id:
        query = query.where(SurveyResult.event_id == event_id)
    results = list(db.scalars(query))
    # Scale/choice answers ("Strongly Agree", ...) would swamp the free-text
    # word themes, so they are counted per question but kept out of the themes.
    event_ids = {result.event_id for result in results}
    choice_questions: set[tuple[int, str]] = set()
    if event_ids:
        for event in db.scalars(select(TrainingEvent).where(TrainingEvent.id.in_(event_ids))):
            for question in event.survey_questions or []:
                if question.get("type") == "choice":
                    choice_questions.add((event.id, str(question.get("id"))))
    answers: dict[str, list[str]] = defaultdict(list)
    words: Counter[str] = Counter()
    for result in results:
        for question, answer in (result.raw_payload or {}).items():
            text = str(answer).strip()
            if not text:
                continue
            answers[question].append(text)
            if (result.event_id, question) in choice_questions:
                continue
            words.update(
                word
                for word in re.findall(r"[a-zA-Z]{4,}", text.lower())
                if word not in STOP_WORDS
            )
    return SurveyInsights(
        response_count=len(results),
        answers_by_question=dict(answers),
        common_themes=[{"theme": word, "mentions": count} for word, count in words.most_common(10)],
        ai_summary=summarize_survey_answers(dict(answers)),
    )
