from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import SurveyTemplateUpdate
from app.services.audit import record_audit
from app.services.survey_template import get_survey_template, set_survey_template

router = APIRouter(prefix="/settings", tags=["Settings"])


@router.get("")
def get_settings(current_user: User = Depends(get_current_user)) -> dict:
    payload: dict = {
        "current_user": {
            "full_name": current_user.full_name,
            "email": current_user.email,
            "role": current_user.role,
        },
    }
    # Ops/environment configuration is admin-only; presenters get just their
    # own account details (their settings page shows nothing else anyway).
    if current_user.role == "admin":
        payload.update(
            organization=settings.certificate_issuer_name,
            retention_years=settings.retention_years,
            email_delivery_mode=settings.email_delivery_mode,
            smtp_configured=bool(settings.smtp_host),
            environment=settings.environment,
        )
    return payload


@router.get("/survey-template")
def read_survey_template(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    return {"questions": get_survey_template(db)}


@router.put("/survey-template")
def update_survey_template(
    payload: SurveyTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict:
    # Only future events are affected: each event copies the template when it
    # is created. An empty list resets back to the built-in defaults.
    questions = [question.model_dump() for question in payload.questions]
    set_survey_template(db, questions)
    record_audit(
        db,
        "settings.survey_template_updated",
        "app_setting",
        None,
        current_user,
        details={"question_count": len(questions)},
    )
    db.commit()
    return {"questions": get_survey_template(db)}
