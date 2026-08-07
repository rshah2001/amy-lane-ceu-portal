from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default="presenter")
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Bumped every time a password is written (see password_reset.set_password).
    # Access tokens carry the value they were minted under, and app.api.deps
    # rejects any token whose value no longer matches -- that is what makes a
    # password change or reset end the sessions that were already open. Without
    # it a stolen token stayed usable for the full access_token_expire_minutes
    # after the victim changed the password precisely to stop it.
    #
    # Starts at 1, for existing rows too (server_default), so deploying this
    # signs nobody out: a token minted before the claim existed is read as
    # version 1 and still matches, until the next password change moves it.
    token_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1"), nullable=False
    )
    # Password reset, one outstanding request per user (a second request
    # replaces the first, which is what "I never got the email, send it again"
    # has to mean). Only the SHA-256 *hash* of the token is stored: unlike the
    # event tokens on TrainingEvent, which are printed on QR codes and are
    # public by design, this one is a credential -- anybody who can read this
    # column must not be able to take over the account. See
    # app.services.password_reset for how the pair is minted and consumed.
    password_reset_token_hash: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True
    )
    password_reset_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    events = relationship(
        "TrainingEvent",
        foreign_keys="TrainingEvent.created_by_id",
        back_populates="created_by",
    )

