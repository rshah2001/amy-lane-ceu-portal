from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


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
    test_questions: list[TestQuestionIn] | None = None
    survey_mode: str | None = None
    survey_required: bool | None = None
    external_survey_url: str | None = None
    certificate_title: str | None = None
    assigned_presenter_id: int | None = None
    survey_questions: list[dict] | None = None


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


class ApprovalRequest(BaseModel):
    event_attendee_ids: list[int]
    approved: bool = True
    # Admin escape hatch: approve even when the eligibility rules aren't met
    # (e.g. a paper post-test that was never uploaded). Audited per attendee.
    override: bool = False


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


class PublicSurveySubmission(BaseModel):
    full_name: str = Field(min_length=2, max_length=255)
    email: EmailStr
    answers: dict[str, str]


class SurveyResponseRow(BaseModel):
    id: int
    event_id: int
    event_title: str
    attendee_id: int
    full_name: str
    email: str | None
    company: str | None
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
    valid: bool
    certificate_number: str | None = None
    attendee_name: str | None = None
    event_title: str | None = None
    event_date: date | None = None
    ceu_hours: Decimal | None = None
    course_instructor: str | None = None
    generated_at: datetime | None = None
    status: str | None = None


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
