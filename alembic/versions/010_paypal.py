"""Add PayPal columns to therapists and invoices

Revision ID: 010
Revises: 009
Create Date: 2026-05-08
"""
from alembic import op
import sqlalchemy as sa

revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('therapists',
        sa.Column('paypal_email', sa.String(255), nullable=True)
    )
    op.add_column('therapists',
        sa.Column('paypal_connected', sa.Boolean(), nullable=False, server_default='false')
    )
    op.add_column('invoices',
        sa.Column('paypal_order_id', sa.String(255), nullable=True)
    )
    op.add_column('invoices',
        sa.Column('paypal_payment_link', sa.Text(), nullable=True)
    )
    op.create_index('ix_invoices_paypal_order_id', 'invoices', ['paypal_order_id'])


def downgrade():
    op.drop_index('ix_invoices_paypal_order_id', table_name='invoices')
    op.drop_column('invoices', 'paypal_payment_link')
    op.drop_column('invoices', 'paypal_order_id')
    op.drop_column('therapists', 'paypal_connected')
    op.drop_column('therapists', 'paypal_email')
