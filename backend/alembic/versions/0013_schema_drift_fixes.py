"""Close the ORM/database drift found by the first working autogenerate run.

Two real divergences:

1. ``notifications.created_at`` is non-nullable in the ORM but was created
   nullable in 0006, so a direct INSERT that omitted it produced a row the ORM
   cannot load.
2. ``app_settings.value`` was created as ``json`` in 0010 while every other JSON
   column in the schema is ``jsonb``. The models now declare a JSONB variant for
   Postgres, so this column is aligned with the rest.

Revision ID: 0013_schema_drift_fixes
Revises: 0012_event_test_required
Create Date: 2026-08-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_schema_drift_fixes"
down_revision: Union[str, None] = "0012_event_test_required"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Any pre-existing NULL would fail the NOT NULL; there is no meaningful
    # original timestamp for such a row, so stamp it with now().
    op.execute(sa.text("UPDATE notifications SET created_at = now() WHERE created_at IS NULL"))
    with op.batch_alter_table("notifications") as batch:
        batch.alter_column(
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            existing_server_default=sa.func.now(),
            nullable=False,
        )
    op.alter_column(
        "app_settings",
        "value",
        existing_type=postgresql.JSON(astext_type=sa.Text()),
        type_=postgresql.JSONB(astext_type=sa.Text()),
        existing_nullable=False,
        postgresql_using="value::jsonb",
    )


def downgrade() -> None:
    op.alter_column(
        "app_settings",
        "value",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        type_=postgresql.JSON(astext_type=sa.Text()),
        existing_nullable=False,
        postgresql_using="value::json",
    )
    with op.batch_alter_table("notifications") as batch:
        batch.alter_column(
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            existing_server_default=sa.func.now(),
            nullable=True,
        )
