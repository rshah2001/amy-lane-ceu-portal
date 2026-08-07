import csv
import io
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone

import qrcode
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.api.events import get_visible_event
from app.core.config import settings
from app.core.rate_limit import PublicRateLimit, client_ip
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
from app.services.csv_safe import csv_safe
from app.services.compliance import recalculate_event
from app.services.identity import normalize_email
from app.services.invites import NONCE_MAX_LENGTH, link_for_nonce
from app.services.survey_ai import summarize_survey_answers

router = APIRouter(tags=["Surveys"])
STOP_WORDS = {
    "about", "after", "again", "also", "and", "because", "course", "from",
    "have", "just", "more", "that", "the", "this", "very", "was", "were",
    "what", "with", "would", "your",
}


EMPTY_SUBMISSION_DETAIL = "Answer at least one survey question before submitting."


def _substantive_answers(answers: dict[str, str]) -> dict[str, str]:
    """The answers that actually say something.

    A form posted with every box left empty arrives as ``{"liked": "", ...}``,
    which is the same nothing as an empty payload -- neither may satisfy an
    event's ``survey_required`` gate, so emptiness is judged on the stripped
    values, not on whether keys are present.
    """
    return {
        question_id: answer
        for question_id, answer in answers.items()
        if str(answer).strip()
    }


def _unanswered_required(event: TrainingEvent, answered: dict[str, str]) -> list[str]:
    """Required question ids this submission left blank.

    ``required`` is read from the event's own stored question dicts. Nothing
    writes it today (``SurveyQuestionIn`` has no such field, so an admin cannot
    yet mark a question mandatory), which is exactly why it is honoured here:
    adding the flag to the schema and the event editor then needs no change to
    this endpoint. Until then the floor below -- at least one real answer --
    is what stands between a blank POST and a satisfied survey requirement.
    """
    return [
        str(question.get("id"))
        for question in event.survey_questions or []
        if question.get("required")
        and question.get("id") is not None
        and str(question.get("id")) not in answered
    ]


