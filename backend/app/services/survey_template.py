"""Default survey questions new events are seeded with.

Admins edit the template on the Settings page; each event still gets its own
independent copy at creation time, so template changes never touch existing
events.
"""

from sqlalchemy.orm import Session

from app.models.app_setting import AppSetting

SURVEY_TEMPLATE_KEY = "survey_template"

DEFAULT_SURVEY_TEMPLATE = [
    {"id": "liked", "label": "What did you like about this course?", "type": "text", "options": []},
    {"id": "improve", "label": "What could we improve?", "type": "text", "options": []},
    {"id": "learned", "label": "What is one thing you learned?", "type": "text", "options": []},
]


def get_survey_template(db: Session) -> list[dict]:
    row = db.get(AppSetting, SURVEY_TEMPLATE_KEY)
    source = row.value if row and row.value else DEFAULT_SURVEY_TEMPLATE
    # Copies, so callers can assign the result to an event without aliasing
    # the stored template.
    return [dict(question) for question in source]


def set_survey_template(db: Session, questions: list[dict]) -> None:
    row = db.get(AppSetting, SURVEY_TEMPLATE_KEY)
    if row:
        row.value = questions
    else:
        db.add(AppSetting(key=SURVEY_TEMPLATE_KEY, value=questions))
