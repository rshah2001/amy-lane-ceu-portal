from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from app.core.security import get_password_hash
from app.db.session import SessionLocal
from app.models.training_event import TrainingEvent
from app.models.user import User
from app.services.audit import record_audit

CAMS_TEMPLATE = Path(__file__).resolve().parent / "assets" / "cams_lunch_learn_cert.pdf"


def upsert_user(db, email: str, full_name: str, role: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user:
        return user
    user = User(
        email=email,
        full_name=full_name,
        role=role,
        hashed_password=get_password_hash(password),
    )
    db.add(user)
    db.flush()
    return user


def main() -> None:
    db = SessionLocal()
    try:
        # Bootstrap admin only. Presenters are added by an admin from the Users
        # page — the seed no longer creates a default presenter account.
        admin = upsert_user(db, "admin@example.com", "Avery Compliance", "admin", "Admin123!")
        template_path = str(CAMS_TEMPLATE) if CAMS_TEMPLATE.exists() else None
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
                certificate_template_path=template_path,
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
            if not event.certificate_template_path and template_path:
                event.certificate_template_path = template_path
            if not event.survey_questions:
                event.survey_questions = [
                    {"id": "liked", "label": "What did you like about this course?"},
                    {"id": "improve", "label": "What could we improve?"},
                    {"id": "learned", "label": "What is one thing you learned?"},
                ]
        db.commit()
        print("Seed complete")
        print("Admin: admin@example.com / Admin123!")
    finally:
        db.close()


if __name__ == "__main__":
    main()
