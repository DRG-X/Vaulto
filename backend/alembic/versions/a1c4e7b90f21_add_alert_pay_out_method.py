"""Add pay_out_method to rate_alerts

An alert can now be scoped to a delivery rail, so "tell me when Wise's UPI
rate hits 55" is expressible. Nullable, so every existing alert keeps its
current meaning: any rail.

Revision ID: a1c4e7b90f21
Revises: 0b82c2271300
Create Date: 2026-09-18
"""
from alembic import op
import sqlalchemy as sa

revision = "a1c4e7b90f21"
down_revision = "0b82c2271300"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    """
    Whether the column is already there.

    A database built by `Base.metadata.create_all` has it before this migration
    ever runs, so a blind ADD COLUMN fails with "duplicate column" on exactly
    the deployments that are being adopted into Alembic. Checking first is what
    lets an existing schema be stamped mid-chain and brought to head.
    """
    bind = op.get_bind()
    return column in {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade():
    if not _has_column("rate_alerts", "pay_out_method"):
        op.add_column("rate_alerts", sa.Column("pay_out_method", sa.String(), nullable=True))


def downgrade():
    if _has_column("rate_alerts", "pay_out_method"):
        op.drop_column("rate_alerts", "pay_out_method")
