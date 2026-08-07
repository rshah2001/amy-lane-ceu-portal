from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import TOKEN_VERSION_CLAIM, decode_access_token
from app.db.session import get_db
from app.models.user import User

bearer_scheme = HTTPBearer()

# Distinct from "Invalid or expired token" on purpose: this one is not a bad
# token, it is a token the account itself retired, and the person holding it
# (usually the owner, on another device) needs to be told to sign in again
# rather than left guessing. Saying so leaks nothing -- the caller already
# presented a validly signed token for this account.
STALE_TOKEN_DETAIL = "Your password was changed. Please sign in again."


def _claimed_token_version(payload: dict) -> int | None:
    """The token's credential version, or None when it cannot be one.

    A token minted before this claim existed is read as version 1, which is
    what every existing row starts at -- that is what keeps a deploy from
    signing the whole portal out. Anything non-integer returns None, which can
    never equal a stored version, so a malformed claim fails closed.
    """
    raw = payload.get(TOKEN_VERSION_CLAIM, 1)
    if isinstance(raw, bool):
        # bool is an int subclass; True == 1 would silently pass as version 1.
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    payload = decode_access_token(credentials.credentials)
    if not payload or not payload.get("sub"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    try:
        # "sub" is attacker-supplied (it only has to survive signature checks,
        # e.g. a token minted against an older/leaked key): a non-numeric value
        # is a bad token, not a server fault, so it must not surface as a 500.
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        ) from None
    user = db.scalar(select(User).where(User.id == user_id))
    # Re-read every request, so deactivating an account ends its open sessions
    # at the next call rather than at token expiry.
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")
    # Same row, same query, no extra cost: a token minted before the password
    # changed no longer matches the version now on the account.
    if _claimed_token_version(payload) != user.token_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=STALE_TOKEN_DETAIL)
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user

