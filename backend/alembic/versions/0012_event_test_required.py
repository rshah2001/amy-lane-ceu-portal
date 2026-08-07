"""Make the post-test requirement an explicit per-event flag.

Eligibility used to block on ``test_completed`` unconditionally, so an event
with no post-test at all marked every attendee permanently ineligible. The rule
now mirrors ``survey_required`` and reads ``training_events.test_required``.

The column defaults to TRUE and every existing row is set to TRUE, which is
exactly today's behaviour: no event silently starts granting CEU credit because
its setup was incomplete.

Revision ID: 0012_event_test_required
Revises: 0011_anonymous_survey
Create Date: 2026-08-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_event_test_required"
down_revision: Union[str, None] = "0011_anonymous_survey"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "training_events",
        sa.Column("test_required", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    # Explicit, even though the server_default already backfills: existing
    # events keep gating on the post-test.
    op.execute(sa.text("UPDATE training_events SET test_required = true"))


def downgrade() -> None:
    op.drop_column("training_events", "test_required")
