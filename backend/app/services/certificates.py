import io
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from uuid import uuid4

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from app.core.config import settings
from app.models.certificate import Certificate
from app.models.event_attendee import EventAttendee
from app.services import storage

logger = logging.getLogger("app.certificates")

# Field placement tuned for the CAMS / NMEDA lunch & learn template (612x792 pt).
# Coordinates are PDF points from the bottom-left. Override per event via
# TrainingEvent.certificate_fields (same shape) to nudge for a different template.
DEFAULT_CERTIFICATE_FIELDS: dict[str, dict] = {
    "attendee_name": {"x": 306, "y": 462, "size": 21, "align": "center", "color": "#2f78b5", "font": "Helvetica-Bold"},
    "training_date": {"x": 306, "y": 388, "size": 15, "align": "center", "color": "#1b3a5b", "font": "Helvetica"},
    "course_instructor": {"x": 220, "y": 332, "size": 13, "align": "left", "color": "#2f78b5", "font": "Helvetica"},
}

# The NMEDA-branded CAMS Lunch & Learn PDF ships with the code, and it is the
# certificate NMEDA actually issues. It is therefore the default for any event
# that has not had its own template uploaded: without a default, an event
# created through the portal renders on the built-in generic design and the
# attendee receives a "Certificate of Completion" that is not NMEDA's
# certificate at all. There is no UI for uploading a per-event template, so
# every portal-created event hit that path.
BUNDLED_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "assets" / "cams_lunch_learn_cert.pdf"


def default_template_path() -> str | None:
    """The bundled branded template, or None if it is absent from the build."""
    return str(BUNDLED_TEMPLATE_PATH) if BUNDLED_TEMPLATE_PATH.is_file() else None


def effective_template_path(event) -> str | None:
    """The template an event renders on: its own upload, else the bundled one.

    Resolved at issue time rather than written onto the event row, so the
    default follows the deployment. The bundled asset's absolute path differs
    between a developer's machine and the server, and freezing one of those
    into the database is how an event ends up pointing at a file that does not
    exist in the environment that has to render it.
    """
    return event.certificate_template_path or default_template_path()


# ReportLab stamps a creation timestamp and a random document id into every PDF
# unless it is told to be invariant. A certificate of record has to re-issue
# byte-for-byte identically, so determinism wins over the (misleading anyway --
# it would show the re-render time) embedded timestamp. The issue time lives on
# the certificate row.
_INVARIANT = 1


def make_certificate_number(event_id: int) -> str:
    return f"CEU-{event_id:05d}-{uuid4().hex[:10].upper()}"


def _ordinal(day: int) -> str:
    suffix = "th" if 11 <= day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def format_training_date(value: date) -> str:
    return f"{value:%B} {_ordinal(value.day)}, {value:%Y}"


def _field_values(link: EventAttendee) -> dict[str, str]:
    event = link.event
    return {
        "attendee_name": link.attendee.full_name,
        "training_date": format_training_date(event.event_date),
        "course_instructor": event.course_instructor or event.presenter_name or "",
    }


@dataclass(frozen=True)
class CertificateContent:
    """Every input the renderer needs, detached from the live event row.

    A certificate is a record: once issued, the document must never change. The
    renderer therefore takes this value object rather than reading
    ``link.event.*``, so a re-issue can be driven from the snapshot stored on
    the certificate at issue time instead of from an event an admin may have
    edited since.
    """

    values: dict[str, str]
    event_title: str
    certificate_title: str
    ceu_hours: str
    template_path: str | None = None
    layout: dict = field(default_factory=dict)
    # "snapshot" when rebuilt from the issued record, "live" when read from the
    # current event row. Only ever "live" for a first issue, a preview, or a
    # pre-snapshot legacy certificate.
    source: str = "live"


def content_from_link(link: EventAttendee) -> CertificateContent:
    """Renderer inputs read from the event as it stands right now."""
    event = link.event
    return CertificateContent(
        values=_field_values(link),
        event_title=event.title,
        certificate_title=event.certificate_title,
        ceu_hours=str(event.ceu_hours),
        template_path=effective_template_path(event),
        layout=event.certificate_fields or {},
        source="live",
    )


