import csv
import io
from zipfile import BadZipFile
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from PIL import Image, ImageOps
import pytesseract
from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.models.attendee import Attendee
from app.models.event_attendee import EventAttendee
from app.models.survey_result import SurveyResult
from app.models.test_result import TestResult
from app.services.compliance import recalculate_event
from app.services.identity import humanize_name, normalize_email, normalize_name, split_name

ALIASES = {
    "full_name": ["full name", "name", "attendee", "participant name", "student name"],
    "first_name": ["first name", "firstname", "given name", "registration first name"],
    "last_name": ["last name", "lastname", "surname", "family name", "registration last name"],
    "email": ["email", "email address", "e-mail", "participant email", "registration email"],
    "company": ["company", "organization", "dealer", "employer"],
    "license_number": ["license number", "license", "credential id"],
    "score": ["score", "test score", "percentage", "percent", "grade"],
    "completed": ["completed", "complete", "submitted", "status"],
    "completed_at": ["completed at", "completion date", "submitted at", "timestamp"],
}


def _canonical_header(value: str) -> str:
    return " ".join(value.strip().lower().replace("_", " ").replace("-", " ").split())


def _value(row: dict[str, str], field: str) -> str | None:
    normalized = {_canonical_header(key): (value or "").strip() for key, value in row.items() if key}
    for alias in ALIASES[field]:
        if alias in normalized and normalized[alias]:
            return normalized[alias]
    return None


def _identity(row: dict[str, str]) -> dict[str, str | None]:
    first = _value(row, "first_name")
    last = _value(row, "last_name")
    full = _value(row, "full_name") or " ".join(value for value in [first, last] if value)
    if not full:
        raise ValueError("A name is required")
    full = humanize_name(full)
    split_first, split_last = split_name(full)
    return {
        "full_name": full,
        "first_name": first or split_first,
        "last_name": last or split_last,
        "email": _value(row, "email"),
        "company": _value(row, "company"),
        "license_number": _value(row, "license_number"),
    }


def _get_or_create_attendee(db: Session, data: dict[str, str | None]) -> Attendee:
    email = normalize_email(data["email"])
    name = normalize_name(data["full_name"])
    clauses = []
    if email:
        clauses.append(Attendee.normalized_email == email)
    if name:
        clauses.append(Attendee.normalized_name == name)
    attendee = db.scalar(select(Attendee).where(or_(*clauses)).order_by(Attendee.id)) if clauses else None
    if attendee:
        if not attendee.email and data["email"]:
            attendee.email = data["email"]
            attendee.normalized_email = email
        attendee.company = attendee.company or data["company"]
        attendee.license_number = attendee.license_number or data["license_number"]
        return attendee
    attendee = Attendee(
        first_name=data["first_name"],
        last_name=data["last_name"],
        full_name=data["full_name"] or "",
        normalized_name=name,
        email=data["email"],
        normalized_email=email,
        company=data["company"],
        license_number=data["license_number"],
    )
    db.add(attendee)
    db.flush()
    return attendee


def _get_or_create_link(db: Session, event_id: int, attendee: Attendee) -> EventAttendee:
    link = db.scalar(
        select(EventAttendee).where(
            EventAttendee.event_id == event_id,
            EventAttendee.attendee_id == attendee.id,
        )
    )
    if not link:
        link = EventAttendee(event_id=event_id, attendee_id=attendee.id)
        db.add(link)
        db.flush()
    return link


def _parse_score(value: str | None) -> Decimal:
    if value is None:
        raise ValueError("A post-test score is required")
    try:
        score = Decimal(value.replace("%", "").strip())
    except InvalidOperation as exc:
        raise ValueError(f"Invalid score: {value}") from exc
    if score < 0 or score > 100:
        raise ValueError("Post-test score must be between 0 and 100")
    return score


