from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("training_events.id", ondelete="CASCADE"), index=True)
    uploaded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    file_type: Mapped[str] = mapped_column(String(50))
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(500))
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    parse_status: Mapped[str] = mapped_column(String(50), default="processed")
    parse_errors: Mapped[list] = mapped_column(JSON, default=list)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    event = relationship("TrainingEvent", back_populates="uploads")

