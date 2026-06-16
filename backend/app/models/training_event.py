from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class TrainingEvent(TimestampMixin, Base):
    __tablename__ = "training_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    event_date: Mapped[date] = mapped_column(Date, index=True)
    ceu_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("1.00"))
    location: Mapped[str | None] = mapped_column(String(255))
    presenter_name: Mapped[str | None] = mapped_column(String(255))
    course_instructor: Mapped[str | None] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(80), default="lunch_and_learn")
    post_test_url: Mapped[str | None] = mapped_column(String(1000))
    survey_mode: Mapped[str] = mapped_column(String(30), default="internal")
    survey_required: Mapped[bool] = mapped_column(Boolean, default=False)
    external_survey_url: Mapped[str | None] = mapped_column(String(1000))
    survey_token: Mapped[str | None] = mapped_column(String(120), unique=True, index=True)
    survey_questions: Mapped[list[dict]] = mapped_column(JSON, default=list)
    test_mode: Mapped[str] = mapped_column(String(30), default="external")
    test_token: Mapped[str | None] = mapped_column(String(120), unique=True, index=True)
    test_questions: Mapped[list[dict]] = mapped_column(JSON, default=list)
    certificate_title: Mapped[str] = mapped_column(String(255), default="Certificate of Completion")
    certificate_fields: Mapped[dict] = mapped_column(JSON, default=dict)
    certificate_template_path: Mapped[str | None] = mapped_column(String(500))
    certificate_template_version: Mapped[int] = mapped_column(Integer, default=1)
    certificate_template_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(50), default="draft", index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    assigned_presenter_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    created_by = relationship("User", foreign_keys=[created_by_id], back_populates="events")
    assigned_presenter = relationship("User", foreign_keys=[assigned_presenter_id])
    uploads = relationship("UploadedFile", back_populates="event", cascade="all, delete-orphan")
    event_attendees = relationship("EventAttendee", back_populates="event", cascade="all, delete-orphan")

    @property
    def assigned_presenter_name(self) -> str | None:
        return self.assigned_presenter.full_name if self.assigned_presenter else None
