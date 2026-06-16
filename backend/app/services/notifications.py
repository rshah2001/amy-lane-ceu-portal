import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.models.user import User
from app.services.emailer import send_simple_email

logger = logging.getLogger("app.notifications")


def notify_admins(
    db: Session,
    category: str,
    title: str,
    body: str | None = None,
    event_id: int | None = None,
    email: bool = False,
) -> list[Notification]:
    """Create a dashboard notification for every active admin, optionally emailing them.

    One row per admin keeps read-state per-admin. Email failures are logged but
    never block the originating action (e.g. a presenter's upload still succeeds).
    """
    admins = list(db.scalars(select(User).where(User.role == "admin", User.is_active.is_(True))))
    created: list[Notification] = []
    for admin in admins:
        notification = Notification(
            recipient_user_id=admin.id,
            category=category,
            title=title,
            body=body,
            event_id=event_id,
        )
        db.add(notification)
        created.append(notification)
        if email:
            try:
                send_simple_email(admin.email, title, body or title)
            except Exception as exc:  # noqa: BLE001 - alerts are best-effort
                logger.warning("Admin alert email to %s failed: %s", admin.email, exc)
    return created
