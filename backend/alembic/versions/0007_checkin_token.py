"""Add per-event check-in token for self-service attendance QR.

Revision ID: 0007_checkin_token
Revises: 0006_lifecycle_notifications
Create Date: 2026-06-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_checkin_token"
down_revision: Union[str, None] = "0006_lifecycle_notifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("training_events", sa.Column("checkin_token", sa.String(length=120), nullable=True))
    op.create_index("ix_training_events_checkin_token", "training_events", ["checkin_token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_training_events_checkin_token", table_name="training_events")
    op.drop_column("training_events", "checkin_token")