def certificate_snapshot(link: EventAttendee) -> dict:
    """The immutable record of what a certificate says, stored at issue time.

    Anything the renderer reads has to be in here, or a re-issue would silently
    pick up a later edit to the event.
    """
    return {
        "event_title": link.event.title,
        "event_date": link.event.event_date.isoformat(),
        "presenter_name": link.event.presenter_name,
        "course_instructor": link.event.course_instructor,
        "ceu_hours": str(link.event.ceu_hours),
        "certificate_title": link.event.certificate_title,
        "template_version": link.event.certificate_template_version,
        "template_path": effective_template_path(link.event),
        # Field placement is part of the document's appearance, so it belongs in
        # the snapshot too. Snapshots written before this key existed fall back
        # to the event's current layout (see content_from_snapshot).
        "certificate_fields": link.event.certificate_fields or {},
        "fields": _field_values(link),
    }


def content_from_snapshot(snapshot: dict | None, fallback_layout: dict | None = None) -> CertificateContent | None:
    """Renderer inputs rebuilt from an issued certificate's snapshot.

    Returns None when the snapshot is missing or too incomplete to render from,
    which is the caller's cue to fall back to live data.
    """
    if not isinstance(snapshot, dict):
        return None
    values = snapshot.get("fields")
    if not isinstance(values, dict) or not values.get("attendee_name"):
        return None
    layout = snapshot.get("certificate_fields")
    if layout is None:
        # Pre-dates the layout being captured: the placement is not part of this
        # record, so the event's current layout is the only source for it. The
        # printed *values* still come from the snapshot.
        logger.info("Certificate snapshot has no stored field layout; using the event's current layout")
        layout = fallback_layout or {}
    return CertificateContent(
        # Every field the built-in design prints must be present, even as an
        # empty string, so a partial snapshot degrades to a blank line instead
        # of failing the re-issue outright.
        values={
            **dict.fromkeys(DEFAULT_CERTIFICATE_FIELDS, ""),
            **{key: str(value or "") for key, value in values.items()},
        },
        event_title=snapshot.get("event_title") or "",
        certificate_title=snapshot.get("certificate_title") or "Certificate of Completion",
        ceu_hours=str(snapshot.get("ceu_hours") or ""),
        template_path=snapshot.get("template_path"),
        layout=layout,
        source="snapshot",
    )


def _fitted_size(text: str, font: str, size: float, max_width: float) -> float:
    """Shrink a font size until the text fits, so long values (e.g. multiple
    presenter names on the instructor line) are never clipped off the page."""
    try:
        text_width = stringWidth(text, font, size)
    except KeyError:
        text_width = stringWidth(text, "Helvetica", size)
    if text_width <= max_width or text_width <= 0:
        return size
    return max(7.0, size * max_width / text_width)


def _watermark(canvas: Canvas, width: float, height: float) -> None:
    canvas.saveState()
    canvas.setFillColor(HexColor("#B42318"))
    canvas.setFillAlpha(0.16)
    canvas.setFont("Helvetica-Bold", 72)
    canvas.translate(width / 2, height / 2)
    canvas.rotate(30)
    canvas.drawCentredString(0, 0, "PREVIEW")
    canvas.restoreState()


def _draw_fields(
    canvas: Canvas,
    width: float,
    height: float,
    values: dict[str, str],
    layout: dict,
) -> None:
    for key, text in values.items():
        if not text:
            continue
        spec = {**DEFAULT_CERTIFICATE_FIELDS.get(key, {}), **(layout.get(key, {}) if layout else {})}
        # Per-event layout overrides are admin-entered JSON: fall back to safe
        # defaults on an unknown font or malformed color instead of failing the
        # whole certificate.
        font = spec.get("font", "Helvetica")
        size = spec.get("size", 14) or 14
        try:
            canvas.setFont(font, size)
        except (KeyError, ValueError, TypeError):
            logger.warning("Unknown certificate font %r for field %s; using Helvetica", spec.get("font"), key)
            font = "Helvetica"
            canvas.setFont(font, size)
        try:
            canvas.setFillColor(HexColor(spec.get("color", "#1b3a5b")))
        except (ValueError, TypeError):
            logger.warning("Invalid certificate color %r for field %s; using default", spec.get("color"), key)
            canvas.setFillColor(HexColor("#1b3a5b"))
        x = spec.get("x", width / 2)
        y = spec.get("y", height / 2)
        align = spec.get("align", "center")
        # Shrink long values (e.g. "Jane Doe & John Smith" on the instructor
        # line) so they stay inside the page instead of being clipped.
        margin = 24
        if align == "center":
            available = 2 * min(x, width - x) - margin
        elif align == "right":
            available = x - margin
        else:
            available = width - x - margin
        fitted = _fitted_size(text, font, size, max(40.0, available))
        if fitted != size:
            canvas.setFont(font, fitted)
        if align == "center":
            canvas.drawCentredString(x, y, text)
        elif align == "right":
            canvas.drawRightString(x, y, text)
        else:
            canvas.drawString(x, y, text)


