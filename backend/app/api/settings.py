from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.config import settings
from app.models.user import User

router = APIRouter(prefix="/settings", tags=["Settings"])


@router.get("")
def get_settings(current_user: User = Depends(get_current_user)) -> dict:
    return {
        "organization": settings.certificate_issuer_name,
        "retention_years": settings.retention_years,
        "email_delivery_mode": settings.email_delivery_mode,
        "smtp_configured": bool(settings.smtp_host),
        "environment": settings.environment,
        "current_user": {
            "full_name": current_user.full_name,
            "email": current_user.email,
            "role": current_user.role,
        },
    }

