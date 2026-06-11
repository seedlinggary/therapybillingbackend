"""Add dashboard_note, reminder_repeat, client email prefs, GI doc type

Revision ID: 016
Revises: 015
Create Date: 2026-06-11
"""
from alembic import op
import sqlalchemy as sa

revision = '016'
down_revision = '015'
branch_labels = None
depends_on = None


def upgrade():
    # therapists: dashboard note + reminder repeat mode
    op.add_column('therapists', sa.Column('dashboard_note', sa.Text(), nullable=True))
    op.add_column('therapists', sa.Column('reminder_repeat', sa.Boolean(), nullable=False, server_default='true'))

    # therapist_clients: per-client email notification preferences
    op.add_column('therapist_clients', sa.Column('notify_appointment', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('therapist_clients', sa.Column('notify_invoice', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('therapist_clients', sa.Column('notify_receipt', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('therapist_clients', sa.Column('notify_reminder', sa.Boolean(), nullable=False, server_default='true'))

    # accounting_integrations: GreenInvoice document type override
    op.add_column('accounting_integrations', sa.Column('green_invoice_doc_type', sa.String(32), nullable=True))


def downgrade():
    op.drop_column('therapists', 'dashboard_note')
    op.drop_column('therapists', 'reminder_repeat')
    op.drop_column('therapist_clients', 'notify_appointment')
    op.drop_column('therapist_clients', 'notify_invoice')
    op.drop_column('therapist_clients', 'notify_receipt')
    op.drop_column('therapist_clients', 'notify_reminder')
    op.drop_column('accounting_integrations', 'green_invoice_doc_type')
