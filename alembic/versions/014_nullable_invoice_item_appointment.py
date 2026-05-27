"""Make invoice_items.appointment_id nullable for standalone invoices

Revision ID: 014
Revises: 013
Create Date: 2026-05-27
"""
from alembic import op
import sqlalchemy as sa

revision = '014'
down_revision = '013'
branch_labels = None
depends_on = None


def upgrade():
    # Drop the existing NOT NULL FK constraint, make column nullable, recreate with SET NULL
    op.drop_constraint('invoice_items_appointment_id_fkey', 'invoice_items', type_='foreignkey')
    op.alter_column('invoice_items', 'appointment_id', nullable=True)
    op.create_foreign_key(
        'invoice_items_appointment_id_fkey',
        'invoice_items', 'appointments',
        ['appointment_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade():
    # Remove rows with NULL appointment_id before reverting (can't add NOT NULL otherwise)
    op.execute("DELETE FROM invoice_items WHERE appointment_id IS NULL")
    op.drop_constraint('invoice_items_appointment_id_fkey', 'invoice_items', type_='foreignkey')
    op.alter_column('invoice_items', 'appointment_id', nullable=False)
    op.create_foreign_key(
        'invoice_items_appointment_id_fkey',
        'invoice_items', 'appointments',
        ['appointment_id'], ['id'],
        ondelete='RESTRICT',
    )
