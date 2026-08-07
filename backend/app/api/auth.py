import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.rate_limit import PublicRateLimit, password_reset_limiter
from app.core.security import create_access_token, login_rate_limiter, verify_password
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MessageOut,
    PasswordChangedOut,
    ResetPasswordRequest,
    TokenResponse,
    UserOut,
)
from app.services.audit import record_audit
from app.services.emailer import send_password_reset_email
from app.services.password_reset import consume_reset_token, issue_reset_token, reset_link, set_password

logger = logging.getLogger("app.auth")

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Both reset routes are unauthenticated, so both are budgeted per caller IP.
# They share one scope deliberately: requesting links and guessing tokens are
# two halves of the same attack, and letting one refill while the other is
# blocked would just hand back the budget.
reset_rate_limit = PublicRateLimit("password_reset", limiter=password_reset_limiter)

# The single answer /forgot-password gives, whether or not the address belongs
# to anybody. Saying "no such user" would turn this route into a free test of
# which addresses have portal accounts.
FORGOT_PASSWORD_DETAIL = (
    "If that address has an account, a password reset link is on its way. "
    "The link can only be used once and expires."
)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    client_ip = _client_ip(request)
    retry_after = login_rate_limiter.retry_after(payload.email, client_ip)
    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not verify_password(payload.password, user.hashed_password):
        login_rate_limiter.record_failure(payload.email, client_ip)
        record_audit(
            db,
            "user.login_failed",
            "user",
            user.id if user else None,
            None,
            details={"email": payload.email.lower(), "ip": client_ip},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive")
    login_rate_limiter.reset(payload.email, client_ip)
    record_audit(db, "user.login", "user", user.id, user)
    db.commit()
    return TokenResponse(
        access_token=create_access_token(str(user.id), user.role, user.token_version),
        user=UserOut.model_validate(user),
    )


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.post("/change-password", response_model=PasswordChangedOut)
def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PasswordChangedOut:
    """Change your own password, proving you know the current one.

    The current password is required even though the caller already holds a
    valid session: a session is something that can be left open on a shared
    laptop, and without this check that is enough to lock the account's owner
    out of it permanently.

    Succeeding ends every *other* session on the account (see
    ``set_password``), and hands this one a replacement token so the person who
    made the change is not the only one signed out by it. That is safe to do
    here and nowhere else: the current password was just proved one line below,
    so this caller is the account's owner and not the session being evicted.
    """
    if not verify_password(payload.current_password, current_user.hashed_password):
        # Audited, because a run of these against one account is worth seeing
        # in the trail. The submitted value is never recorded.
        record_audit(
            db, "user.password_change_failed", "user", current_user.id, current_user
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect"
        )
    if payload.new_password == payload.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The new password must be different from the current one",
        )
    set_password(current_user, payload.new_password)
    # Details carry the *method*, never the password or a token: an audit trail
    # that records credentials is a credential store nobody meant to build.
    record_audit(
        db, "user.password_changed", "user", current_user.id, current_user, details={"method": "self_service"}
    )
    db.commit()
    # Minted after the commit, so the version it carries is the one now stored:
    # a token minted from an uncommitted bump would be refused if the commit
    # failed, handing the caller a session that never worked.
    return PasswordChangedOut(
        detail="Your password has been changed. Any other devices signed in to this account have been signed out.",
        access_token=create_access_token(
            str(current_user.id), current_user.role, current_user.token_version
        ),
        user=UserOut.model_validate(current_user),
    )


@router.post("/forgot-password", response_model=MessageOut, status_code=status.HTTP_202_ACCEPTED)
def forgot_password(
    payload: ForgotPasswordRequest,
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(reset_rate_limit),
) -> MessageOut:
    """Email a single-use reset link to an address, if it has an account.

    Answers identically in every case -- unknown address, deactivated account,
    or a link genuinely sent -- so it cannot be used to enumerate accounts. The
    only observable difference is whether an email arrives, which is only
    observable to the person who owns the mailbox.
    """
    email = payload.email.lower()
    user = db.scalar(select(User).where(User.email == email))
    if user and user.is_active:
        token, expires_at = issue_reset_token(db, user)
        record_audit(
            db,
            "user.password_reset_requested",
            "user",
            user.id,
            None,
            details={"method": "self_service"},
        )
        db.commit()
        try:
            send_password_reset_email(user.email, user.full_name, reset_link(token), expires_at)
        except Exception as exc:  # noqa: BLE001 - the caller must not learn this failed
            # A send failure cannot change the response without turning the
            # route into an enumeration oracle, so it goes to the log instead.
            # The token stays valid; the user can ask again, or an admin can
            # issue one through /users/{id}/reset-password and read it out.
            logger.error("Password reset email to %s failed: %s", user.email, exc)
    return MessageOut(detail=FORGOT_PASSWORD_DETAIL)


@router.post("/reset-password", response_model=MessageOut)
def reset_password(
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(reset_rate_limit),
) -> MessageOut:
    """Set a new password using a reset token. The token is spent either way."""
    user = consume_reset_token(db, payload.token)
    if user is None:
        # One message for unknown / expired / already-used / deactivated: the
        # caller is anonymous and must not be able to tell them apart.
        db.commit()  # persist the clearing of an expired or orphaned token
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This password reset link is invalid or has expired. Please request a new one.",
        )
    set_password(user, payload.new_password)
    record_audit(
        db, "user.password_changed", "user", user.id, user, details={"method": "reset_token"}
    )
    db.commit()
    return MessageOut(detail="Your password has been reset. You can now sign in.")
