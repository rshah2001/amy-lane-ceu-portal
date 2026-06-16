from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.config import settings
from app.db.session import get_db
from app.models.certificate import Certificate
from app.models.certificate_email_log import CertificateEmailLog
from app.models.training_event import TrainingEvent
from app.models.user import User
from app.schemas.common import SystemHealth

router = APIRouter(prefix="/system", tags=["System"])


def _dir_size(path) -> int:
    total = 0
    if path.exists():
        for entry in path.rglob("*"):
            if entry.is_file():
                try:
                    total += entry.stat().st_size
                except OSError:
                    continue
    return total


def _human(num: int) -> str:
    size = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TB"


@router.get("/health", response_model=SystemHealth)
def system_health(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> SystemHealth:
    storage_bytes = _dir_size(settings.storage_dir)
    total_certificates = db.scalar(select(func.count(Certificate.id))) or 0
    certificates_sent = db.scalar(
        select(func.count(Certificate.id)).where(Certificate.sent_at.is_not(None))
    ) or 0
    active_users = db.scalar(select(func.count(User.id)).where(User.is_active.is_(True))) or 0
    events_created = db.scalar(select(func.count(TrainingEvent.id))) or 0
    emails_sent = db.scalar(
        select(func.count(CertificateEmailLog.id)).where(CertificateEmailLog.status == "sent")
    ) or 0
    emails_failed = db.scalar(
        select(func.count(CertificateEmailLog.id)).where(CertificateEmailLog.status == "failed")
    ) or 0
    attempts = emails_sent + emails_failed
    success_rate = round(emails_sent / attempts * 100, 1) if attempts else 100.0
    return SystemHealth(
        storage_bytes=storage_bytes,
        storage_human=_human(storage_bytes),
        total_certificates=total_certificates,
        certificates_sent=certificates_sent,
        active_users=active_users,
        events_created=events_created,
        emails_sent=emails_sent,
        emails_failed=emails_failed,
        email_success_rate=success_rate,
    )
