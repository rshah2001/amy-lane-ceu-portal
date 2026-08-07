import io
from datetime import datetime, timezone
from decimal import Decimal

import qrcode
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.events import get_visible_event
from app.core.config import settings
from app.core.rate_limit import PublicRateLimit, client_ip
from app.db.session import get_db
from app.models.test_result import TestResult
from app.models.training_event import TrainingEvent
from app.models.user import User
from app.schemas.common import PublicTestOut, PublicTestSubmission, TestSubmissionResult
from app.services.attendee_match import get_or_create_link, match_or_create_attendee
from app.services.audit import record_audit
from app.services.compliance import recalculate_event
from app.services.invites import NONCE_MAX_LENGTH, link_for_nonce

router = APIRouter(tags=["Tests"])

PASSING_SCORE = Decimal("80")

# How many times one attendee may sit the public post-test for one event.
# Unlimited retakes turn a printed link into a brute-force answer key: with
# four choices per question, enough attempts always reach 100%.
MAX_PUBLIC_TEST_ATTEMPTS = 3
ATTEMPTS_EXHAUSTED_DETAIL = (
    f"You have used all {MAX_PUBLIC_TEST_ATTEMPTS} attempts at this post-test. "
    "Contact the course administrator if you need another."
)


def _credited_result(attempts: list[TestResult]) -> TestResult:
    """Which attempt counts, out of every attempt an attendee has on record.

    RETAKE POLICY -- deliberate choice, stated here because the behaviour is
    otherwise invisible: **the best attempt is the one credited.**

    Every submission is kept as its own ``test_results`` row (the history the
    upload path already wrote and the public path used to overwrite), and the
    score published on the event link is the highest of them. So a retake can
    only ever improve the record: scoring 40 after a 95 no longer revokes the
    pass, and the 95 is still there to show for it.

    Best-of-N was chosen over "first passing attempt" because the certificate
    reports a score, the number of attempts is capped, and the highest of a
    bounded set is both defensible to an accreditor and the answer an attendee
    expects. Ties resolve to the earliest attempt (``max`` keeps the first
    maximal element and the list is id-ordered), so the credited row is stable
    no matter how often this runs. Switching to first-passing-attempt is a
    change to this function alone.
    """
    return max(attempts, key=lambda attempt: Decimal(str(attempt.score)))


def _completion_basis(*, via_invite: bool) -> str:
    """Why a public post-test submission may credit the attendee it resolved to.

    Deliberately the same vocabulary as ``surveys._completion_basis`` -- an
    admin reading the audit trail should not have to learn two -- but only two
    of that function's three bases can arise here, and neither of them refuses:

    - ``invite_nonce``: the submission carried the secret from this attendee's
      own invite email (``?k=``), which nothing on the roster and no colleague
      who knows their address can produce. This is the only basis that is proof
      rather than plausibility, and it is the one the identity came *from* --
      the caller resolves the attendee by nonce, not by the form's name field.
    - ``email_on_submission``: no usable nonce, so the attendee is whoever
      ``match_or_create_attendee`` resolves the typed name and address to.
      Exactly what this endpoint did before nonces existed, and knowingly
      weaker: a registered address is not a secret. It stays because the
      printed QR sheet is one shared link for the whole room and has no nonce
      to offer -- it is a core feature, not a legacy path.

    The survey's third basis (``no_email_on_record``) and its refusal cannot
    occur here: ``PublicTestSubmission.email`` is mandatory, so a post-test
    submission always carries an address and there is never a name-only claim
    on somebody else's record to turn down. The consequence is stated plainly
    rather than hidden: on the nonce-less link, a known address still credits.
    """
    return "invite_nonce" if via_invite else "email_on_submission"


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
    _rate_limit: None = Depends(PublicRateLimit("test", "token")),
) -> TestSubmissionResult:
    # Public (QR-token) endpoint: rate limited per caller + token so the
    # printed link cannot be scripted into unlimited scored test results.
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

    # A nonce, when the link came from this attendee's own invite email. An
    # unrecognised one is treated as absent rather than refused: the fallback
    # credits nothing it would not have credited before, and a 4xx here would
    # throw away a sitting the attendee has already spent -- and there are only
    # three. Whether one was offered, and whether it resolved, is audited below.
    invited_link = link_for_nonce(db, event.id, k)
    submitted_email = str(payload.email)
    if invited_link is not None:
        # The nonce *is* the identity, so the form's name and email are not
        # consulted for matching at all -- the same rule the survey path uses,
        # and it carries more here: this endpoint writes a score, and
        # match_or_create_attendee would credit whatever address was typed.
        # A nickname also cannot fork a duplicate roster row this way. What was
        # typed is still recorded in the audit entry.
        attendee = invited_link.attendee
        link = invited_link
    else:
        attendee = match_or_create_attendee(db, event.id, payload.full_name, submitted_email)
        link = get_or_create_link(db, event.id, attendee.id)
    basis = _completion_basis(via_invite=invited_link is not None)
    previous = list(
        db.scalars(
            select(TestResult)
            .where(
                TestResult.event_id == event.id,
                TestResult.attendee_id == attendee.id,
            )
            .order_by(TestResult.id)
        )
    )
    # Only the attendee's own sittings count against the cap; rows imported
    # from a post-test file are the administrator's record, not their attempts.
    attempts_used = sum(1 for attempt in previous if attempt.source == "web")
    if attempts_used >= MAX_PUBLIC_TEST_ATTEMPTS:
        raise HTTPException(status_code=409, detail=ATTEMPTS_EXHAUSTED_DETAIL)

    # A new row per attempt: the history is the evidence behind the credited
    # score, and overwriting it is what let a retake erase a pass.
    result = TestResult(
        event_id=event.id,
        attendee_id=attendee.id,
        score=score,
        passed=passed,
        completed_at=datetime.now(timezone.utc),
        raw_payload={str(key): value for key, value in payload.answers.items()},
        source="web",
    )
    db.add(result)
    db.flush()

    credited = _credited_result([*previous, result])
    link.test_completed = True
    link.test_score = credited.score
    recalculate_event(db, event.id)
    db.flush()
    record_audit(
        db,
        "test.submitted",
        "test_result",
        result.id,
        None,
        event.id,
        {
            "attendee_id": attendee.id,
            "score": float(score),
            "passed": passed,
            "source": "public_web",
            "client_ip": client_ip(request),
            # What the form claimed, which on the nonce path is not what was
            # credited: the endpoint is unauthenticated, so the audit trail is
            # the only record of who claimed to be whom.
            "submitted_name": payload.full_name,
            "submitted_email": submitted_email,
            "attempt": attempts_used + 1,
            "attempts_allowed": MAX_PUBLIC_TEST_ATTEMPTS,
            "completion_basis": basis,
            # Both flags, not just the basis: a nonce that was offered and did
            # not resolve is the fingerprint of a stale or tampered link, and it
            # is invisible in `completion_basis` alone because the submission
            # quietly falls back to the older rules. The nonce value itself is
            # never written here -- it is a credential, and audit rows are read
            # by anyone who can read the audit log.
            "invite_nonce_presented": k is not None,
            "invite_nonce_valid": invited_link is not None,
            # What the event link now carries, which is not this attempt
            # whenever an earlier one scored higher (see _credited_result).
            "credited_result_id": credited.id,
            "credited_score": float(credited.score),
        },
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
    elif event.test_mode == "internal" and event.test_token and event.test_questions:
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
