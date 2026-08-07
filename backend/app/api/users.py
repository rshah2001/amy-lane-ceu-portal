import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.security import get_password_hash
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import PasswordResetLinkOut, UserCreate, UserOut, UserUpdate
from app.services.audit import record_audit
from app.services.emailer import send_password_reset_email
from app.services.password_reset import issue_reset_token, reset_link, set_password

logger = logging.getLogger("app.users")

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[User]:
    return list(db.scalars(select(User).order_by(User.created_at)))


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> User:
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )
    user = User(
        email=email,
        full_name=payload.full_name.strip(),
        role=payload.role,
        hashed_password=get_password_hash(payload.password),
    )
    db.add(user)
    db.flush()
    record_audit(db, "user.created", "user", user.id, current_user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> User:
    user = db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    # Guard against an admin locking themselves out of the portal.
    if user.id == current_user.id and (payload.is_active is False or payload.role == "presenter"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot deactivate or demote your own admin account",
        )
    if payload.full_name is not None:
        user.full_name = payload.full_name.strip()
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password is not None:
        # Routed through set_password so that setting one by hand also
        # invalidates any reset link still sitting in the user's inbox.
        set_password(user, payload.password)
    record_audit(db, "user.updated", "user", user.id, current_user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/reset-password", response_model=PasswordResetLinkOut)
def admin_reset_password(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> PasswordResetLinkOut:
    """Start a password reset on someone else's behalf.

    This is the answer to the login page's "contact your NMEDA administrator":
    before it existed, the administrator's only move was to invent a new
    password in ``PATCH /users/{id}`` and read *that* out, which meant a shared
    secret the admin knew and the user could not change.

    A tokenized link is issued instead. It is emailed to the user and also
    returned here, because the case this exists for is a presenter who cannot
    get in and whose address may itself be the thing that is wrong -- an admin
    who can only answer "check your email" has not been given a control that
    helps. Returning it grants no new power (the same admin can already set the
    password outright) and gives up less: the password ends up known only to
    its owner.

    An inactive account is refused rather than quietly issued a link that would
    be rejected at redemption time.
    """
    user = db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This account is deactivated. Reactivate it before resetting the password.",
        )
    token, expires_at = issue_reset_token(db, user)
    url = reset_link(token)
    emailed = True
    email_error: str | None = None
    try:
        send_password_reset_email(user.email, user.full_name, url, expires_at)
    except Exception as exc:  # noqa: BLE001 - the link still works; say so
        # Not fatal, and deliberately not a 502: the token is minted and the
        # link is in this response, which is exactly the fallback an admin
        # needs when the user's address is the broken thing.
        logger.error("Password reset email to %s failed: %s", user.email, exc)
        emailed = False
        email_error = str(exc)
    # The audit records that a reset was issued, by whom, for whom -- and never
    # the token, which is a credential.
    record_audit(
        db,
        "user.password_reset_issued",
        "user",
        user.id,
        current_user,
        details={"emailed": emailed, "expires_at": expires_at.isoformat()},
    )
    db.commit()
    return PasswordResetLinkOut(
        user_id=user.id,
        email=user.email,
        reset_url=url,
        expires_at=expires_at,
        emailed=emailed,
        email_error=email_error,
    )
