"""Per-attendee invite nonce, so an emailed survey link proves who sent it.

``/public/surveys/{token}`` is a shared link -- printed on a QR sheet, shown on
a slide -- so a submission's only claim to an identity was the name and email
typed into the form. An email address is not a secret, which meant anybody who
knew a colleague's registered address could complete that colleague's survey.

This column carries a secret that only that attendee's own invite email
contains (``?k=``). A submission carrying it is credited to that attendee
whatever the form says; a submission without one falls back to the previous
rules, because the QR flow legitimately has no nonce to offer.

Nullable and NULL for every existing row, which is "no invite sent yet" -- the
value is minted the first time this attendee is emailed, and never rotated
afterwards, so a link already in an inbox keeps working. Unique and indexed,
matching ``checkin_token`` / ``survey_token`` / ``test_token``: redemption is a
single indexed equality, and two attendees can never collide on one nonce.

Revision ID: 0017_invite_nonce
Revises: 0016_token_version
Create Date: 2026-08-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017_invite_nonce"
down_revision: Union[str, None] = "0016_token_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("event_attendees", sa.Column("invite_nonce", sa.String(length=120), nullable=True))
    op.create_index(
        "ix_event_attendees_invite_nonce", "event_attendees", ["invite_nonce"], unique=True
    )


def downgrade() -> None:
    # Dropping this invalidates the ``?k=`` on every invite already sent: those
    # links keep loading the survey (the event token in them is untouched) and
    # simply fall back to name/email matching, which is where this started.
    # No compliance state is lost -- survey_completed is a separate column and
    # the ``survey.submitted`` audit entries record which basis credited each
    # submission.
    op.drop_index("ix_event_attendees_invite_nonce", table_name="event_attendees")
    op.drop_column("event_attendees", "invite_nonce")
