from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.user import User


def record_audit(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: int | None,
    actor: User | None,
    event_id: int | None = None,
    details: dict | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_id=actor.id if actor else None,
        event_id=event_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details or {},
    )
    db.add(entry)
    return entry

