"""Minting and redeeming password-reset tokens.

Why this exists: an account's password could only ever be set by an admin
typing one into ``PATCH /users/{id}``, and it was never shown again. There was
no reset, no change-password, and the login screen's advice ("contact your
NMEDA administrator") pointed at somebody who had no control that helped.
Presenters sign in about twice a year, so "I have forgotten it" is the normal
case rather than the exception.

Design, following the token patterns already in this codebase
(``checkin_token``, ``survey_token``, ``test_token``): the token lives in a
column on the row it belongs to, and the public link is built the same way
``emailer._public_link`` builds the others.

It departs from those patterns in exactly one respect, and deliberately. Event
tokens are printed on QR codes and handed to a room -- they are public, and are
stored in plaintext because there is nothing to protect. A reset token is a
credential: holding one is enough to take over an account. So only its SHA-256
hash is stored, and the token itself exists only in the response that mints it
and in the email that carries it. A leaked database backup therefore yields no
usable reset links.

The three properties the token has to have:

* **Not guessable** -- 32 bytes from ``secrets``, which is 256 bits of CSPRNG
  output, not a uuid4 hex like the (public) event tokens.
* **Single use** -- redeeming clears the columns, so the same link cannot be
  replayed by anyone who later reads the mailbox it was sent to. Setting a
  password by *any* route clears them too (see ``set_password``): once the
  password is known-good, an outstanding reset link is a spare key nobody
  asked to keep.
* **Expiring** -- ``password_reset_ttl_hours`` after issue. An expired token is
  refused and, on the way out, cleared.
"""

import hashlib
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.config import settings
from app.core.security import get_password_hash
from app.models.user import User

# 32 bytes -> a 43-character URL-safe string. Long enough that guessing is not
# a strategy, short enough that an admin can read one over the phone if the
# email never arrives.
TOKEN_BYTES = 32


def hash_token(token: str) -> str:
    """The stored form of a reset token: SHA-256 hex, 64 characters.

    A plain hash (not bcrypt) is right here and not a shortcut: the input is
    256 bits of uniform randomness, so there is no dictionary to attack and no
    work factor worth paying on every lookup. It is also what lets the lookup
    be a single indexed equality instead of a scan over every user.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def reset_link(token: str) -> str:
    """The public URL that carries a reset token, in the same shape as the
    other public links this app sends (``{frontend}/?{param}={token}``)."""
    return f"{settings.public_frontend_url}/?{urlencode({'reset': token})}"


def issue_reset_token(db: Session, user: User) -> tuple[str, datetime]:
    """Mint a fresh reset token for ``user``; returns (token, expires_at).

    Any previously issued token for this user stops working immediately --
    there is one column, so the newest request wins. That is the behaviour a
    second "send it again" has to have.

    The caller is responsible for committing, and for making sure the returned
    token reaches the user (and nowhere else -- it must never be written to a
    log or an audit entry).
    """
    token = secrets.token_urlsafe(TOKEN_BYTES)
    expires_at = utc_now() + timedelta(hours=settings.password_reset_ttl_hours)
    user.password_reset_token_hash = hash_token(token)
    user.password_reset_expires_at = expires_at
    return token, expires_at


def clear_reset_token(user: User) -> None:
    user.password_reset_token_hash = None
    user.password_reset_expires_at = None


def consume_reset_token(db: Session, token: str) -> User | None:
    """Redeem a reset token exactly once. Returns the user, or None.

    None covers every failure the caller must treat identically -- unknown,
    already used, expired, or belonging to a deactivated account -- because
    telling them apart would tell an anonymous caller which tokens exist.
    """
    if not token:
        return None
    user = db.scalar(
        select(User).where(User.password_reset_token_hash == hash_token(token))
    )
    if user is None:
        return None
    expires_at = user.password_reset_expires_at
    if expires_at is None:
        return None
    # Rows read back from SQLite lose their tzinfo; treat a naive timestamp as
    # the UTC it was written as rather than letting the comparison raise.
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=utc_now().tzinfo)
    if expires_at <= utc_now():
        # Burn it on the way out: an expired token has no further use, and
        # leaving it in place keeps a dead credential in the table forever.
        clear_reset_token(user)
        return None
    if not user.is_active:
        # A deactivated account must not be reachable through a link that was
        # valid before it was deactivated.
        clear_reset_token(user)
        return None
    clear_reset_token(user)
    return user


def set_password(user: User, new_password: str) -> None:
    """The single place a password is written.

    Always clears any outstanding reset token: once the account has a password
    its owner knows, a reset link still sitting in an inbox is a spare key.

    Always bumps ``token_version``, which is what makes the change end sessions
    that are already open. Every access token carries the version it was minted
    under and ``app.api.deps`` refuses any that no longer matches, so the
    moment this runs, every previously issued token for this account is dead --
    including the one held by whoever the reset was hurried for. It lives here,
    and not in the three routes that set passwords, so a fourth route cannot
    forget it: ``/auth/change-password``, ``/auth/reset-password`` and
    ``PATCH /users/{id}`` all come through this function.

    (``POST /users/{id}/reset-password`` sets no password -- it only mints a
    link -- so it deliberately does not bump: an admin starting a reset must
    not sign the user out of a session they may still be using to read the
    email. The bump lands when the link is actually redeemed.)

    Not called for a brand-new user in ``POST /users``: that account has no
    tokens to invalidate, and starts at version 1 from the column default.
    """
    user.hashed_password = get_password_hash(new_password)
    clear_reset_token(user)
    # `or 0` covers a User object that has not been flushed yet, where the
    # column default has not been applied and the attribute is still None.
    user.token_version = (user.token_version or 0) + 1
