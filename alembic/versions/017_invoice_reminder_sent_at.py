"""Add reminder_sent_at to invoices

Revision ID: 017
Revises: 016
Create Date: 2026-06-11
"""
from alembic import op
import sqlalchemy as sa

revision = '017'
down_revision = '016'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('invoices', sa.Column('reminder_sent_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('invoices', 'reminder_sent_at')
