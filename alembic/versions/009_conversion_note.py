"""Add show_conversion_note to therapists

Revision ID: 009
Revises: 008
Create Date: 2026-05-07
"""
from alembic import op
import sqlalchemy as sa

revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('therapists',
        sa.Column('show_conversion_note', sa.Boolean(), nullable=False, server_default='false')
    )


def downgrade():
    op.drop_column('therapists', 'show_conversion_note')
