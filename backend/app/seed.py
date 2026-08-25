import os
import secrets
from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app.core.config import settings
from app.core.security import get_password_hash
from app.db.session import SessionLocal
from app.models.training_event import TrainingEvent
from app.models.user import User
from app.services.audit import record_audit
from app.services.survey_template import get_survey_template


def upsert_user(db, email: str, full_name: str, role: str, password: str) -> tuple[User, bool]:
    user = db.scalar(select(User).where(User.email == email))
    if user:
        return user, False
    user = User(
        email=email,
        full_name=full_name,
        role=role,
        hashed_password=get_password_hash(password),
    )
    db.add(user)
    db.flush()
    return user, True


def _bootstrap_admin_password() -> str:
    # A fixed password is only acceptable for local development. In production
    # the bootstrap admin (needed after a fresh/reset database) gets the
    # SEED_ADMIN_PASSWORD env value, or a random one printed exactly once.
    configured = os.environ.get("SEED_ADMIN_PASSWORD")
    if configured:
        return configured
    if settings.environment == "production":
        return secrets.token_urlsafe(16)
    return "Admin123!"


def main() -> None:
    db = SessionLocal()
    try:
        # Bootstrap admin only. Presenters are added by an admin from the Users
        # page — the seed no longer creates a default presenter account.
        admin_password = _bootstrap_admin_password()
        admin, admin_created = upsert_user(
            db, "admin@example.com", "Avery Compliance", "admin", admin_password
        )
        if not db.scalar(
            select(TrainingEvent).where(
                TrainingEvent.title == "Comprehensive Automotive Mobility Solutions"
            )
        ):
            event = TrainingEvent(
                title="Comprehensive Automotive Mobility Solutions",
                description="NMEDA Lunch & Learn continuing education on automotive mobility solutions.",
                event_date=date(2026, 6, 4),
                ceu_hours=Decimal("1.00"),
                location="Virtual (Microsoft Teams)",
                presenter_name="Monique McGivney",
                course_instructor="Monique McGivney",
                certificate_title="Lunch & Learn Course",
                status="review",
                created_by_id=admin.id,
                assigned_presenter_id=None,
            )
            db.add(event)
            db.flush()
            record_audit(db, "seed.event_created", "training_event", event.id, admin, event.id)
        for event in db.scalars(select(TrainingEvent)):
            if not event.survey_token:
                event.survey_token = uuid4().hex
            if not event.test_token:
                event.test_token = uuid4().hex
            if not event.checkin_token:
                event.checkin_token = uuid4().hex
            if not event.survey_questions:
                event.survey_questions = get_survey_template(db)
        db.commit()
        print("Seed complete")
        if admin_created:
            # Printed once at creation so a fresh deployment isn't locked out;
            # change it immediately from the Users page.
            print(f"Bootstrap admin created: admin@example.com / {admin_password}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
