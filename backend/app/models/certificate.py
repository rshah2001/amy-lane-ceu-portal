from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.types import JSON


class Certificate(Base):
    __tablename__ = "certificates"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_attendee_id: Mapped[int] = mapped_column(
        ForeignKey("event_attendees.id", ondelete="CASCADE"), unique=True
    )
    certificate_number: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    pdf_path: Mapped[str] = mapped_column(String(500))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    generated_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    template_version: Mapped[int] = mapped_column(default=1)
    event_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sent_to: Mapped[str | None] = mapped_column(String(255))
    # delivered_at requires a provider with delivery receipts (Gmail SMTP gives
    # none); kept for future use. downloaded_at is set when the holder fetches
    # their PDF through the public verification portal.
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    event_attendee = relationship("EventAttendee", back_populates="certificate")
    email_logs = relationship("CertificateEmailLog", back_populates="certificate", cascade="all, delete-orphan")
