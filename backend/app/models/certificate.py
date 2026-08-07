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
    # Revocation. An issued certificate inside its retention window is never
    # hard-deleted -- the attestation in docs/data-storage-and-retention-
    # confirmation.md commits to keeping it for seven years. Withdrawing it
    # (a certificate issued to the wrong person, say) sets these three columns
    # instead: the row, its PDF, its email logs and its audit trail all survive
    # until the retention purge removes them with everything else.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    revoked_reason: Mapped[str | None] = mapped_column(String(500))

    event_attendee = relationship("EventAttendee", back_populates="certificate")
    email_logs = relationship("CertificateEmailLog", back_populates="certificate", cascade="all, delete-orphan")

    @property
    def is_revoked(self) -> bool:
        """Withdrawn: it must not verify, be re-sent, or be handed out again."""
        return self.revoked_at is not None
