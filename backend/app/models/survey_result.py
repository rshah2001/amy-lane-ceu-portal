from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SurveyResult(Base):
    __tablename__ = "survey_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("training_events.id", ondelete="CASCADE"), index=True)
    attendee_id: Mapped[int] = mapped_column(ForeignKey("attendees.id"))
    completed: Mapped[bool] = mapped_column(Boolean, default=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)

