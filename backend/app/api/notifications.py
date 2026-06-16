from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.models.notification import Notification
from app.models.user import User
from app.schemas.common import NotificationOut

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    unread_only: bool = False,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> list[Notification]:
    query = select(Notification).where(Notification.recipient_user_id == current_user.id)
    if unread_only:
        query = query.where(Notification.is_read.is_(False))
    query = query.order_by(Notification.created_at.desc()).limit(max(1, min(limit, 200)))
    return list(db.scalars(query))


@router.get("/unread-count")
def unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict:
    count = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.recipient_user_id == current_user.id,
            Notification.is_read.is_(False),
        )
    )
    return {"unread": count or 0}


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Notification:
    notification = db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.recipient_user_id == current_user.id,
        )
    )
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.is_read = True
    db.commit()
    db.refresh(notification)
    return notification


@router.post("/read-all")
def mark_all_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict:
    result = db.execute(
        update(Notification)
        .where(
            Notification.recipient_user_id == current_user.id,
            Notification.is_read.is_(False),
        )
        .values(is_read=True)
    )
    db.commit()
    return {"marked_read": result.rowcount or 0}
