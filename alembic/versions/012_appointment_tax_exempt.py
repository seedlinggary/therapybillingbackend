"""Add tax_exempt to appointments

Revision ID: 012
Revises: 011
Create Date: 2026-05-13
"""
from alembic import op
import sqlalchemy as sa

revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('appointments',
        sa.Column('tax_exempt', sa.Boolean(), nullable=True)
    )


def downgrade():
    op.drop_column('appointments', 'tax_exempt')
