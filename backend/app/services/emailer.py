import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from app.core.config import settings
from app.models.training_event import TrainingEvent

logger = logging.getLogger("app.emailer")


def _deliver(recipient: str, subject: str, body: str) -> str:
    """Send a plain-text email, or write it to the server log in log mode."""
    message_id = f"log-{uuid4()}"
    if settings.email_delivery_mode == "log":
        logger.info("[log mode] To: %s | Subject: %s\n%s", recipient, subject, body)
        return message_id
    if not settings.smtp_host:
        raise RuntimeError("SMTP_HOST is required when EMAIL_DELIVERY_MODE is smtp")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
        smtp.starttls()
        if settings.smtp_username and settings.smtp_password:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)
    return message_id


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
    message_id = f"log-{uuid4()}"
    if settings.email_delivery_mode == "log":
        logger.info(
            "[log mode] To: %s | Subject: Your CEU certificate: %s | Attachment: %s",
            recipient, event_title, pdf_path.name,
        )
        return message_id
    if not settings.smtp_host:
        raise RuntimeError("SMTP_HOST is required when EMAIL_DELIVERY_MODE is smtp")

    message = EmailMessage()
    message["Subject"] = f"Your CEU certificate: {event_title}"
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message.set_content(
        f"Hello {attendee_name},\n\nYour certificate for {event_title} is attached.\n"
    )
    message.add_attachment(
        pdf_path.read_bytes(),
        maintype="application",
        subtype="pdf",
        filename=pdf_path.name,
    )
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
        smtp.starttls()
        if settings.smtp_username and settings.smtp_password:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)
    return message_id

