from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CertificateEmailLog(Base):
    __tablename__ = "certificate_email_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    certificate_id: Mapped[int] = mapped_column(ForeignKey("certificates.id", ondelete="CASCADE"), index=True)
    recipient_email: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), default="sent")
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    error_message: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    certificate = relationship("Certificate", back_populates="email_logs")

