from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.types import JSON


class SurveyResult(Base):
    __tablename__ = "survey_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("training_events.id", ondelete="CASCADE"), index=True)
    # Nullable: public surveys may be submitted anonymously (no name/email).
    attendee_id: Mapped[int | None] = mapped_column(ForeignKey("attendees.id"))
    # Optional free-text "Business Name / Location" captured on the public form.
    business_location: Mapped[str | None] = mapped_column(String(255))
    completed: Mapped[bool] = mapped_column(Boolean, default=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    # "web" rows come from the public survey page and survive file re-imports;
    # "upload" rows are replaced whenever a survey file is uploaded again.
    source: Mapped[str] = mapped_column(String(10), default="upload", server_default="upload")

