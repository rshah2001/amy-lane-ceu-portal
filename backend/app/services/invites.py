"""Per-attendee invite nonces: proof a public submission came from our email.

The problem this exists for: ``/public/surveys/{token}`` and
``/public/tests/{token}`` are *shared* links -- printed on a QR sheet and shown
on a slide -- so the only thing a submission could offer as identity was a name
and an email address. ``surveys._completion_basis`` already refuses to credit a
submission that names an attendee without carrying their address, but an
address is not a secret: anybody who knows a colleague's registered email could
still complete that colleague's survey, or sit their scored post-test, and move
their compliance state.

The nonce closes that for the people we email. Each ``EventAttendee`` gets one
the first time an invite is sent to it, ``emailer`` embeds it in that
attendee's post-test and survey links as ``?k=``, and a submission carrying it
is credited to that attendee no matter what name or address the form was filled
in with.

Following the token conventions already in this codebase (``checkin_token``,
``survey_token``, ``test_token``): a nullable, unique, indexed ``String(120)``
on the row it belongs to, resolved by a single indexed equality, and carried in
the public URL as a query parameter.

It departs from those three in two respects, both deliberate:

* **How it is generated.** The event tokens are ``uuid4().hex``, which is fine
  for a value that is public by design. This one is not public -- it is the
  whole difference between "the person we emailed" and "somebody who knows
  their address" -- so it comes from ``secrets``.
* **What it is worth, and therefore how it is stored.** Unlike a password reset
  token (hashed, single use, expiring) this one is stored in plaintext and does
  not expire, because it has to survive being re-sent: distribution is re-run
  routinely, and the link in the *first* email must keep working. Hashing it
  would mean minting a new one per send and silently breaking every invite
  already in somebody's inbox. What it grants is correspondingly narrow --
  crediting one attendee's survey and post-test completions on one event, with
  the score they actually earned in the session it was used -- never portal
  access, and never the ability to name a *different* attendee.
"""

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.event_attendee import EventAttendee

# 16 bytes -> a 22-character URL-safe string, 128 bits of CSPRNG output. Long
# enough that guessing is not a strategy (and the public survey endpoint is
# rate limited per caller besides), short enough to survive an email client
# wrapping the link.
NONCE_BYTES = 16
# The column width, so a caller-supplied value can be bounded before it is used
# as a lookup key rather than after.
NONCE_MAX_LENGTH = 120


def ensure_invite_nonce(link: EventAttendee) -> str:
    """This attendee's invite nonce, minting one on first use.

    Stable on purpose: re-running distribution must not invalidate the link in
    an email the attendee already has. The caller is responsible for committing.
    """
    if not link.invite_nonce:
        link.invite_nonce = secrets.token_urlsafe(NONCE_BYTES)
    return link.invite_nonce


def link_for_nonce(db: Session, event_id: int, nonce: str | None) -> EventAttendee | None:
    """The roster row a nonce identifies on this event, or None.

    Scoped to ``event_id`` as well as the nonce so a link forwarded from one
    event's invite cannot vouch for anybody on another event, even though the
    nonce is globally unique.

    Returns None for anything unrecognised rather than raising: the caller
    falls back to the identity rules that applied before nonces existed, which
    keeps a mangled or stale link from throwing away real feedback, or a
    post-test sitting the attendee only gets three of.
    """
    if not nonce or len(nonce) > NONCE_MAX_LENGTH:
        return None
    return db.scalar(
        select(EventAttendee).where(
            EventAttendee.event_id == event_id,
            EventAttendee.invite_nonce == nonce,
        )
    )
