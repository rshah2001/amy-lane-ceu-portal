import base64
import json
import logging
import smtplib
import ssl
import urllib.error
import urllib.request
from datetime import datetime
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from app.core.config import settings
from app.models.training_event import TrainingEvent

logger = logging.getLogger("app.emailer")

# Connection/read timeout so a hung mail server cannot block a request forever.
SEND_TIMEOUT_SECONDS = 30
# Retry once on transient SMTP failures (dropped connections, timeouts).
# Permanent errors (bad credentials, refused recipients) fail immediately.
SMTP_MAX_ATTEMPTS = 2
_TRANSIENT_SMTP_ERRORS = (
    smtplib.SMTPServerDisconnected,
    smtplib.SMTPConnectError,
    smtplib.SMTPHeloError,
    ConnectionError,
    TimeoutError,
)

RESEND_ENDPOINT = "https://api.resend.com/emails"


def _read_pdf(pdf_path: Path) -> bytes:
    try:
        return pdf_path.read_bytes()
    except OSError as exc:
        raise RuntimeError(f"Certificate PDF is missing or unreadable: {pdf_path}") from exc


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
    if settings.reply_contact_email:
        payload["reply_to"] = [settings.reply_contact_email]
    if pdf_path is not None:
        payload["attachments"] = [
            {"filename": pdf_path.name, "content": base64.b64encode(_read_pdf(pdf_path)).decode()}
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
        with urllib.request.urlopen(request, timeout=SEND_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        logger.error("Resend send to %s failed: HTTP %s %s", recipient, exc.code, detail)
        raise RuntimeError(f"Resend API error {exc.code}: {detail}") from exc
    return result.get("id", f"resend-{uuid4()}")


def _build_message(recipient: str, subject: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message["Message-ID"] = make_msgid()
    # The sending mailbox is unmonitored; route any replies to a real person.
    if settings.reply_contact_email:
        message["Reply-To"] = settings.reply_contact_email
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
                settings.smtp_host, settings.smtp_port, timeout=SEND_TIMEOUT_SECONDS
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


def _send_via_smtp(recipient: str, subject: str, body: str, pdf_path: Path | None = None) -> str:
    message = _build_message(recipient, subject)
    message.set_content(body)
    if pdf_path is not None:
        message.add_attachment(
            _read_pdf(pdf_path), maintype="application", subtype="pdf", filename=pdf_path.name
        )
    return _smtp_send(message)


def _with_footer(body: str) -> str:
    """Append the do-not-reply footer every outgoing body carries."""
    footer = "\n\n--\nThis mailbox is not monitored — please do not reply to this email."
    if settings.reply_contact_email:
        footer += f"\nQuestions? Contact {settings.reply_contact_email}."
    return body + footer


def _deliver(recipient: str, subject: str, body: str, pdf_path: Path | None = None) -> str:
    """Route an email through the configured delivery mode: log / resend / smtp."""
    body = _with_footer(body)
    mode = settings.email_delivery_mode
    if mode == "log":
        logger.info(
            "[log mode] To: %s | Subject: %s%s\n%s",
            recipient,
            subject,
            f" | Attachment: {pdf_path.name}" if pdf_path else "",
            body,
        )
        return f"log-{uuid4()}"
    if mode == "resend":
        return _send_via_resend(recipient, subject, body, pdf_path)
    return _send_via_smtp(recipient, subject, body, pdf_path)


def send_simple_email(recipient: str, subject: str, body: str) -> str:
    """Public wrapper for plain-text notification emails (admin alerts, etc.)."""
    return _deliver(recipient, subject, body)


def _public_link(
    token_param: str, token: str, name: str, email: str, nonce: str | None = None
) -> str:
    params = {token_param: token, "name": name, "email": email}
    if nonce:
        # The one part of this URL that is not guessable from the roster: it is
        # what lets the survey endpoint tell "the attendee we emailed" apart
        # from "somebody who knows their address". See app.services.invites.
        params["k"] = nonce
    return f"{settings.public_frontend_url}/?{urlencode(params)}"


def send_invite_email(
    event: TrainingEvent,
    attendee_name: str,
    recipient: str,
    *,
    invite_nonce: str | None = None,
) -> str:
    """Email an attendee their personalized post-test and/or survey links.

    ``invite_nonce`` is this attendee's invite secret; when given it rides
    along on the survey link so their submission can be credited to them
    without them having to retype the address we already hold. Optional, so
    that a caller with no roster row (there is none today) still sends a
    working, if unprivileged, email.
    """
    actions: list[tuple[str, str]] = []
    # An internal test link is only worth sending once the test actually has
    # questions -- the same guard the check-in next-steps and the QR slide links
    # already apply. Without it the attendee lands on a submittable quiz with
    # nothing in it and no way to finish what the email asked for.
    if event.test_mode == "internal" and event.test_token and event.test_questions:
        actions.append(("Complete your post-test", _public_link("test", event.test_token, attendee_name, recipient)))
    elif event.test_mode == "external" and event.post_test_url:
        actions.append(("Complete your post-test", event.post_test_url))
    if event.survey_mode == "internal" and event.survey_token:
        actions.append(
            (
                "Complete the feedback survey",
                _public_link(
                    "survey", event.survey_token, attendee_name, recipient, invite_nonce
                ),
            )
        )
    elif event.survey_mode == "external" and event.external_survey_url:
        actions.append(("Complete the feedback survey", event.external_survey_url))

    if not actions:
        # "Please finish the following:" with nothing under it is a dead end for
        # the attendee and invisible to the admin. Refusing surfaces it as a
        # per-recipient failure in the distribution report instead.
        raise RuntimeError(
            "This event has no post-test or survey link to send yet — add internal "
            "questions or an external link before distributing."
        )

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


def send_password_reset_email(
    recipient: str, full_name: str, reset_url: str, expires_at: datetime
) -> str:
    """Send somebody the link that lets them set a new portal password.

    The link is the whole message. It is deliberately not accompanied by the
    old password, a temporary one, or any other credential -- there is nothing
    in this body that is worth anything after the link is used once.
    """
    hours = settings.password_reset_ttl_hours
    body = "\n".join(
        [
            f"Hello {full_name},",
            "",
            "A password reset was requested for your CEU portal account. "
            "Open the link below to choose a new password:",
            "",
            reset_url,
            "",
            f"The link can be used once and expires in {hours} hours "
            f"({expires_at:%Y-%m-%d %H:%M} UTC).",
            "",
            "If you did not ask for this, you can ignore this email — your "
            "password has not been changed.",
        ]
    )
    return _deliver(recipient, "Reset your CEU portal password", body)


def send_certificate_email(
    recipient: str,
    attendee_name: str,
    event_title: str,
    pdf_path: Path,
) -> str:
    subject = f"Your CEU certificate: {event_title}"
    body = f"Hello {attendee_name},\n\nYour certificate for {event_title} is attached."
    return _deliver(recipient, subject, body, pdf_path)
