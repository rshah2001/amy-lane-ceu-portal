from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.events import get_visible_event
from app.core.config import settings
from app.db.session import get_db
from app.models.uploaded_file import UploadedFile
from app.models.user import User
from app.schemas.common import UploadedFileOut
from app.services.audit import record_audit
from app.services import storage
from app.services.csv_import import SHEET_FORMATS, process_document, save_upload
from app.services.notifications import notify_admins

router = APIRouter(prefix="/events/{event_id}/uploads", tags=["Uploads"])
FILE_TYPES = {"registration", "attendance", "post_test", "survey"}
ALLOWED_SUFFIXES = {".csv", ".xlsx", ".png", ".jpg", ".jpeg", ".pdf", ".docx"}
ALLOWED_FORMATS_LABEL = "CSV, XLSX, PDF, DOCX, PNG, JPG, or JPEG"
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
        if b"\x00" in contents:
            return False
        try:
            contents.decode("utf-8-sig")
        except UnicodeDecodeError:
            return False
        return True
    return False


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
    event_id: int,
    file_type: str,
    file: UploadFile = File(...),
    sheet_format: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UploadedFile:
    event = get_visible_event(db, event_id, current_user)
    if file_type not in FILE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid file type")
    # Optional hint describing what kind of sheet this is; steers parsing.
    if sheet_format and sheet_format not in SHEET_FORMATS:
        raise HTTPException(status_code=400, detail="Invalid sheet format")
    if current_user.role != "admin" and file_type != "attendance":
        raise HTTPException(
            status_code=403,
            detail="Presenters can only upload the attendance / sign-in sheet",
        )
    suffix = Path(file.filename).suffix.lower() if file.filename else ""
    if not file.filename or suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"Upload a {ALLOWED_FORMATS_LABEL} file")
    contents = await file.read()
    if len(contents) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Upload exceeds the 15 MB limit")
    if not contents or not _content_matches_suffix(suffix, contents):
        raise HTTPException(
            status_code=400,
            detail=f"File content does not match its extension; upload a valid {ALLOWED_FORMATS_LABEL} file",
        )

    destination = settings.uploads_dir / str(event_id) / f"{uuid4().hex}-{Path(file.filename).name}"
    save_upload(contents, destination)
    try:
        row_count, errors = process_document(
            db, event_id, file_type, file.filename, contents, sheet_format=sheet_format
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Unable to extract rows: {exc}") from exc
    uploaded = UploadedFile(
        event_id=event_id,
        uploaded_by_id=current_user.id,
        file_type=file_type,
        original_filename=file.filename,
        storage_path=str(destination),
        row_count=row_count,
        parse_status="processed_with_errors" if errors else "processed",
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
            "errors": len(errors),
            **({"sheet_format": sheet_format} if sheet_format else {}),
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
