from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.security import get_password_hash
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import UserCreate, UserOut, UserUpdate
from app.services.audit import record_audit

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
        user.hashed_password = get_password_hash(payload.password)
    record_audit(db, "user.updated", "user", user.id, current_user)
    db.commit()
    db.refresh(user)
    return user
