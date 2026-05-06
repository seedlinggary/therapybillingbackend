"""Add PayMe provider support: payment_provider fields, PayMe columns, payme_payment_metadata table

Revision ID: 007
Revises: 006
Create Date: 2026-05-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade():
    # ── therapists: payment provider + PayMe credentials ─────────────────────
    op.add_column('therapists',
        sa.Column('payment_provider', sa.String(32), nullable=False, server_default='stripe')
    )
    op.add_column('therapists',
        sa.Column('payme_seller_id', sa.String(255), nullable=True)
    )
    op.add_column('therapists',
        sa.Column('payme_api_key', sa.Text(), nullable=True)
    )

    # ── invoices: payment provider + PayMe fields ─────────────────────────────
    op.add_column('invoices',
        sa.Column('payment_provider', sa.String(32), nullable=False, server_default='stripe')
    )
    op.add_column('invoices',
        sa.Column('payme_sale_id', sa.String(255), nullable=True)
    )
    op.add_column('invoices',
        sa.Column('payme_payment_link', sa.Text(), nullable=True)
    )
    op.create_index('ix_invoices_payme_sale_id', 'invoices', ['payme_sale_id'])

    # ── payments: make stripe_payment_intent_id nullable, add provider fields ─
    op.alter_column('payments', 'stripe_payment_intent_id', nullable=True)
    op.add_column('payments',
        sa.Column('provider', sa.String(32), nullable=False, server_default='stripe')
    )
    op.add_column('payments',
        sa.Column('external_payment_id', sa.String(255), nullable=True)
    )
    op.create_unique_constraint('uq_payments_external_payment_id', 'payments', ['external_payment_id'])
    op.create_index('ix_payments_external_payment_id', 'payments', ['external_payment_id'])

    # Backfill external_payment_id from stripe_payment_intent_id for existing rows
    op.execute("""
        UPDATE payments
        SET external_payment_id = stripe_payment_intent_id
        WHERE stripe_payment_intent_id IS NOT NULL
          AND external_payment_id IS NULL
    """)

    # ── payme_payment_metadata table ──────────────────────────────────────────
    op.create_table(
        'payme_payment_metadata',
        sa.Column('id',            UUID(as_uuid=True), primary_key=True),
        sa.Column('payme_sale_id', sa.String(255),     nullable=False),
        sa.Column('invoice_id',    UUID(as_uuid=True), sa.ForeignKey('invoices.id',   ondelete='CASCADE'), nullable=False),
        sa.Column('therapist_id',  UUID(as_uuid=True), sa.ForeignKey('therapists.id', ondelete='CASCADE'), nullable=False),
        sa.Column('client_id',     UUID(as_uuid=True), sa.ForeignKey('clients.id',    ondelete='CASCADE'), nullable=False),
        sa.Column('metadata',      JSONB,               nullable=True),
        sa.Column('created_at',    sa.DateTime(timezone=True)),
    )
    op.create_unique_constraint('uq_payme_metadata_sale_id', 'payme_payment_metadata', ['payme_sale_id'])
    op.create_index('ix_payme_metadata_sale_id',   'payme_payment_metadata', ['payme_sale_id'])
    op.create_index('ix_payme_metadata_invoice_id', 'payme_payment_metadata', ['invoice_id'])


def downgrade():
    op.drop_table('payme_payment_metadata')

    op.drop_index('ix_payments_external_payment_id', table_name='payments')
    op.drop_constraint('uq_payments_external_payment_id', 'payments')
    op.drop_column('payments', 'external_payment_id')
    op.drop_column('payments', 'provider')
    op.alter_column('payments', 'stripe_payment_intent_id', nullable=False)

    op.drop_index('ix_invoices_payme_sale_id', table_name='invoices')
    op.drop_column('invoices', 'payme_payment_link')
    op.drop_column('invoices', 'payme_sale_id')
    op.drop_column('invoices', 'payment_provider')

    op.drop_column('therapists', 'payme_api_key')
    op.drop_column('therapists', 'payme_seller_id')
    op.drop_column('therapists', 'payment_provider')
