"""Advanced features: recurring appointments, invoice batching, bill-now, offline payments

Revision ID: 002
Revises: 001
Create Date: 2026-04-28 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade():
    # ── recurrence_rules ─────────────────────────────────────────────────────
    op.create_table('recurrence_rules',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('therapist_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('client_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('recurrence_type', sa.String(32), nullable=False),
        sa.Column('interval', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date()),
        sa.Column('occurrence_count', sa.Integer()),
        sa.Column('session_type', sa.String(128), server_default='Individual'),
        sa.Column('override_price', sa.Numeric(10, 2)),
        sa.Column('duration_minutes', sa.Integer(), nullable=False, server_default='50'),
        sa.Column('start_hour', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('start_minute', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(['therapist_id'], ['therapists.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_recurrence_rules_therapist_id', 'recurrence_rules', ['therapist_id'])
    op.create_index('ix_recurrence_rules_client_id', 'recurrence_rules', ['client_id'])

    # ── appointments: add recurrence_id and billed ───────────────────────────
    op.add_column('appointments', sa.Column('recurrence_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_appointments_recurrence_id', 'appointments', 'recurrence_rules',
        ['recurrence_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('ix_appointments_recurrence_id', 'appointments', ['recurrence_id'])

    op.add_column('appointments', sa.Column('billed', sa.Boolean(), nullable=False, server_default='false'))
    op.create_index('ix_appointments_billed', 'appointments', ['status', 'billed', 'completed_at'])

    # Backfill: mark existing invoiced appointments as billed
    op.execute("""
        UPDATE appointments
        SET billed = TRUE
        WHERE id IN (
            SELECT appointment_id FROM invoices WHERE appointment_id IS NOT NULL
        )
    """)

    # ── invoices: make appointment_id nullable, drop unique constraint ────────
    op.drop_constraint('uq_invoice_appointment', 'invoices', type_='unique')
    op.alter_column('invoices', 'appointment_id', nullable=True)

    # ── invoice_items ─────────────────────────────────────────────────────────
    op.create_table('invoice_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('invoice_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('appointment_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_invoice_items_invoice_id', 'invoice_items', ['invoice_id'])
    op.create_index('ix_invoice_items_appointment_id', 'invoice_items', ['appointment_id'])

    # Backfill invoice_items for all existing invoices
    op.execute("""
        INSERT INTO invoice_items (id, invoice_id, appointment_id, amount, description, created_at)
        SELECT
            gen_random_uuid(),
            i.id,
            i.appointment_id,
            i.amount,
            'Therapy Session',
            NOW()
        FROM invoices i
        WHERE i.appointment_id IS NOT NULL
    """)

    # ── therapist_clients: add billing schedule fields ────────────────────────
    op.add_column('therapist_clients', sa.Column('billing_frequency', sa.String(32), nullable=False, server_default='same_day'))
    op.add_column('therapist_clients', sa.Column('billing_anchor_day', sa.Integer(), nullable=True))

    # ── therapists: add payment_instructions ─────────────────────────────────
    op.add_column('therapists', sa.Column('payment_instructions', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('therapists', 'payment_instructions')
    op.drop_column('therapist_clients', 'billing_anchor_day')
    op.drop_column('therapist_clients', 'billing_frequency')
    op.drop_table('invoice_items')
    op.alter_column('invoices', 'appointment_id', nullable=False)
    op.create_unique_constraint('uq_invoice_appointment', 'invoices', ['appointment_id'])
    op.drop_index('ix_appointments_billed', 'appointments')
    op.drop_column('appointments', 'billed')
    op.drop_index('ix_appointments_recurrence_id', 'appointments')
    op.drop_constraint('fk_appointments_recurrence_id', 'appointments', type_='foreignkey')
    op.drop_column('appointments', 'recurrence_id')
    op.drop_table('recurrence_rules')
