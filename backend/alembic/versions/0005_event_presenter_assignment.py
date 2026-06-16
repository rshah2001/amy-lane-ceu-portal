"""Assign a presenter user to an event for scoped presenter access.

Revision ID: 0005_event_presenter_assignment
Revises: 0004_certificate_template_fields
Create Date: 2026-06-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_event_presenter_assignment"
down_revision: Union[str, None] = "0004_certificate_template_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "training_events",
        sa.Column("assigned_presenter_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_training_events_assigned_presenter_id_users",
        "training_events",
        "users",
        ["assigned_presenter_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_training_events_assigned_presenter_id_users",
        "training_events",
        type_="foreignkey",
    )
    op.drop_column("training_events", "assigned_presenter_id")
