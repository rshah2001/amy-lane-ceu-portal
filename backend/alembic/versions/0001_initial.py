"""Initial CEU compliance schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True, index=True),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False, server_default="presenter"),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "training_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False, index=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=False, index=True),
        sa.Column("ceu_hours", sa.Numeric(6, 2), nullable=False, server_default="1.00"),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("presenter_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="draft", index=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "attendees",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("first_name", sa.String(length=120), nullable=True),
        sa.Column("last_name", sa.String(length=120), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=False, index=True),
        sa.Column("normalized_name", sa.String(length=255), nullable=False, index=True),
        sa.Column("email", sa.String(length=255), nullable=True, index=True),
        sa.Column("normalized_email", sa.String(length=255), nullable=True, index=True),
        sa.Column("company", sa.String(length=255), nullable=True),
        sa.Column("license_number", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "uploaded_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("training_events.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("uploaded_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("file_type", sa.String(length=50), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parse_status", sa.String(length=50), nullable=False, server_default="processed"),
        sa.Column("parse_errors", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "event_attendees",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("training_events.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("attendee_id", sa.Integer(), sa.ForeignKey("attendees.id"), nullable=False, index=True),
        sa.Column("registered", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("attended", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("test_completed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("test_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("survey_completed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("has_valid_email", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("eligible", sa.Boolean(), nullable=False, server_default=sa.text("false"), index=True),
        sa.Column("approved", sa.Boolean(), nullable=False, server_default=sa.text("false"), index=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("eligibility_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("compliance_status", sa.String(length=50), nullable=False, server_default="pending", index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("event_id", "attendee_id", name="uq_event_attendee"),
    )

    op.create_table(
        "test_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("training_events.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("attendee_id", sa.Integer(), sa.ForeignKey("attendees.id"), nullable=False),
        sa.Column("score", sa.Numeric(5, 2), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )

    op.create_table(
        "survey_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("training_events.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("attendee_id", sa.Integer(), sa.ForeignKey("attendees.id"), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )

    op.create_table(
        "certificates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_attendee_id", sa.Integer(), sa.ForeignKey("event_attendees.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("certificate_number", sa.String(length=120), nullable=False, unique=True, index=True),
        sa.Column("pdf_path", sa.String(length=500), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("generated_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sent_to", sa.String(length=255), nullable=True),
    )

    op.create_table(
        "certificate_email_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("certificate_id", sa.Integer(), sa.ForeignKey("certificates.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("recipient_email", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="sent"),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True, index=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("training_events.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("action", sa.String(length=120), nullable=False, index=True),
        sa.Column("entity_type", sa.String(length=120), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("certificate_email_logs")
    op.drop_table("certificates")
    op.drop_table("survey_results")
    op.drop_table("test_results")
    op.drop_table("event_attendees")
    op.drop_table("uploaded_files")
    op.drop_table("attendees")
    op.drop_table("training_events")
    op.drop_table("users")

