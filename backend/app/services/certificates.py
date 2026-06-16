import io
from datetime import date
from pathlib import Path
from uuid import uuid4

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from app.core.config import settings
from app.models.event_attendee import EventAttendee

# Field placement tuned for the CAMS / NMEDA lunch & learn template (612x792 pt).
# Coordinates are PDF points from the bottom-left. Override per event via
# TrainingEvent.certificate_fields (same shape) to nudge for a different template.
DEFAULT_CERTIFICATE_FIELDS: dict[str, dict] = {
    "attendee_name": {"x": 306, "y": 462, "size": 21, "align": "center", "color": "#2f78b5", "font": "Helvetica-Bold"},
    "training_date": {"x": 306, "y": 388, "size": 15, "align": "center", "color": "#1b3a5b", "font": "Helvetica"},
    "course_instructor": {"x": 220, "y": 332, "size": 13, "align": "left", "color": "#2f78b5", "font": "Helvetica"},
}


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


def certificate_snapshot(link: EventAttendee) -> dict:
    return {
        "event_title": link.event.title,
        "event_date": link.event.event_date.isoformat(),
        "presenter_name": link.event.presenter_name,
        "course_instructor": link.event.course_instructor,
        "ceu_hours": str(link.event.ceu_hours),
        "certificate_title": link.event.certificate_title,
        "template_version": link.event.certificate_template_version,
        "template_path": link.event.certificate_template_path,
        "fields": _field_values(link),
    }


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
        canvas.setFont(spec.get("font", "Helvetica"), spec.get("size", 14))
        canvas.setFillColor(HexColor(spec.get("color", "#1b3a5b")))
        x = spec.get("x", width / 2)
        y = spec.get("y", height / 2)
        align = spec.get("align", "center")
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
    reader = PdfReader(template_path)
    page = reader.pages[0]
    width = float(page.mediabox.width)
    height = float(page.mediabox.height)

    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=(width, height))
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
    link: EventAttendee,
    certificate_number: str,
    values: dict[str, str],
    output_path: Path,
    preview: bool,
) -> Path:
    """Built-in landscape design used when no branded PDF template is uploaded."""
    canvas = Canvas(str(output_path), pagesize=landscape(letter))
    width, height = landscape(letter)
    template_path = link.event.certificate_template_path
    if template_path and Path(template_path).exists():
        canvas.drawImage(
            ImageReader(template_path), 0, 0, width=width, height=height, preserveAspectRatio=False, mask="auto"
        )
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
    canvas.drawCentredString(width / 2, height - 125, link.event.certificate_title.upper())
    canvas.setFont("Helvetica", 13)
    canvas.drawCentredString(width / 2, height - 165, "This certifies that")
    canvas.setFont("Helvetica-Bold", 27)
    canvas.drawCentredString(width / 2, height - 215, values["attendee_name"])
    canvas.setFont("Helvetica", 13)
    canvas.drawCentredString(width / 2, height - 255, "successfully completed")
    canvas.setFont("Helvetica-Bold", 19)
    canvas.drawCentredString(width / 2, height - 292, link.event.title)
    canvas.setFont("Helvetica", 12)
    canvas.drawCentredString(width / 2, height - 328, f"{values['training_date']}  |  {link.event.ceu_hours} CEU hours")
    canvas.line(width / 2 - 130, 135, width / 2 + 130, 135)
    canvas.setFont("Helvetica", 11)
    canvas.drawCentredString(width / 2, 116, values["course_instructor"] or settings.certificate_issuer_name)
    canvas.setFont("Helvetica", 9)
    canvas.drawString(58, 62, f"Certificate no. {certificate_number}")
    if preview:
        _watermark(canvas, width, height)
    canvas.save()
    return output_path


def generate_certificate_pdf(
    link: EventAttendee,
    certificate_number: str,
    output_path: Path | None = None,
    preview: bool = False,
) -> Path:
    output = output_path or settings.certificates_dir / f"{certificate_number}.pdf"
    values = _field_values(link)
    layout = link.event.certificate_fields or {}
    template_path = link.event.certificate_template_path
    # A branded PDF template (e.g. the NMEDA cert) is stamped with the variable
    # fields; image templates and the no-template case use the built-in design.
    if template_path and Path(template_path).suffix.lower() == ".pdf" and Path(template_path).exists():
        return _overlay_on_pdf(template_path, values, layout, output, preview)
    return _legacy_certificate(link, certificate_number, values, output, preview)
