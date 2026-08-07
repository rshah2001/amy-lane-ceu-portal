from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(ORMModel):
    id: int
    # Plain str (not EmailStr) on output: input is already validated, and this
    # avoids 500s when older/test rows hold reserved-TLD addresses.
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    role: Literal["admin", "presenter"] = "presenter"
    password: str = Field(min_length=8, max_length=128)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    role: Literal["admin", "presenter"] | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
    is_active: bool | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TestQuestionIn(BaseModel):
    id: str
    prompt: str
    choices: list[str] = Field(min_length=2)
    correct_index: int = Field(ge=0)


class SurveyQuestionIn(BaseModel):
    id: str
    label: str = Field(min_length=1)
    # "text" renders a free-text box; "choice" renders one pick from options
    # (e.g. a Strongly Agree ... Strongly Disagree scale).
    type: Literal["text", "choice"] = "text"
    options: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_options(self) -> "SurveyQuestionIn":
        self.options = [option.strip() for option in self.options if option.strip()]
        if self.type == "choice" and len(self.options) < 2:
            raise ValueError("A multiple-choice survey question needs at least two options")
        return self


class SurveyTemplateUpdate(BaseModel):
    """Default survey questions for newly created events. An empty list
    resets the template to the built-in defaults."""

    questions: list[SurveyQuestionIn]


class EventCreate(BaseModel):
    title: str = Field(min_length=2, max_length=255)
    description: str | None = None
    event_date: date
    ceu_hours: Decimal = Field(default=Decimal("1.00"), gt=0)
    location: str | None = None
    presenter_name: str | None = None
    course_instructor: str | None = None
    event_type: str = "lunch_and_learn"
    post_test_url: str | None = None
    test_mode: str = "external"
    # Defaults to True so an event created without saying otherwise keeps
    # gating CEU credit on a passed post-test.
    test_required: bool = True
    test_questions: list[TestQuestionIn] = Field(default_factory=list)
    survey_mode: str = "internal"
    survey_required: bool = False
    external_survey_url: str | None = None
    certificate_title: str = "Certificate of Completion"
    assigned_presenter_id: int | None = None


class EventUpdate(BaseModel):
    """Partial update for an event: every field optional; only fields the
    client explicitly sends (``exclude_unset``) are applied."""

    title: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = None
    event_date: date | None = None
    ceu_hours: Decimal | None = Field(default=None, gt=0)
    location: str | None = None
    presenter_name: str | None = None
    course_instructor: str | None = None
    event_type: str | None = None
    post_test_url: str | None = None
    test_mode: str | None = None
    test_required: bool | None = None
    test_questions: list[TestQuestionIn] | None = None
    survey_mode: str | None = None
    survey_required: bool | None = None
    external_survey_url: str | None = None
    certificate_title: str | None = None
    assigned_presenter_id: int | None = None
    survey_questions: list[SurveyQuestionIn] | None = None
    # Admin override for the workflow stage, including moving an event out of
    # (or into) "completed" by hand.
    status: str | None = Field(default=None, pattern="^(draft|review|completed)$")


class EventOut(ORMModel):
    id: int
    title: str
    description: str | None
    event_date: date
    ceu_hours: Decimal
    location: str | None
    presenter_name: str | None
    course_instructor: str | None
    event_type: str
    post_test_url: str | None
    test_mode: str
    test_required: bool
    test_token: str | None
    checkin_token: str | None
    test_questions: list
    survey_mode: str
    survey_required: bool
    survey_questions: list
    external_survey_url: str | None
    survey_token: str | None
    certificate_title: str
    certificate_template_path: str | None
    certificate_template_version: int
    status: str
    created_by_id: int
    assigned_presenter_id: int | None
    assigned_presenter_name: str | None = None
    # Setup problems the admin UI should show loudly (e.g. a required post-test
    # that was never configured, which blocks every attendee).
    configuration_warnings: list[str] = Field(default_factory=list)
    created_at: datetime


