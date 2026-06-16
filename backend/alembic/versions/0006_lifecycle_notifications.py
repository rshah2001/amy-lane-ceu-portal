"""Survey-required toggle, certificate delivery/download tracking, notifications.

Revision ID: 0006_lifecycle_notifications
Revises: 0005_event_presenter_assignment
Create Date: 2026-06-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_lifecycle_notifications"
down_revision: Union[str, None] = "0005_event_presenter_assignment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "training_events",
        sa.Column("survey_required", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("certificates", sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("certificates", sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "recipient_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("category", sa.String(length=60), nullable=False, server_default="general"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("training_events.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false(), index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
    )


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_column("certificates", "downloaded_at")
    op.drop_column("certificates", "delivered_at")
    op.drop_column("training_events", "survey_required")