def _overlay_on_pdf(
    template_path: str,
    values: dict[str, str],
    layout: dict,
    output_path: Path,
    preview: bool,
) -> Path:
    try:
        reader = PdfReader(template_path)
        if reader.is_encrypted:
            reader.decrypt("")
        if not reader.pages:
            raise ValueError("template has no pages")
        page = reader.pages[0]
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
    except Exception as exc:
        raise RuntimeError(
            f"Certificate PDF template could not be read ({template_path}): {exc}. "
            "Re-upload the template for this event."
        ) from exc

    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=(width, height), invariant=_INVARIANT)
    _draw_fields(canvas, width, height, values, layout)
    if preview:
        _watermark(canvas, width, height)
    canvas.save()
    buffer.seek(0)

    page.merge_page(PdfReader(buffer).pages[0])
    writer = PdfWriter()
    writer.add_page(page)
    with open(output_path, "wb") as handle:
        writer.write(handle)
    return output_path


def _legacy_certificate(
    content: CertificateContent,
    certificate_number: str,
    output_path: Path,
    preview: bool,
) -> Path:
    """Built-in landscape design used when no branded PDF template is uploaded."""
    values = content.values
    canvas = Canvas(str(output_path), pagesize=landscape(letter), invariant=_INVARIANT)
    width, height = landscape(letter)
    template_path = content.template_path
    # ensure_local is a plain existence check on local storage and re-fetches
    # the image from the bucket when the local copy was lost.
    if template_path and storage.ensure_local(Path(template_path)):
        try:
            canvas.drawImage(
                ImageReader(template_path), 0, 0, width=width, height=height, preserveAspectRatio=False, mask="auto"
            )
        except Exception as exc:
            raise RuntimeError(
                f"Certificate template image could not be read ({template_path}): {exc}. "
                "Re-upload the template for this event."
            ) from exc
    else:
        canvas.setFillColor(HexColor("#17324d"))
        canvas.rect(0, 0, width, height, fill=1, stroke=0)
        canvas.setFillColor(HexColor("#f7fafc"))
        canvas.rect(26, 26, width - 52, height - 52, fill=1, stroke=0)
        canvas.setStrokeColor(HexColor("#b58a3b"))
        canvas.setLineWidth(3)
        canvas.rect(42, 42, width - 84, height - 84, fill=0, stroke=1)

    canvas.setFillColor(HexColor("#17324d"))
    canvas.setFont("Helvetica-Bold", 30)
    canvas.drawCentredString(width / 2, height - 125, content.certificate_title.upper())
    canvas.setFont("Helvetica", 13)
    canvas.drawCentredString(width / 2, height - 165, "This certifies that")
    max_text_width = width - 120
    canvas.setFont("Helvetica-Bold", _fitted_size(values["attendee_name"], "Helvetica-Bold", 27, max_text_width))
    canvas.drawCentredString(width / 2, height - 215, values["attendee_name"])
    canvas.setFont("Helvetica", 13)
    canvas.drawCentredString(width / 2, height - 255, "successfully completed")
    canvas.setFont("Helvetica-Bold", _fitted_size(content.event_title, "Helvetica-Bold", 19, max_text_width))
    canvas.drawCentredString(width / 2, height - 292, content.event_title)
    canvas.setFont("Helvetica", 12)
    canvas.drawCentredString(width / 2, height - 328, f"{values['training_date']}  |  {content.ceu_hours} CEU hours")
    canvas.line(width / 2 - 130, 135, width / 2 + 130, 135)
    instructor_line = values["course_instructor"] or settings.certificate_issuer_name
    canvas.setFont("Helvetica", _fitted_size(instructor_line, "Helvetica", 11, max_text_width))
    canvas.drawCentredString(width / 2, 116, instructor_line)
    canvas.setFont("Helvetica", 9)
    canvas.drawString(58, 62, f"Certificate no. {certificate_number}")
    if preview:
        _watermark(canvas, width, height)
    canvas.save()
    return output_path