def _parse_completed(value: str | None) -> bool:
    if value is None:
        return True
    return value.strip().lower() not in {"false", "no", "n", "0", "incomplete", "not completed"}


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_csv_bytes(contents: bytes) -> list[dict[str, str]]:
    text = contents.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def _detect_header(rows: list[tuple]) -> int | None:
    """Find the header row: the first row with >=2 labels that names a person or email.

    Skips leading title/summary rows (e.g. Microsoft Teams "1. Summary" blocks).
    """
    for index, row in enumerate(rows):
        cells = [str(cell).strip() for cell in row if cell is not None and str(cell).strip()]
        if len(cells) < 2:
            continue
        canonical = [_canonical_header(cell) for cell in cells]
        if any("email" in cell or "name" in cell for cell in canonical):
            return index
    return None


def _records_from_rows(rows: list[tuple], header_index: int) -> list[dict[str, str]]:
    headers = [str(cell).strip() if cell is not None else "" for cell in rows[header_index]]
    records: list[dict[str, str]] = []
    for row in rows[header_index + 1 :]:
        record = {
            headers[index]: "" if cell is None else str(cell).strip()
            for index, cell in enumerate(row)
            if index < len(headers) and headers[index]
        }
        if any(value for value in record.values()):
            records.append(record)
    return records


def parse_xlsx_bytes(contents: bytes) -> list[dict[str, str]]:
    workbook = load_workbook(io.BytesIO(contents), read_only=True, data_only=True)
    # Real exports (e.g. Microsoft Teams) ship multiple sheets: a summary sheet
    # plus the attendee table. Choose the sheet whose header best identifies people.
    best: tuple[tuple[int, int, int], list[dict[str, str]]] | None = None
    for worksheet in workbook.worksheets:
        rows = list(worksheet.iter_rows(values_only=True))
        header_index = _detect_header(rows)
        if header_index is None:
            continue
        records = _records_from_rows(rows, header_index)
        if not records:
            continue
        canonical = [_canonical_header(str(cell)) for cell in rows[header_index] if cell]
        score = (
            sum("email" in cell for cell in canonical),
            sum("name" in cell for cell in canonical),
            len(records),
        )
        if best is None or score > best[0]:
            best = (score, records)
    return best[1] if best else []


def _split_ocr_line(line: str) -> list[str]:
    if "," in line:
        return next(csv.reader([line]))
    if "|" in line:
        return [part.strip() for part in line.split("|")]
    if "\t" in line:
        return [part.strip() for part in line.split("\t")]
    # Best-effort fallback for printed table scans. Commas/pipes produce better OCR.
    import re

    return [part.strip() for part in re.split(r"\s{2,}", line) if part.strip()]


def _parse_ocr_text(text: str) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return [], [{"row": 0, "message": "OCR found no readable text"}]

    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if any(alias in _canonical_header(line) for alias in ["email", "name", "score"])
        ),
        0,
    )
    headers = _split_ocr_line(lines[header_index])
    if len(headers) < 2:
        return [], [
            {
                "row": 0,
                "message": "OCR text was found, but a table header could not be detected. Use CSV/XLSX or a clearer comma-separated image.",
            }
        ]

    records: list[dict[str, str]] = []
    errors: list[dict[str, Any]] = [
        {
            "row": 0,
            "message": "Image OCR is best-effort. Review extracted rows before approving certificates.",
        }
    ]
    for row_number, line in enumerate(lines[header_index + 1 :], start=2):
        parts = _split_ocr_line(line)
        if len(parts) < len(headers):
            errors.append({"row": row_number, "message": f"OCR skipped low-confidence row: {line}"})
            continue
        records.append({header: parts[index] for index, header in enumerate(headers) if header})
    return records, errors


