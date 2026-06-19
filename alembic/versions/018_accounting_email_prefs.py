"""Add accounting email sending preferences per doc type

Revision ID: 018
Revises: 017
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa

revision = '018'
down_revision = '017'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('therapists', sa.Column(
        'accounting_send_email_invoice', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('therapists', sa.Column(
        'accounting_send_email_receipt', sa.Boolean(), nullable=False, server_default='true'))


def downgrade():
    op.drop_column('therapists', 'accounting_send_email_invoice')
    op.drop_column('therapists', 'accounting_send_email_receipt')
