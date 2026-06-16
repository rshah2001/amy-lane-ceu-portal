from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
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
from app.services.csv_import import process_document, save_upload
from app.services.notifications import notify_admins

router = APIRouter(prefix="/events/{event_id}/uploads", tags=["Uploads"])
FILE_TYPES = {"registration", "attendance", "post_test", "survey"}
ALLOWED_SUFFIXES = {".csv", ".xlsx", ".png", ".jpg", ".jpeg"}


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


@router.post("/{file_type}", response_model=UploadedFileOut, status_code=201)
async def upload_document(
    event_id: int,
    file_type: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UploadedFile:
    event = get_visible_event(db, event_id, current_user)
    if file_type not in FILE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid file type")
    if current_user.role != "admin" and file_type != "attendance":
        raise HTTPException(
            status_code=403,
            detail="Presenters can only upload the attendance / sign-in sheet",
        )
    if not file.filename or Path(file.filename).suffix.lower() not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="Upload a CSV, XLSX, PNG, JPG, or JPEG file")
    contents = await file.read()
    if len(contents) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Upload exceeds the 15 MB limit")

    destination = settings.uploads_dir / str(event_id) / f"{uuid4().hex}-{Path(file.filename).name}"
    save_upload(contents, destination)
    try:
        row_count, errors = process_document(db, event_id, file_type, file.filename, contents)
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
        {"file_type": file_type, "filename": file.filename, "rows": row_count, "errors": len(errors)},
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
