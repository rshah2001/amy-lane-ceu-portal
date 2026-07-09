import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from app.core.config import settings
from app.models.training_event import TrainingEvent

logger = logging.getLogger("app.emailer")

# Connection/read timeout so a hung SMTP server cannot block a request forever.
SMTP_TIMEOUT_SECONDS = 30
# Retry once on transient failures (dropped connections, timeouts). Permanent
# errors (bad credentials, refused recipients) fail immediately.
SMTP_MAX_ATTEMPTS = 2
_TRANSIENT_SMTP_ERRORS = (
    smtplib.SMTPServerDisconnected,
    smtplib.SMTPConnectError,
    smtplib.SMTPHeloError,
    ConnectionError,
    TimeoutError,
)


def _build_message(recipient: str, subject: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message["Message-ID"] = make_msgid()
    return message


def _smtp_send(message: EmailMessage) -> str:
    """Deliver a prepared message over SMTP; returns its Message-ID.

    Uses a connection timeout, verified TLS, and one retry on transient errors.
    """
    if not settings.smtp_host:
        raise RuntimeError("SMTP_HOST is required when EMAIL_DELIVERY_MODE is smtp")
    tls_context = ssl.create_default_context()
    last_error: Exception | None = None
    for attempt in range(1, SMTP_MAX_ATTEMPTS + 1):
        try:
            with smtplib.SMTP(
                settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS
            ) as smtp:
                smtp.starttls(context=tls_context)
                if settings.smtp_username and settings.smtp_password:
                    smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
            return message["Message-ID"]
        except _TRANSIENT_SMTP_ERRORS as exc:
            last_error = exc
            logger.warning(
                "SMTP send to %s failed on attempt %d/%d (%s: %s)",
                message["To"], attempt, SMTP_MAX_ATTEMPTS, type(exc).__name__, exc,
            )
        except (smtplib.SMTPException, OSError) as exc:
            logger.error(
                "SMTP send to %s via %s:%s failed permanently (%s: %s)",
                message["To"], settings.smtp_host, settings.smtp_port, type(exc).__name__, exc,
            )
            raise
    logger.error(
        "SMTP send to %s via %s:%s gave up after %d attempts: %s",
        message["To"], settings.smtp_host, settings.smtp_port, SMTP_MAX_ATTEMPTS, last_error,
    )
    raise last_error  # type: ignore[misc]  # loop always sets it before exiting


def _with_footer(body: str) -> str:
    """Append the do-not-reply footer every outgoing body carries."""
    footer = "\n\n--\nThis mailbox is not monitored — please do not reply to this email."
    if settings.reply_contact_email:
        footer += f"\nQuestions? Contact {settings.reply_contact_email}."
    return body + footer


def _deliver(recipient: str, subject: str, body: str) -> str:
    """Send a plain-text email, or write it to the server log in log mode."""
    body = _with_footer(body)
    if settings.email_delivery_mode == "log":
        logger.info("[log mode] To: %s | Subject: %s\n%s", recipient, subject, body)
        return f"log-{uuid4()}"
    message = _build_message(recipient, subject)
    message.set_content(body)
    return _smtp_send(message)


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
    body = _with_footer(f"Hello {attendee_name},\n\nYour certificate for {event_title} is attached.")
    if settings.email_delivery_mode == "log":
        logger.info(
            "[log mode] To: %s | Subject: Your CEU certificate: %s | Attachment: %s\n%s",
            recipient, event_title, pdf_path.name, body,
        )
        return f"log-{uuid4()}"

    try:
        pdf_bytes = pdf_path.read_bytes()
    except OSError as exc:
        raise RuntimeError(f"Certificate PDF is missing or unreadable: {pdf_path}") from exc

    message = _build_message(recipient, subject)
    message.set_content(body)
    message.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="pdf",
        filename=pdf_path.name,
    )
    return _smtp_send(message)
