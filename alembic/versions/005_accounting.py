"""accounting integration tables + therapist.country

Revision ID: 005
Revises: 004
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade():
    # ── therapist.country ────────────────────────────────────────────────────
    op.add_column('therapists',
        sa.Column('country', sa.String(8), nullable=False, server_default='US')
    )

    # ── accounting_integrations ───────────────────────────────────────────────
    op.create_table(
        'accounting_integrations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('therapist_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('therapists.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('provider', sa.String(32), nullable=False),  # 'icount' | 'internal'
        sa.Column('access_token_enc', sa.Text),                # Fernet-encrypted API key
        sa.Column('company_id', sa.String(128)),               # iCount cid
        sa.Column('username_enc', sa.Text),                    # Fernet-encrypted username
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('therapist_id', 'provider', name='uq_accounting_therapist_provider'),
    )

    # ── accounting_documents ─────────────────────────────────────────────────
    op.create_table(
        'accounting_documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('therapist_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('therapists.id', ondelete='RESTRICT'),
                  nullable=False, index=True),
        sa.Column('invoice_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('invoices.id', ondelete='SET NULL'),
                  nullable=True, index=True),
        sa.Column('parent_document_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('accounting_documents.id', ondelete='SET NULL'),
                  nullable=True),  # credit note → original document
        sa.Column('doc_type', sa.String(32), nullable=False),  # invoice|receipt|receipt_invoice|credit_note
        sa.Column('external_id', sa.String(255)),              # iCount document number
        sa.Column('pdf_url', sa.Text),
        sa.Column('status', sa.String(32), nullable=False, server_default='pending'),  # pending|issued|canceled|failed
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('currency', sa.String(8), nullable=False, server_default='USD'),
        sa.Column('vat_amount', sa.Numeric(10, 2)),            # IL only
        sa.Column('doc_metadata', sa.JSON),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── accounting_audit_logs ─────────────────────────────────────────────────
    op.create_table(
        'accounting_audit_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('therapist_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('therapists.id', ondelete='SET NULL'),
                  nullable=True, index=True),
        sa.Column('action', sa.String(64), nullable=False),    # create_invoice|create_receipt|cancel_document|resend_email|retry
        sa.Column('status', sa.String(16), nullable=False),    # success|failed
        sa.Column('entity_type', sa.String(32)),               # document|integration
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('error_message', sa.Text),
        sa.Column('log_metadata', sa.JSON),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_audit_logs_therapist_created',
                    'accounting_audit_logs', ['therapist_id', 'created_at'])

    # ── accounting_retry_jobs ─────────────────────────────────────────────────
    op.create_table(
        'accounting_retry_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('therapist_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('therapists.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('document_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('accounting_documents.id', ondelete='CASCADE'),
                  nullable=True),
        sa.Column('job_type', sa.String(64), nullable=False),  # create_receipt|create_invoice|create_credit_note
        sa.Column('payload', sa.JSON, nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='pending'),  # pending|retrying|succeeded|failed
        sa.Column('attempts', sa.Integer, nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer, nullable=False, server_default='6'),
        sa.Column('last_error', sa.Text),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_retry_jobs_status_next',
                    'accounting_retry_jobs', ['status', 'next_attempt_at'])


def downgrade():
    op.drop_table('accounting_retry_jobs')
    op.drop_table('accounting_audit_logs')
    op.drop_table('accounting_documents')
    op.drop_table('accounting_integrations')
    op.drop_column('therapists', 'country')
