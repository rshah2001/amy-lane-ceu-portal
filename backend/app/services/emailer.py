import base64
import json
import logging
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from app.core.config import settings
from app.models.training_event import TrainingEvent

logger = logging.getLogger("app.emailer")

RESEND_ENDPOINT = "https://api.resend.com/emails"


def _send_via_resend(recipient: str, subject: str, body: str, pdf_path: Path | None = None) -> str:
    """Send over Resend's HTTPS API (works where outbound SMTP is blocked, e.g. Render)."""
    if not settings.resend_api_key:
        raise RuntimeError("RESEND_API_KEY is required when EMAIL_DELIVERY_MODE is resend")
    payload: dict = {
        "from": settings.resend_from,
        "to": [recipient],
        "subject": subject,
        "text": body,
    }
    if pdf_path is not None:
        payload["attachments"] = [
            {"filename": pdf_path.name, "content": base64.b64encode(pdf_path.read_bytes()).decode()}
        ]
    request = urllib.request.Request(
        RESEND_ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {settings.resend_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Resend is behind Cloudflare, which 403s the default "Python-urllib"
            # User-Agent (error 1010). A normal UA passes.
            "User-Agent": "Mozilla/5.0 (compatible; CEU-Portal/1.0; +https://ceu-portal.vercel.app)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Resend API error {exc.code}: {detail}") from exc
    return result.get("id", f"resend-{uuid4()}")


def _send_via_smtp(recipient: str, subject: str, body: str, pdf_path: Path | None = None) -> str:
    if not settings.smtp_host:
        raise RuntimeError("SMTP_HOST is required when EMAIL_DELIVERY_MODE is smtp")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message.set_content(body)
    if pdf_path is not None:
        message.add_attachment(
            pdf_path.read_bytes(), maintype="application", subtype="pdf", filename=pdf_path.name
        )
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
        smtp.starttls()
        if settings.smtp_username and settings.smtp_password:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)
    return f"smtp-{uuid4()}"


def _deliver(recipient: str, subject: str, body: str, pdf_path: Path | None = None) -> str:
    """Route an email through the configured delivery mode: log / resend / smtp."""
    mode = settings.email_delivery_mode
    if mode == "log":
        logger.info(
            "[log mode] To: %s | Subject: %s%s",
            recipient,
            subject,
            f" | Attachment: {pdf_path.name}" if pdf_path else "",
        )
        return f"log-{uuid4()}"
    if mode == "resend":
        return _send_via_resend(recipient, subject, body, pdf_path)
    return _send_via_smtp(recipient, subject, body, pdf_path)


def send_simple_email(recipient: str, subject: str, body: str) -> str:
    """Public wrapper for plain-text notification emails (admin alerts, etc.)."""
    return _deliver(recipient, subject, body)


def _public_link(token_param: str, token: str, name: str, email: str) -> str:
    query = urlencode({token_param: token, "name": name, "email": email})
    return f"{settings.public_frontend_url}/?{query}"


def send_invite_email(event: TrainingEvent, attendee_name: str, recipient: str) -> str:
    """Email an attendee their personalized post-test and/or survey links."""
    actions: list[tuple[str, str]] = []
    if event.test_mode == "internal" and event.test_token:
        actions.append(("Complete your post-test", _public_link("test", event.test_token, attendee_name, recipient)))
    elif event.test_mode == "external" and event.post_test_url:
        actions.append(("Complete your post-test", event.post_test_url))
    if event.survey_mode == "internal" and event.survey_token:
        actions.append(("Complete the feedback survey", _public_link("survey", event.survey_token, attendee_name, recipient)))
    elif event.survey_mode == "external" and event.external_survey_url:
        actions.append(("Complete the feedback survey", event.external_survey_url))

    lines = [
        f"Hello {attendee_name},",
        "",
        f"Thank you for attending {event.title}. To receive your certificate of completion, "
        "please finish the following:",
        "",
    ]
    lines.extend(f"- {label}: {url}" for label, url in actions)
    lines.extend(["", "Thank you."])
    return _deliver(recipient, f"Action needed for your {event.title} certificate", "\n".join(lines))


def send_certificate_email(
    recipient: str,
    attendee_name: str,
    event_title: str,
    pdf_path: Path,
) -> str:
    subject = f"Your CEU certificate: {event_title}"
    body = f"Hello {attendee_name},\n\nYour certificate for {event_title} is attached.\n"
    return _deliver(recipient, subject, body, pdf_path)