def parse_image_bytes(contents: bytes) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    try:
        image = Image.open(io.BytesIO(contents))
        image = ImageOps.autocontrast(ImageOps.grayscale(image))
        if image.width < 1400:
            scale = 1400 / image.width
            image = image.resize(
                (1400, max(1, round(image.height * scale))),
                Image.Resampling.LANCZOS,
            )
        text = pytesseract.image_to_string(image, config="--psm 6")
    except (OSError, pytesseract.TesseractError) as exc:
        raise ValueError(f"Image OCR failed: {exc}") from exc
    return _parse_ocr_text(text)


def parse_document_bytes(filename: str, contents: bytes) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        try:
            return parse_csv_bytes(contents), []
        except (csv.Error, UnicodeDecodeError) as exc:
            raise ValueError(f"Invalid CSV file: {exc}") from exc
    if suffix == ".xlsx":
        try:
            return parse_xlsx_bytes(contents), []
        except (BadZipFile, InvalidFileException, OSError, ValueError) as exc:
            raise ValueError(f"Invalid XLSX file: {exc}") from exc
    if suffix in {".png", ".jpg", ".jpeg"}:
        return parse_image_bytes(contents)
    raise ValueError("Supported uploads are CSV, XLSX, PNG, JPG, and JPEG")


def process_rows(
    db: Session,
    event_id: int,
    file_type: str,
    rows: list[dict[str, str]],
    extraction_errors: list[dict[str, Any]] | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = list(extraction_errors or [])
    if file_type == "registration":
        db.execute(update(EventAttendee).where(EventAttendee.event_id == event_id).values(registered=False))
    elif file_type == "attendance":
        db.execute(update(EventAttendee).where(EventAttendee.event_id == event_id).values(attended=False))
    if file_type == "post_test":
        db.execute(
            update(EventAttendee)
            .where(EventAttendee.event_id == event_id)
            .values(test_completed=False, test_score=None)
        )
        db.execute(delete(TestResult).where(TestResult.event_id == event_id))
    elif file_type == "survey":
        db.execute(
            update(EventAttendee)
            .where(EventAttendee.event_id == event_id)
            .values(survey_completed=False)
        )
        db.execute(delete(SurveyResult).where(SurveyResult.event_id == event_id))

    for row_number, row in enumerate(rows, start=2):
        try:
            identity = _identity(row)
            attendee = _get_or_create_attendee(db, identity)
            link = _get_or_create_link(db, event_id, attendee)
            if file_type == "registration":
                link.registered = True
            elif file_type == "attendance":
                link.attended = True
            elif file_type == "post_test":
                score = _parse_score(_value(row, "score"))
                link.test_completed = True
                link.test_score = score
                db.add(
                    TestResult(
                        event_id=event_id,
                        attendee_id=attendee.id,
                        score=score,
                        passed=score >= Decimal("80"),
                        completed_at=_parse_datetime(_value(row, "completed_at")),
                        raw_payload=row,
                    )
                )
            elif file_type == "survey":
                completed = _parse_completed(_value(row, "completed"))
                link.survey_completed = completed
                db.add(
                    SurveyResult(
                        event_id=event_id,
                        attendee_id=attendee.id,
                        completed=completed,
                        completed_at=_parse_datetime(_value(row, "completed_at")),
                        raw_payload=row,
                    )
                )
            else:
                raise ValueError(f"Unsupported file type: {file_type}")
        except ValueError as exc:
            errors.append({"row": row_number, "message": str(exc)})
    recalculate_event(db, event_id)
    return len(rows), errors


def process_document(
    db: Session,
    event_id: int,
    file_type: str,
    filename: str,
    contents: bytes,
) -> tuple[int, list[dict[str, Any]]]:
    rows, extraction_errors = parse_document_bytes(filename, contents)
    return process_rows(db, event_id, file_type, rows, extraction_errors)


def process_csv(
    db: Session,
    event_id: int,
    file_type: str,
    contents: bytes,
) -> tuple[int, list[dict[str, Any]]]:
    return process_rows(db, event_id, file_type, parse_csv_bytes(contents))


def save_upload(contents: bytes, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(contents)
