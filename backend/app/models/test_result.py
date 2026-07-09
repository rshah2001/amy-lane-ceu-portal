from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TestResult(Base):
    __tablename__ = "test_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("training_events.id", ondelete="CASCADE"), index=True)
    attendee_id: Mapped[int] = mapped_column(ForeignKey("attendees.id"))
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    passed: Mapped[bool] = mapped_column(Boolean)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    # "web" rows come from the public test page and survive file re-imports;
    # "upload" rows are replaced whenever a post-test file is uploaded again.
    source: Mapped[str] = mapped_column(String(10), default="upload", server_default="upload")

