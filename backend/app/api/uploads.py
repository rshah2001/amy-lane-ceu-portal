from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_user
from app.api.events import get_visible_event
from app.core.config import settings
from app.db.session import get_db
from app.models.uploaded_file import UploadedFile
from app.models.user import User
from app.schemas.common import UploadedFileOut
from app.services.audit import record_audit
from app.services import storage
from app.services.csv_import import (
    SCORE_BASES,
    SHEET_FORMATS,
    EmptyImportError,
    looks_like_csv_text,
    process_document,
    save_upload,
)
from app.services.notifications import notify_admins

router = APIRouter(prefix="/events/{event_id}/uploads", tags=["Uploads"])
FILE_TYPES = {"registration", "attendance", "post_test", "survey"}
ALLOWED_SUFFIXES = {".csv", ".xlsx", ".png", ".jpg", ".jpeg", ".pdf", ".docx"}
ALLOWED_FORMATS_LABEL = "CSV, XLSX, PDF, DOCX, PNG, JPG, or JPEG"
# Largest upload we accept. Deliberately a module constant rather than a
# request-time surprise: the body is refused before it is read into memory.
# TODO: graduate this to a config setting (config.py is owned elsewhere today).
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_UPLOAD_LABEL = "15 MB"
# Reading the body in chunks lets an oversized upload be cut off after one
# chunk past the limit instead of after the whole file is in memory.
UPLOAD_CHUNK_BYTES = 1024 * 1024
MEDIA_TYPES = {
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def _content_matches_suffix(suffix: str, contents: bytes) -> bool:
    """Verify the file's magic bytes match its claimed extension."""
    if suffix == ".png":
        return contents.startswith(b"\x89PNG\r\n\x1a\n")
    if suffix in {".jpg", ".jpeg"}:
        return contents.startswith(b"\xff\xd8\xff")
    if suffix == ".pdf":
        return contents.startswith(b"%PDF")
    if suffix in {".xlsx", ".docx"}:
        # XLSX and DOCX files are ZIP archives.
        return contents.startswith(b"PK\x03\x04")
    if suffix == ".csv":
        # Delegated to the importer so the gate accepts exactly what the
        # importer can read: Excel still writes cp1252 and UTF-16 CSVs, and
        # rejecting them here made the API refuse files it parses correctly.
        return looks_like_csv_text(contents)
    return False


async def _read_within_limit(request: Request, file: UploadFile) -> bytes:
    """Read the upload, refusing anything over the size limit as early as possible.

    A declared Content-Length is checked before a single byte is read; without
    one, the stream is cut off as soon as it passes the limit. Either way an
    oversized file never reaches the parser, which for an image would mean
    minutes of OCR before the rejection.
    """
    declared = request.headers.get("content-length")
    # Content-Length covers the multipart framing too, so allow a little slack
    # and let the exact check below decide for a file near the limit.
    if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES + 65536:
        raise HTTPException(
            status_code=413, detail=f"Upload exceeds the {MAX_UPLOAD_LABEL} limit"
        )
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(UPLOAD_CHUNK_BYTES):
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413, detail=f"Upload exceeds the {MAX_UPLOAD_LABEL} limit"
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.get("", response_model=list[UploadedFileOut])
def list_uploads(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[UploadedFile]:
    get_visible_event(db, event_id, current_user)
    return list(
        db.scalars(
            select(UploadedFile)
            .where(UploadedFile.event_id == event_id)
            .order_by(UploadedFile.uploaded_at.desc())
        )
    )


@router.get("/{upload_id}/download")
def download_upload(
    event_id: int,
    upload_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    """Stream back the original uploaded document (same visibility as listing)."""
    get_visible_event(db, event_id, current_user)
    upload = db.scalar(
        select(UploadedFile).where(
            UploadedFile.id == upload_id,
            UploadedFile.event_id == event_id,
        )
    )
    # ensure_local restores the file from Supabase Storage (when configured)
    # if the local cache copy was lost, e.g. after an ephemeral-disk restart.
    if not upload or not storage.ensure_local(Path(upload.storage_path)):
        raise HTTPException(status_code=404, detail="Uploaded file not found")
    suffix = Path(upload.original_filename).suffix.lower()
    fallback = Path(upload.original_filename).name.encode("ascii", "replace").decode("ascii").replace('"', "'")
    disposition = (
        f'attachment; filename="{fallback}"; '
        f"filename*=UTF-8''{quote(Path(upload.original_filename).name)}"
    )
    return FileResponse(
        upload.storage_path,
        media_type=MEDIA_TYPES.get(suffix, "application/octet-stream"),
        headers={"Content-Disposition": disposition},
    )


@router.post("/{file_type}", response_model=UploadedFileOut, status_code=201)
async def upload_document(
    request: Request,
    event_id: int,
    file_type: str,
    file: UploadFile = File(...),
    sheet_format: str | None = Form(None),
    score_basis: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UploadedFile:
    event = get_visible_event(db, event_id, current_user)
    if file_type not in FILE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid file type")
    # Optional hint describing what kind of sheet this is; steers parsing.
    if sheet_format and sheet_format not in SHEET_FORMATS:
        raise HTTPException(status_code=400, detail="Invalid sheet format")
    # Optional statement of what a bare post-test score means. Same shape as
    # the sheet-format hint: when it is absent the importer infers per column
    # and refuses to guess rather than picking a unit.
    if score_basis and score_basis not in SCORE_BASES:
        raise HTTPException(status_code=400, detail="Invalid score basis")
    if current_user.role != "admin" and file_type != "attendance":
        raise HTTPException(
            status_code=403,
            detail="Presenters can only upload the attendance / sign-in sheet",
        )
    suffix = Path(file.filename).suffix.lower() if file.filename else ""
    if not file.filename or suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"Upload a {ALLOWED_FORMATS_LABEL} file")
    contents = await _read_within_limit(request, file)
    if not contents or not _content_matches_suffix(suffix, contents):
        raise HTTPException(
            status_code=400,
            detail=f"File content does not match its extension; upload a valid {ALLOWED_FORMATS_LABEL} file",
        )

    destination = settings.uploads_dir / str(event_id) / f"{uuid4().hex}-{Path(file.filename).name}"
    # Everything below here is synchronous and slow — OCR on a scanned sign-in
    # sheet runs for minutes — so it must not run on the event loop. On a
    # single worker that would freeze every other request, health checks
    # included, for the whole duration of one upload.
    await run_in_threadpool(save_upload, contents, destination)
    try:
        row_count, errors = await run_in_threadpool(
            process_document,
            db,
            event_id,
            file_type,
            file.filename,
            contents,
            sheet_format,
            score_basis,
        )
    except EmptyImportError as exc:
        # Nothing was imported, so nothing was replaced (process_rows rolls the
        # reset back). Say so with a 400: reporting 201 for an upload that
        # changed nothing is how a mistyped file "succeeded" while wiping an
        # event's scores.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Unable to extract rows: {exc}") from exc
    # Row-level notices ("level": "info") report how the file was read — e.g.
    # which unit the score column was taken to be — and are not problems.
    has_problems = any(error.get("level") != "info" for error in errors)
    uploaded = UploadedFile(
        event_id=event_id,
        uploaded_by_id=current_user.id,
        file_type=file_type,
        original_filename=file.filename,
        storage_path=str(destination),
        row_count=row_count,
        parse_status="processed_with_errors" if has_problems else "processed",
        parse_errors=errors,
    )
    db.add(uploaded)
    event.status = "review"
    db.flush()
    record_audit(
        db,
        "file.uploaded",
        "uploaded_file",
        uploaded.id,
        current_user,
        event_id,
        {
            "file_type": file_type,
            "filename": file.filename,
            "rows": row_count,
            "errors": sum(1 for error in errors if error.get("level") != "info"),
            **({"sheet_format": sheet_format} if sheet_format else {}),
            **({"score_basis": score_basis} if score_basis else {}),
        },
    )
    # Alert admins when a presenter submits the sign-in sheet so they can finish
    # the certificate workflow (dashboard notification + email).
    if current_user.role != "admin" and file_type == "attendance":
        notify_admins(
            db,
            category="attendance_upload",
            title=f"Sign-in sheet uploaded: {event.title}",
            body=(
                f"{current_user.full_name} uploaded the attendance / sign-in sheet "
                f"({row_count} rows) for \"{event.title}\". Review compliance and issue certificates."
            ),
            event_id=event_id,
            email=True,
        )
    db.commit()
    db.refresh(uploaded)
    return uploaded
