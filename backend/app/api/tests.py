import io
from datetime import datetime, timezone
from decimal import Decimal

import qrcode
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.events import get_visible_event
from app.core.config import settings
from app.db.session import get_db
from app.models.test_result import TestResult
from app.models.training_event import TrainingEvent
from app.models.user import User
from app.schemas.common import PublicTestOut, PublicTestSubmission, TestSubmissionResult
from app.services.attendee_match import get_or_create_link, match_or_create_attendee
from app.services.audit import record_audit
from app.services.compliance import recalculate_event

router = APIRouter(tags=["Tests"])

PASSING_SCORE = Decimal("80")


def get_test_event(db: Session, token: str) -> TrainingEvent:
    event = db.scalar(select(TrainingEvent).where(TrainingEvent.test_token == token))
    if not event or event.test_mode != "internal":
        raise HTTPException(status_code=404, detail="Test not found")
    return event


@router.get("/public/tests/{token}", response_model=PublicTestOut)
def public_test(token: str, db: Session = Depends(get_db)) -> PublicTestOut:
    event = get_test_event(db, token)
    # Never expose the answer key to the public test page.
    questions = [
        {"id": question["id"], "prompt": question["prompt"], "choices": question["choices"]}
        for question in (event.test_questions or [])
    ]
    return PublicTestOut(
        event_title=event.title,
        event_date=event.event_date,
        presenter_name=event.presenter_name,
        questions=questions,
    )


@router.post("/public/tests/{token}", response_model=TestSubmissionResult)
def submit_public_test(
    token: str,
    payload: PublicTestSubmission,
    db: Session = Depends(get_db),
) -> TestSubmissionResult:
    event = get_test_event(db, token)
    questions = event.test_questions or []
    if not questions:
        raise HTTPException(status_code=409, detail="This test has no questions yet")

    correct = sum(
        1
        for question in questions
        if payload.answers.get(question["id"]) is not None
        and int(payload.answers[question["id"]]) == int(question.get("correct_index", -1))
    )
    score = Decimal(str(round(correct / len(questions) * 100, 2)))
    passed = score >= PASSING_SCORE

    attendee = match_or_create_attendee(db, payload.full_name, str(payload.email))
    link = get_or_create_link(db, event.id, attendee.id)
    result = db.scalar(
        select(TestResult).where(
            TestResult.event_id == event.id,
            TestResult.attendee_id == attendee.id,
        )
    )
    if not result:
        result = TestResult(event_id=event.id, attendee_id=attendee.id)
        db.add(result)
    result.score = score
    result.passed = passed
    result.completed_at = datetime.now(timezone.utc)
    result.raw_payload = {str(key): value for key, value in payload.answers.items()}

    link.test_completed = True
    link.test_score = score
    recalculate_event(db, event.id)
    db.flush()
    record_audit(
        db,
        "test.submitted",
        "test_result",
        result.id,
        None,
        event.id,
        {"attendee_id": attendee.id, "score": float(score), "passed": passed},
    )
    db.commit()
    return TestSubmissionResult(score=float(score), passed=passed, correct=correct, total=len(questions))


@router.get("/events/{event_id}/test-qr")
def test_qr(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    event = get_visible_event(db, event_id, current_user)
    if event.test_mode == "external" and event.post_test_url:
        url = event.post_test_url
    elif event.test_token:
        url = f"{settings.public_frontend_url}/?test={event.test_token}"
    else:
        raise HTTPException(
            status_code=409,
            detail="Add internal test questions or an external test URL first",
        )
    image = qrcode.make(url)
    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return StreamingResponse(output, media_type="image/png")
