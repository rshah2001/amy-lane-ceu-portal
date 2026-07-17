"""Allow anonymous survey responses and capture an optional business/location.

The public feedback survey no longer requires a name or email, so
``survey_results.attendee_id`` becomes nullable, and a new optional
``business_location`` column stores the "Business Name / Location" field.

Revision ID: 0011_anonymous_survey
Revises: 0010_app_settings
Create Date: 2026-07-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_anonymous_survey"
down_revision: Union[str, None] = "0010_app_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch_alter_table renders plain ALTERs on Postgres and falls back to a
    # table rebuild on SQLite (which cannot ALTER COLUMN).
    with op.batch_alter_table("survey_results") as batch:
        batch.add_column(sa.Column("business_location", sa.String(length=255), nullable=True))
        batch.alter_column("attendee_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    # Anonymous rows have no attendee to fall back to; drop them before the
    # column becomes NOT NULL again.
    op.execute("DELETE FROM survey_results WHERE attendee_id IS NULL")
    with op.batch_alter_table("survey_results") as batch:
        batch.alter_column("attendee_id", existing_type=sa.Integer(), nullable=False)
        batch.drop_column("business_location")