class UploadedFileOut(ORMModel):
    id: int
    event_id: int
    file_type: str
    original_filename: str
    row_count: int
    parse_status: str
    parse_errors: list
    uploaded_at: datetime


class ComplianceRow(BaseModel):
    id: int
    attendee_id: int
    full_name: str
    email: str | None
    company: str | None
    registered: bool
    attended: bool
    test_completed: bool
    test_score: float | None
    survey_completed: bool
    has_valid_email: bool
    eligible: bool
    approved: bool
    compliance_status: str
    lifecycle_status: str
    eligibility_reasons: list[str]
    certificate_id: int | None = None
    certificate_number: str | None = None
    certificate_sent_at: datetime | None = None
    certificate_downloaded_at: datetime | None = None
    # Set once the certificate has been withdrawn. The row and its number are
    # kept for the retention period, so the UI has to be able to tell a live
    # certificate from a revoked one rather than inferring it from absence.
    certificate_revoked_at: datetime | None = None


class ApprovalRequest(BaseModel):
    event_attendee_ids: list[int]
    approved: bool = True
    # Admin escape hatch: approve even when the eligibility rules aren't met
    # (e.g. a paper post-test that was never uploaded). Audited per attendee.
    override: bool = False


class RosterRemovalResult(BaseModel):
    """Outcome of removing attendees from one event's roster."""

    removed: int
    # Attendees left in place because their certificate already reached them —
    # emailed, or downloaded by the holder from the public portal. Removing
    # those revokes a live credential, so it needs the include_sent override.
    kept_with_issued_certificates: list[str] = Field(default_factory=list)
    # Attendees whose certificate was revoked rather than deleted, because it
    # had reached them and is still inside the retention window. They are off
    # the roster in every sense that counts, but their record stays. Reported
    # separately from `removed` so the admin is told what actually happened.
    revoked: list[str] = Field(default_factory=list)


class ManualIssueRequest(BaseModel):
    """Admin-issued certificate for anyone, bypassing the eligibility rules."""

    full_name: str = Field(min_length=2, max_length=255)
    email: EmailStr
    send_email: bool = False


class CertificateOut(BaseModel):
    id: int
    event_attendee_id: int
    certificate_number: str
    generated_at: datetime
    sent_at: datetime | None
    last_sent_to: str | None
    template_version: int


class PublicCheckinOut(BaseModel):
    event_title: str
    event_date: date
    presenter_name: str | None
    location: str | None = None


class PublicCheckinSubmission(BaseModel):
    full_name: str = Field(min_length=2, max_length=255)
    email: EmailStr


class PublicSurveyOut(BaseModel):
    event_title: str
    event_date: date
    presenter_name: str | None
    questions: list[dict]


# Bounds for the anonymous survey payload. A real survey has a handful of
# questions and a paragraph-sized answer; anything past these limits is either
# a broken client or someone using the public form as free storage (the values
# are replayed into the admin CSV, the insights view, and the AI summariser).
MAX_SURVEY_ANSWERS = 50
MAX_SURVEY_ANSWER_LENGTH = 4000
MAX_SURVEY_QUESTION_ID_LENGTH = 100


