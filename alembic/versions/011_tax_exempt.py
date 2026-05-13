"""Add tax_exempt to therapist_clients

Revision ID: 011
Revises: 010
Create Date: 2026-05-12
"""
from alembic import op
import sqlalchemy as sa

revision = '011'
down_revision = '010'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('therapist_clients',
        sa.Column('tax_exempt', sa.Boolean(), nullable=False, server_default='false')
    )


def downgrade():
    op.drop_column('therapist_clients', 'tax_exempt')
