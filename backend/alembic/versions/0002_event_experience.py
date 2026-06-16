"""Add event links, surveys, and immutable certificate snapshots.

Revision ID: 0002_event_experience
Revises: 0001_initial
Create Date: 2026-06-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_event_experience"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("training_events", sa.Column("event_type", sa.String(80), nullable=False, server_default="lunch_and_learn"))
    op.add_column("training_events", sa.Column("post_test_url", sa.String(1000), nullable=True))
    op.add_column("training_events", sa.Column("survey_mode", sa.String(30), nullable=False, server_default="internal"))
    op.add_column("training_events", sa.Column("external_survey_url", sa.String(1000), nullable=True))
    op.add_column("training_events", sa.Column("survey_token", sa.String(120), nullable=True))
    op.add_column(
        "training_events",
        sa.Column(
            "survey_questions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "training_events",
        sa.Column("certificate_title", sa.String(255), nullable=False, server_default="Certificate of Completion"),
    )
    op.add_column("training_events", sa.Column("certificate_template_path", sa.String(500), nullable=True))
    op.add_column(
        "training_events",
        sa.Column("certificate_template_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("training_events", sa.Column("certificate_template_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_training_events_survey_token", "training_events", ["survey_token"], unique=True)

    op.add_column("certificates", sa.Column("template_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column(
        "certificates",
        sa.Column(
            "event_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("certificates", "event_snapshot")
    op.drop_column("certificates", "template_version")
    op.drop_index("ix_training_events_survey_token", table_name="training_events")
    op.drop_column("training_events", "certificate_template_updated_at")
    op.drop_column("training_events", "certificate_template_version")
    op.drop_column("training_events", "certificate_template_path")
    op.drop_column("training_events", "certificate_title")
    op.drop_column("training_events", "survey_questions")
    op.drop_column("training_events", "survey_token")
    op.drop_column("training_events", "external_survey_url")
    op.drop_column("training_events", "survey_mode")
    op.drop_column("training_events", "post_test_url")
    op.drop_column("training_events", "event_type")
