"""Per-user password reset token, so a forgotten password is not a dead end.

Until now a password could only be set by an admin typing one into
``PATCH /users/{id}``, and it was never shown again -- there was no reset, no
change-password, and the login page's "contact your NMEDA administrator"
pointed at somebody with no control that helped. These two columns hold one
outstanding reset per user.

Only the SHA-256 *hash* of the token is stored, which is why the column is
CHAR-width 64 rather than the token's own length: unlike ``checkin_token`` and
its siblings -- public values printed on QR codes -- a reset token is a
credential, and a readable one in the database would be an account takeover.
The unique index is what makes redemption a single indexed lookup instead of a
scan, and also stops two users from ever colliding on one token.

Both columns are nullable and start NULL, which is "no reset outstanding" --
the correct state for every existing row.

Revision ID: 0015_password_reset
Revises: 0014_certificate_revocation
Create Date: 2026-08-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015_password_reset"
down_revision: Union[str, None] = "0014_certificate_revocation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("password_reset_token_hash", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column("password_reset_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_users_password_reset_token_hash",
        "users",
        ["password_reset_token_hash"],
        unique=True,
    )


def downgrade() -> None:
    # Dropping these invalidates every reset link that is currently in flight
    # -- the token has nowhere left to be checked against, so redemption simply
    # stops working and the user asks again. Nothing else is lost: no password
    # lives in these columns, and the ``user.password_reset_issued`` /
    # ``user.password_changed`` audit entries are what survives the reversal.
    op.drop_index("ix_users_password_reset_token_hash", table_name="users")
    op.drop_column("users", "password_reset_expires_at")
    op.drop_column("users", "password_reset_token_hash")
