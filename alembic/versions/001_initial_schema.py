"""Initial schema

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # therapists
    op.create_table('therapists',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('google_sub', sa.String(255), nullable=False),
        sa.Column('picture_url', sa.String(500)),
        sa.Column('google_access_token_enc', sa.Text()),
        sa.Column('google_refresh_token_enc', sa.Text()),
        sa.Column('google_token_expiry', sa.DateTime(timezone=True)),
        sa.Column('google_calendar_id', sa.String(255)),
        sa.Column('google_calendar_connected', sa.Boolean(), default=False),
        sa.Column('stripe_account_id', sa.String(255)),
        sa.Column('stripe_connected', sa.Boolean(), default=False),
        sa.Column('timezone', sa.String(64), default='America/New_York'),
        sa.Column('phone', sa.String(32)),
        sa.Column('license_number', sa.String(64)),
        sa.Column('bio', sa.Text()),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('onboarding_completed', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_therapists_email', 'therapists', ['email'], unique=True)
    op.create_index('ix_therapists_google_sub', 'therapists', ['google_sub'], unique=True)
    op.create_index('ix_therapists_stripe_account_id', 'therapists', ['stripe_account_id'], unique=True)

    # clients
    op.create_table('clients',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('hashed_password', sa.String(255)),
        sa.Column('phone', sa.String(32)),
        sa.Column('is_active', sa.Boolean(), default=False),
        sa.Column('email_verified', sa.Boolean(), default=False),
        sa.Column('invite_token', sa.String(255)),
        sa.Column('invite_token_expires', sa.DateTime(timezone=True)),
        sa.Column('date_of_birth', sa.DateTime(timezone=True)),
        sa.Column('address', sa.Text()),
        sa.Column('timezone', sa.String(64)),
        sa.Column('notes', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_clients_email', 'clients', ['email'], unique=True)
    op.create_index('ix_clients_invite_token', 'clients', ['invite_token'])

    # therapist_clients
    op.create_table('therapist_clients',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('therapist_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('client_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('default_session_price', sa.Numeric(10, 2), nullable=False),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('notes', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(['therapist_id'], ['therapists.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('therapist_id', 'client_id', name='uq_therapist_client'),
    )
    op.create_index('ix_therapist_clients_therapist_id', 'therapist_clients', ['therapist_id'])
    op.create_index('ix_therapist_clients_client_id', 'therapist_clients', ['client_id'])

    # appointments
    op.create_table('appointments',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('therapist_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('client_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('canceled_at', sa.DateTime(timezone=True)),
        sa.Column('override_price', sa.Numeric(10, 2)),
        sa.Column('session_type', sa.String(128)),
        sa.Column('google_event_id', sa.String(255)),
        sa.Column('google_calendar_id', sa.String(255)),
        sa.Column('session_notes', sa.Text()),
        sa.Column('cancellation_reason', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(['therapist_id'], ['therapists.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_appointments_therapist_id', 'appointments', ['therapist_id'])
    op.create_index('ix_appointments_client_id', 'appointments', ['client_id'])
    op.create_index('ix_appointments_status', 'appointments', ['status'])
    op.create_index('ix_appointments_therapist_start', 'appointments', ['therapist_id', 'start_time'])
    op.create_index('ix_appointments_client_start', 'appointments', ['client_id', 'start_time'])
    op.create_index('ix_appointments_status_completed', 'appointments', ['status', 'completed_at'])

    # invoices
    op.create_table('invoices',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('therapist_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('client_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('appointment_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('invoice_number', sa.String(64), nullable=False),
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('due_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('paid_at', sa.DateTime(timezone=True)),
        sa.Column('stripe_payment_intent_id', sa.String(255)),
        sa.Column('stripe_payment_link', sa.String(500)),
        sa.Column('stripe_checkout_session_id', sa.String(255)),
        sa.Column('pdf_path', sa.String(500)),
        sa.Column('notes', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(['therapist_id'], ['therapists.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('invoice_number', name='uq_invoice_number'),
        sa.UniqueConstraint('appointment_id', name='uq_invoice_appointment'),
    )
    op.create_index('ix_invoices_therapist_id', 'invoices', ['therapist_id'])
    op.create_index('ix_invoices_client_id', 'invoices', ['client_id'])
    op.create_index('ix_invoices_status', 'invoices', ['status'])
    op.create_index('ix_invoices_therapist_status', 'invoices', ['therapist_id', 'status'])
    op.create_index('ix_invoices_client_status', 'invoices', ['client_id', 'status'])

    # payments
    op.create_table('payments',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('invoice_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('stripe_payment_intent_id', sa.String(255), nullable=False),
        sa.Column('stripe_charge_id', sa.String(255)),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('failure_reason', sa.Text()),
        sa.Column('paid_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('stripe_payment_intent_id', name='uq_payment_intent'),
    )
    op.create_index('ix_payments_invoice_id', 'payments', ['invoice_id'])


def downgrade():
    op.drop_table('payments')
    op.drop_table('invoices')
    op.drop_table('appointments')
    op.drop_table('therapist_clients')
    op.drop_table('clients')
    op.drop_table('therapists')
