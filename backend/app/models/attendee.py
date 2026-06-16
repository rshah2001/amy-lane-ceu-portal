from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class Attendee(TimestampMixin, Base):
    __tablename__ = "attendees"

    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str | None] = mapped_column(String(120))
    last_name: Mapped[str | None] = mapped_column(String(120))
    full_name: Mapped[str] = mapped_column(String(255), index=True)
    normalized_name: Mapped[str] = mapped_column(String(255), index=True)
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    normalized_email: Mapped[str | None] = mapped_column(String(255), index=True)
    company: Mapped[str | None] = mapped_column(String(255))
    license_number: Mapped[str | None] = mapped_column(String(120))

    event_links = relationship("EventAttendee", back_populates="attendee")

