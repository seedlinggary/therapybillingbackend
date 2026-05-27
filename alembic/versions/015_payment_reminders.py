"""Add payment reminder fields to therapists

Revision ID: 015
Revises: 014
Create Date: 2026-05-27
"""
from alembic import op
import sqlalchemy as sa

revision = '015'
down_revision = '014'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('therapists', sa.Column('reminder_frequency_days', sa.Integer(), nullable=True))
    op.add_column('therapists', sa.Column('last_payment_reminder_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('therapists', 'last_payment_reminder_at')
    op.drop_column('therapists', 'reminder_frequency_days')
