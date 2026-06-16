"""Add internal post-test fields and attendee invite tracking.

Revision ID: 0003_internal_test_and_invites
Revises: 0002_event_experience
Create Date: 2026-06-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_internal_test_and_invites"
down_revision: Union[str, None] = "0002_event_experience"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "training_events",
        sa.Column("test_mode", sa.String(30), nullable=False, server_default="external"),
    )
    op.add_column("training_events", sa.Column("test_token", sa.String(120), nullable=True))
    op.add_column(
        "training_events",
        sa.Column(
            "test_questions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_index("ix_training_events_test_token", "training_events", ["test_token"], unique=True)
    op.add_column(
        "event_attendees",
        sa.Column("invite_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("event_attendees", "invite_sent_at")
    op.drop_index("ix_training_events_test_token", table_name="training_events")
    op.drop_column("training_events", "test_questions")
    op.drop_column("training_events", "test_token")
    op.drop_column("training_events", "test_mode")
