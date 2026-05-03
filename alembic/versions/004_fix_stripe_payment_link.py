"""Widen stripe_payment_link from VARCHAR(500) to TEXT

Revision ID: 004
Revises: 003
Create Date: 2026-04-28 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        'invoices', 'stripe_payment_link',
        type_=sa.Text(),
        existing_type=sa.String(500),
        existing_nullable=True,
    )


def downgrade():
    op.alter_column(
        'invoices', 'stripe_payment_link',
        type_=sa.String(500),
        existing_type=sa.Text(),
        existing_nullable=True,
    )