def render_certificate_pdf(
    content: CertificateContent,
    certificate_number: str,
    output_path: Path | None = None,
    preview: bool = False,
) -> Path:
    """Render a certificate from an explicit set of inputs (live or snapshot)."""
    output = output_path or settings.certificates_dir / f"{certificate_number}.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)
    template_path = content.template_path
    # A branded PDF template (e.g. the NMEDA cert) is stamped with the variable
    # fields; image templates and the no-template case use the built-in design.
    # ensure_local re-fetches the template from Supabase Storage if the local
    # copy was lost (ephemeral disk); with local-only storage it is a plain
    # existence check.
    if template_path and Path(template_path).suffix.lower() == ".pdf":
        if not storage.ensure_local(Path(template_path)) and Path(template_path).name == BUNDLED_TEMPLATE_PATH.name:
            # A snapshot (or a seeded row) written on another machine records
            # that machine's absolute path to the bundled template. The file
            # itself ships with the code, so recover it from the build rather
            # than falling through to a different design under the same
            # certificate number. Same bytes, same document.
            recovered = default_template_path()
            if recovered:
                logger.info(
                    "Certificate %s references the bundled template at %s, which is not present here; "
                    "rendering on the copy shipped with this build.",
                    certificate_number,
                    template_path,
                )
                template_path = recovered
        if storage.ensure_local(Path(template_path)):
            result = _overlay_on_pdf(template_path, content.values, content.layout, output, preview)
        else:
            # The document that was issued cannot be reproduced exactly without
            # its template, so say so loudly rather than quietly handing back a
            # differently-styled certificate under the same number.
            logger.error(
                "Certificate %s was issued on PDF template %s, which is missing from storage; "
                "falling back to the built-in design. The re-issued PDF will not match the original.",
                certificate_number,
                template_path,
            )
            result = _legacy_certificate(content, certificate_number, output, preview)
    else:
        result = _legacy_certificate(content, certificate_number, output, preview)
    if not preview:
        # Previews are throwaway; real certificates are mirrored to the
        # remote backend (no-op when only local storage is configured).
        storage.mirror_file(result)
    return result


def generate_certificate_pdf(
    link: EventAttendee,
    certificate_number: str,
    output_path: Path | None = None,
    preview: bool = False,
) -> Path:
    """Render from the event as it stands now.

    Correct for a first issue and for previews. Re-issuing an existing
    certificate must go through reissue_certificate_pdf instead.
    """
    return render_certificate_pdf(content_from_link(link), certificate_number, output_path, preview)


def reissue_certificate_pdf(
    link: EventAttendee,
    certificate: Certificate,
    output_path: Path | None = None,
) -> Path:
    """Rebuild an already-issued certificate's PDF.

    Renders from the snapshot taken at issue time, so the reproduced document is
    the one that was issued even if the event has been renamed, re-dated or
    re-instructored since. Certificate numbers are permanent references; two
    different documents must never share one.

    Only rows written before snapshots existed (or with an unusable snapshot)
    fall back to live event data, and that fallback is logged as a warning
    because the result is not guaranteed to match what the holder received.
    """
    content = content_from_snapshot(
        certificate.event_snapshot, fallback_layout=link.event.certificate_fields or {}
    )
    if content is None:
        logger.warning(
            "Certificate %s has no usable issue-time snapshot; re-rendering from the "
            "current event record. The result may differ from the document that was issued.",
            certificate.certificate_number,
        )
        content = content_from_link(link)
    return render_certificate_pdf(content, certificate.certificate_number, output_path)