class PublicSurveySubmission(BaseModel):
    # Surveys accept anonymous/blind feedback: every identity field is optional,
    # but a name that IS provided must still look like one (min 2 chars).
    business_location: str | None = Field(default=None, max_length=255)
    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    email: EmailStr | None = None
    answers: dict[str, str]

    @field_validator("answers")
    @classmethod
    def bound_answers(cls, value: dict[str, str]) -> dict[str, str]:
        """Cap how much an anonymous caller can push through the public form.

        Which question ids are *allowed* is checked in the endpoint, where the
        event's own question set is known; this only enforces the size limits.
        """
        if len(value) > MAX_SURVEY_ANSWERS:
            raise ValueError(f"A survey response may not carry more than {MAX_SURVEY_ANSWERS} answers")
        for question_id, answer in value.items():
            if len(question_id) > MAX_SURVEY_QUESTION_ID_LENGTH:
                raise ValueError("Survey question ids are limited to 100 characters")
            if len(answer) > MAX_SURVEY_ANSWER_LENGTH:
                raise ValueError(
                    f"Answer for {question_id!r} exceeds the "
                    f"{MAX_SURVEY_ANSWER_LENGTH}-character limit"
                )
        return value

    @field_validator("business_location", "full_name", "email", mode="before")
    @classmethod
    def blank_to_none(cls, value: object) -> object:
        """Treat blank/whitespace-only strings from the form as omitted."""
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class SurveyResponseRow(BaseModel):
    id: int
    event_id: int
    event_title: str
    attendee_id: int | None
    full_name: str | None
    email: str | None
    company: str | None
    business_location: str | None
    completed_at: datetime | None
    answers: dict


class SurveyInsights(BaseModel):
    response_count: int
    answers_by_question: dict[str, list[str]]
    common_themes: list[dict]
    ai_summary: dict | None = None


class PublicTestOut(BaseModel):
    event_title: str
    event_date: date
    presenter_name: str | None
    questions: list[dict]


class PublicTestSubmission(BaseModel):
    full_name: str = Field(min_length=2, max_length=255)
    email: EmailStr
    answers: dict[str, int]


class TestSubmissionResult(BaseModel):
    score: float
    passed: bool
    correct: int
    total: int


class DistributionResult(BaseModel):
    sent: int
    skipped: list[str]
    failed: list[str]


class DashboardStats(BaseModel):
    total_events: int
    upcoming_events: int
    pending_reviews: int
    certificates_sent: int
    compliance_rate: float


class EventSummary(BaseModel):
    event_id: int
    total_attendees: int
    registered: int
    attended: int
    test_passed: int
    survey_completed: int
    eligible: int
    approved: int
    certificates_generated: int
    certificates_sent: int
    compliance_rate: float


class ChartBucket(BaseModel):
    label: str
    value: int


class EventCompliancePoint(BaseModel):
    event_id: int
    title: str
    eligible: int
    total: int


class DashboardCharts(BaseModel):
    score_distribution: list[ChartBucket]
    events_compliance: list[EventCompliancePoint]
    monthly_certificates: list[ChartBucket]


class ReportColumn(BaseModel):
    key: str
    label: str


class AttendeeSearchRow(BaseModel):
    attendee_id: int
    full_name: str
    email: str | None
    company: str | None
    event_id: int
    event_title: str
    event_date: date
    eligible: bool
    approved: bool
    certificate_number: str | None


class BulkActionResult(BaseModel):
    action: str
    processed: int
    skipped: int
    failed: int
    details: list[str] = Field(default_factory=list)


class VerificationOut(BaseModel):
    """Public answer to "is this certificate real?".

    Three outcomes, not two: valid, revoked, and unknown. A revoked
    certificate comes back ``valid=False`` with ``status="revoked"`` and a
    ``revoked_at`` date, because somebody holding the PDF has to be told it no
    longer counts — "no certificate matches that number" would tell them the
    opposite of the truth.
    """

    valid: bool
    certificate_number: str | None = None
    attendee_name: str | None = None
    event_title: str | None = None
    event_date: date | None = None
    ceu_hours: Decimal | None = None
    course_instructor: str | None = None
    generated_at: datetime | None = None
    status: str | None = None
    revoked_at: datetime | None = None


class NotificationOut(ORMModel):
    id: int
    category: str
    title: str
    body: str | None
    event_id: int | None
    is_read: bool
    created_at: datetime


class SystemHealth(BaseModel):
    storage_bytes: int
    storage_human: str
    total_certificates: int
    certificates_sent: int
    active_users: int
    events_created: int
    emails_sent: int
    emails_failed: int
    email_success_rate: float
