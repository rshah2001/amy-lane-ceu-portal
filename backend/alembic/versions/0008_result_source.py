"""Tag test/survey results with their source so file re-imports keep web submissions.

Revision ID: 0008_result_source
Revises: 0007_checkin_token
Create Date: 2026-07-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_result_source"
down_revision: Union[str, None] = "0007_checkin_token"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing rows default to "upload"; web submissions recorded after this
    # migration are tagged "web" and survive survey/post-test file re-imports.
    op.add_column(
        "test_results",
        sa.Column("source", sa.String(length=10), nullable=False, server_default="upload"),
    )
    op.add_column(
        "survey_results",
        sa.Column("source", sa.String(length=10), nullable=False, server_default="upload"),
    )


def downgrade() -> None:
    op.drop_column("survey_results", "source")
    op.drop_column("test_results", "source")
