"""Add course instructor and configurable certificate field placement.

Revision ID: 0004_certificate_template_fields
Revises: 0003_internal_test_and_invites
Create Date: 2026-06-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_certificate_template_fields"
down_revision: Union[str, None] = "0003_internal_test_and_invites"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("training_events", sa.Column("course_instructor", sa.String(255), nullable=True))
    op.add_column(
        "training_events",
        sa.Column(
            "certificate_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("training_events", "certificate_fields")
    op.drop_column("training_events", "course_instructor")
