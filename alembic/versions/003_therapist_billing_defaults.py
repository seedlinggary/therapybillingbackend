"""Add default billing frequency/anchor to therapists

Revision ID: 003
Revises: 002
Create Date: 2026-04-28 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('therapists', sa.Column(
        'default_billing_frequency', sa.String(32), nullable=False, server_default='same_day'
    ))
    op.add_column('therapists', sa.Column(
        'default_billing_anchor_day', sa.Integer(), nullable=True
    ))


def downgrade():
    op.drop_column('therapists', 'default_billing_anchor_day')
    op.drop_column('therapists', 'default_billing_frequency')
