from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin
from app.models.types import JSON


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
    # Secret embedded in this attendee's own invite email, so a public survey
    # submission can prove it came from that email rather than from anyone who
    # knows the address. Minted on first send and never rotated -- an invite
    # already sitting in an inbox has to keep working. Never serialized to any
    # API response: it is a per-person secret, not roster data. See
    # app.services.invites.
    invite_nonce: Mapped[str | None] = mapped_column(String(120), unique=True, index=True)
    # Set when the attendee self-checked-in via the public QR link; attendance
    # file re-imports must never clear attendance recorded this way.
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    event = relationship("TrainingEvent", back_populates="event_attendees")
    attendee = relationship("Attendee", back_populates="event_links")
    certificate = relationship("Certificate", back_populates="event_attendee", uselist=False)

