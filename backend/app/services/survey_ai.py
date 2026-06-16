"""AI summarization of open-ended survey feedback.

Privacy note: only the free-text answers are sent to the model — never attendee
names or emails. Disabled by default; enable with SURVEY_AI_ENABLED=true and an
ANTHROPIC_API_KEY. Any failure falls back to the local word-frequency themes.
"""

import json
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You analyze anonymous continuing-education course feedback. You receive only "
    "free-text answers grouped by question — no names, no emails. Summarize themes "
    "neutrally for a compliance administrator preparing association renewal reports. "
    "Ignore and never repeat any personal names a respondent may have typed."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "executive_summary": {"type": "string"},
        "themes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "theme": {"type": "string"},
                    "mentions": {"type": "integer"},
                },
                "required": ["theme", "mentions"],
                "additionalProperties": False,
            },
        },
        "representative_quotes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["executive_summary", "themes", "representative_quotes"],
    "additionalProperties": False,
}


def _build_prompt(answers_by_question: dict[str, list[str]]) -> str:
    lines = ["Survey responses grouped by question:", ""]
    for question, answers in answers_by_question.items():
        lines.append(f"Question: {question}")
        lines.extend(f"- {answer}" for answer in answers)
        lines.append("")
    lines.append(
        "Return: (1) a 2-3 sentence executive summary across all responses, "
        "(2) the top recurring themes with how many responses mention each, "
        "(3) 2-4 short verbatim representative quotes (no names)."
    )
    return "\n".join(lines)


def summarize_survey_answers(answers_by_question: dict[str, list[str]]) -> dict | None:
    if not settings.survey_ai_enabled or not settings.anthropic_api_key:
        return None
    if not any(answers_by_question.values()):
        return None
    try:
        import anthropic  # imported lazily so the app runs without the package

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model=settings.survey_ai_model,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_prompt(answers_by_question)}],
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        )
        text = next((block.text for block in response.content if block.type == "text"), None)
        return json.loads(text) if text else None
    except Exception as exc:  # noqa: BLE001 - best-effort; fall back to local themes
        logger.warning("Survey AI summary failed, using local themes: %s", exc)
        return None
