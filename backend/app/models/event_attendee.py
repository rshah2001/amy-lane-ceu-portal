from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class EventAttendee(TimestampMixin, Base):
    __tablename__ = "event_attendees"
    __table_args__ = (UniqueConstraint("event_id", "attendee_id", name="uq_event_attendee"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("training_events.id", ondelete="CASCADE"), index=True)
    attendee_id: Mapped[int] = mapped_column(ForeignKey("attendees.id"), index=True)
    registered: Mapped[bool] = mapped_column(Boolean, default=False)
    attended: Mapped[bool] = mapped_column(Boolean, default=False)
    test_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    test_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    survey_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    has_valid_email: Mapped[bool] = mapped_column(Boolean, default=False)
    eligible: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    eligibility_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    compliance_status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    invite_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    event = relationship("TrainingEvent", back_populates="event_attendees")
    attendee = relationship("Attendee", back_populates="event_links")
    certificate = relationship("Certificate", back_populates="event_attendee", uselist=False)