def _completion_basis(
    attendee: Attendee, submitted_email: str | None, *, via_invite: bool = False
) -> str | None:
    """Why (or why not) a public submission may credit this attendee's survey.

    The survey link is a shared secret printed on a slide: anyone holding it can
    post any name, and that name is matched to an attendee. Crediting every
    match lets one person satisfy another's survey requirement, so a submission
    that names an attendee who already carries an identity -- without carrying
    that identity itself -- records the response but leaves the flag alone.

    The three accepted bases, strongest first, and what each one is worth:

    - ``invite_nonce``: the submission carried the secret from this attendee's
      own invite email (``?k=``), which nothing on the roster and no colleague
      who knows their address can produce. This is the only basis that is proof
      rather than plausibility, and it is the one the identity came *from* --
      the caller resolves the attendee by nonce, not by the form's name field.
    - ``email_on_submission``: the submission carried an address, so
      ``match_or_create_attendee`` either resolved this attendee *by* that
      address (the submitter knew what is on the record) or resolved a record
      that had no address at all -- an email-bearing submission is only ever
      name-matched into an email-less row. Nothing else can be reached. Weaker
      than the nonce, and knowingly so: a registered address is not a secret.
      It survives because the QR sheet is a core feature and it is the only
      thing a walk-in with a printed link can offer.
    - ``no_email_on_record``: a name-only submission naming an attendee with no
      address on file. There is no identity to prove, and the survey flag alone
      hands nothing out: eligibility also requires a valid email.

    Returns the basis for crediting, or ``None`` when the submission may not.
    """
    if via_invite:
        return "invite_nonce"
    if submitted_email and normalize_email(submitted_email):
        return "email_on_submission"
    if not attendee.normalized_email:
        return "no_email_on_record"
    return None


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
    request: Request,
    k: str | None = Query(
        default=None,
        max_length=NONCE_MAX_LENGTH,
        description=(
            "Invite nonce from this attendee's own invitation email. Present on "
            "emailed links only; the shared QR link has none and does not need one."
        ),
    ),
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(PublicRateLimit("survey", "token")),
) -> dict:
    # Public (QR-token) endpoint: rate limited per caller + token, and the
    # answer payload is bounded both in the schema (count and per-value length)
    # and here, against this event's own question set.
    event = get_survey_event(db, token)
    # Answers may only address questions this event actually asks: the payload
    # is otherwise an anonymous key/value store that shows up verbatim in the
    # admin CSV and the insights view.
    known_ids = {
        str(question.get("id"))
        for question in event.survey_questions or []
        if question.get("id") is not None
    }
    if known_ids:
        unknown = sorted(set(payload.answers) - known_ids)
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown survey question(s): {', '.join(unknown[:5])}",
            )
    # An event with no configured questions (legacy/seeded rows) has nothing to
    # validate against; those submissions are still bounded by the schema caps.
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
    # A submission has to actually answer something to count. Without this an
    # empty POST marked survey_completed, so an event configured with
    # survey_required was satisfied by a request carrying no feedback at all.
    # This is about empty *answers* only -- name and email stay optional, and
    # anonymous submissions are unaffected.
    answered = _substantive_answers(payload.answers)
    if not answered:
        raise HTTPException(status_code=422, detail=EMPTY_SUBMISSION_DETAIL)
    missing = _unanswered_required(event, answered)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Please answer the required question(s): {', '.join(missing[:5])}",
        )
    # A nonce, when the link came from this attendee's own invite email. An
    # unrecognised one is treated as absent rather than refused: the fallback
    # credits nothing it would not have credited before, and rejecting would
    # throw away real feedback over a link an email client mangled. Whether one
    # was offered, and whether it resolved, is audited below.
    invited_link = link_for_nonce(db, event.id, k)
    # Name and email are both optional: with neither, the response is stored
    # anonymously (no attendee linked); with either one, we match/create an
    # attendee from whatever identity was given, as before.
    submitted_email = str(payload.email) if payload.email else None
    attendee = None
    if invited_link is not None:
        # The nonce *is* the identity, so the form's name and email are not
        # consulted for matching at all. Two reasons: a link only its owner
        # received should not need them retyped correctly, and letting a
        # nonce-bearing submission also match/create some other attendee would
        # scatter duplicate roster rows every time someone typed a nickname.
        # What was typed is still recorded in the audit entry.
        attendee = invited_link.attendee
    elif payload.full_name or payload.email:
        attendee = match_or_create_attendee(
            db,
            event.id,
            payload.full_name or "",
            submitted_email,
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
    basis = (
        _completion_basis(attendee, submitted_email, via_invite=invited_link is not None)
        if attendee
        else None
    )
    # A submission that named someone else's record: kept, linked, but not
    # allowed to move their compliance state (see _completion_basis).
    refused = attendee is not None and basis is None
    if attendee:
        link = invited_link or get_or_create_link(db, event.id, attendee.id)
        if basis:
            link.survey_completed = True
    db.flush()
    recalculate_event(db, event.id)
    # Every public submission is audited with where it came from: the endpoint
    # is unauthenticated, so the audit trail is the only record of who claimed
    # to be whom, and of whether that claim moved anyone's compliance state.
    caller = client_ip(request)
    record_audit(
        db,
        "survey.submitted",
        "survey_result",
        result.id,
        None,
        event.id,
        {
            "attendee_id": attendee.id if attendee else None,
            "source": "public_web",
            "client_ip": caller,
            "submitted_name": payload.full_name,
            "submitted_email": submitted_email,
            "answered": len(answered),
            "survey_completed": bool(basis),
            "completion_basis": basis,
            # Both flags, not just the basis: a nonce that was offered and did
            # not resolve is the fingerprint of a stale or tampered link, and it
            # is invisible in `completion_basis` alone because the submission
            # quietly falls back to the older rules.
            "invite_nonce_presented": k is not None,
            "invite_nonce_valid": invited_link is not None,
        },
    )
    if refused:
        # Its own action so an admin can find impersonation attempts without
        # reading every submission: someone named an attendee who already has
        # an identity on file, and did not submit that identity.
        record_audit(
            db,
            "survey.completion_refused",
            "attendee",
            attendee.id,
            None,
            event.id,
            {
                "reason": "named_an_existing_identity_without_proving_it",
                "source": "public_web",
                "client_ip": caller,
                "submitted_name": payload.full_name,
                "submitted_email": submitted_email,
                # This entry is meant to be readable on its own, so it repeats
                # the nonce flags: a refusal that *did* carry a nonce means the
                # nonce did not resolve, which is what a stale or edited link
                # looks like -- a different thing from no nonce at all.
                "invite_nonce_presented": k is not None,
            },
        )
    db.commit()
    if refused:
        # The response is kept either way -- it is real feedback -- but the
        # submitter is told it was not counted, otherwise an attendee who is on
        # the roster with an email and types only their name is silently left
        # short of their certificate. The extra keys are only present on this
        # path, so the success contract ({"status": "submitted"}) is unchanged.
        return {
            "status": "submitted",
            "credited": False,
            "message": (
                "Thanks -- your feedback was recorded. To have it counted towards "
                "your certificate, submit it again using the email address you "
                "registered with."
            ),
        }
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
    # The six fixed headers are ours and go out verbatim; the question labels
    # are admin-authored (and fall back to submitted answer keys), so they are
    # neutralized like any other non-hardcoded cell. Every data cell below is
    # user-derived -- the survey is a public, unauthenticated form -- so all of
    # them run through csv_safe to keep formulas out of the admin's Excel.
    writer.writerow(
        ["Event", "Attendee", "Email", "Company", "Business Name / Location", "Completed at"]
        + [csv_safe(label_for.get(qid, qid)) for qid in question_keys]
    )
    for result, attendee, event in rows:
        answers = result.raw_payload or {}
        writer.writerow(
            [
                csv_safe(event.title),
                csv_safe(attendee.full_name if attendee else "Anonymous"),
                csv_safe((attendee.email if attendee else None) or ""),
                csv_safe((attendee.company if attendee else None) or ""),
                csv_safe(result.business_location or ""),
                csv_safe(result.completed_at.isoformat() if result.completed_at else ""),
            ]
            + [csv_safe(answers.get(qid, "")) for qid in question_keys]
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
