"""Revocation state for certificates, so a withdrawal is not a deletion.

An admin still needs a remedy for a certificate issued to the wrong person, but
``docs/data-storage-and-retention-confirmation.md`` commits to keeping issued
certificate records for seven years, so the remedy cannot be a DELETE. These
three columns record the withdrawal instead: the row, its PDF and its email
logs stay put until the retention purge takes them with the rest of the event.

Existing rows are not revoked -- every column is nullable and left NULL, which
is exactly "still valid".

Revision ID: 0014_certificate_revocation
Revises: 0013_schema_drift_fixes
Create Date: 2026-08-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_certificate_revocation"
down_revision: Union[str, None] = "0013_schema_drift_fixes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("certificates", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("certificates", sa.Column("revoked_by_id", sa.Integer(), nullable=True))
    op.add_column("certificates", sa.Column("revoked_reason", sa.String(length=500), nullable=True))
    # Named explicitly, following 0005: an auto-named constraint cannot be
    # dropped by name in downgrade().
    op.create_foreign_key(
        "fk_certificates_revoked_by_id_users",
        "certificates",
        "users",
        ["revoked_by_id"],
        ["id"],
    )


def downgrade() -> None:
    # Dropping the columns discards which certificates were withdrawn, so the
    # ones still carrying a revoked_at start verifying as valid again. That is
    # inherent to reversing this migration; the audit trail
    # (``certificate.revoked`` entries) is what survives it.
    op.drop_constraint("fk_certificates_revoked_by_id_users", "certificates", type_="foreignkey")
    op.drop_column("certificates", "revoked_reason")
    op.drop_column("certificates", "revoked_by_id")
    op.drop_column("certificates", "revoked_at")
