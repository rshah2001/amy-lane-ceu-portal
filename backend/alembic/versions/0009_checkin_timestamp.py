"""Record QR self-check-in time so attendance file re-imports keep web check-ins.

Revision ID: 0009_checkin_timestamp
Revises: 0008_result_source
Create Date: 2026-07-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_checkin_timestamp"
down_revision: Union[str, None] = "0008_result_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "event_attendees",
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("event_attendees", "checked_in_at")
