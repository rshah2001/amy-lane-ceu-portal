from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.user import User

# Actions recorded when an import throws work away rather than adding to it.
# Named constants because the compliance story depends on being able to query
# them back out ("what happened to the 7/14 scores?"), and a typo'd action
# string is an audit trail that silently answers "nothing happened".
RESULTS_CLEARED_ACTION = "import.results_cleared"


def record_audit(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: int | None,
    actor: User | None,
    event_id: int | None = None,
    details: dict | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_id=actor.id if actor else None,
        event_id=event_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details or {},
    )
    db.add(entry)
    return entry


def record_destructive_import(
    db: Session,
    *,
    event_id: int,
    actor: User | None,
    file_type: str,
    cleared: dict[str, int],
    reason: str,
    filename: str | None = None,
    rows_in_file: int = 0,
    names_parsed: int = 0,
) -> AuditLog:
    """Audit an import that deleted or reset an event's existing results.

    A re-import replaces what the last one wrote, so the rows it removes are
    real work — an evening's scores or survey responses — and until this
    existed the deletion left no trace at all: an upload that parsed zero names
    could wipe an event and the audit log would only show a file was uploaded.
    This records enough to reconstruct the loss without the rows themselves:
    who ran it, when (``AuditLog.created_at``), against which event, from which
    file, and how many rows of each kind went.

    ``cleared`` is a per-table tally, e.g.
    ``{"test_results": 24, "event_attendee_test_flags": 31}``; counts are taken
    by the caller *before* the delete, since afterwards there is nothing left
    to count. ``reason`` says why the reset ran ("post_test re-import",
    "no names parsed"), which is what separates a routine replacement from the
    accident this was written for.
    """
    return record_audit(
        db,
        RESULTS_CLEARED_ACTION,
        "training_event",
        event_id,
        actor,
        event_id,
        {
            "file_type": file_type,
            "filename": filename,
            "rows_in_file": rows_in_file,
            "names_parsed": names_parsed,
            "reason": reason,
            "cleared": dict(cleared),
            "rows_cleared": sum(cleared.values()),
        },
    )
