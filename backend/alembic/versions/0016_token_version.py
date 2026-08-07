"""Per-user access-token version, so a password change ends open sessions.

Access tokens carried nothing that tied them to the credential they were minted
under, so changing or resetting a password left every previously issued token
valid for the rest of ``access_token_expire_minutes`` (eight hours by default).
The reason somebody resets a password in a hurry is that they believe another
person has it -- and that person kept a working session for the rest of the
day. This column is the counter every token is now stamped with, and
``app.api.deps`` refuses any token whose stamp no longer matches.

NOT NULL with a server default of 1, deliberately: the alternative (nullable,
backfilled later) would leave a window where a NULL version matches no token at
all and signs the portal out. Starting every existing row at 1 -- which is also
how a token minted before the claim existed is read -- means deploying this
signs nobody out; the first *password change* is what starts evicting tokens,
which is exactly the intended trigger.

Revision ID: 0016_token_version
Revises: 0015_password_reset
Create Date: 2026-08-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016_token_version"
down_revision: Union[str, None] = "0015_password_reset"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )


def downgrade() -> None:
    # Dropping this re-opens the hole rather than losing data: tokens stop
    # being checked against a version, so a password change goes back to
    # leaving already-issued tokens alive until they expire. Nothing an admin
    # relies on is destroyed -- the counter is only ever compared, never read
    # by a human -- and the ``user.password_changed`` audit entries survive.
    op.drop_column("users", "token_version")
