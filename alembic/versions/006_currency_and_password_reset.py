"""multi-currency, default session price, and client password reset

Revision ID: 006
Revises: 005
Create Date: 2026-04-29
"""
from alembic import op
import sqlalchemy as sa

revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade():
    # ── clients: password reset fields ───────────────────────────────────────
    op.add_column('clients',
        sa.Column('reset_token', sa.String(255), nullable=True)
    )
    op.add_column('clients',
        sa.Column('reset_token_expires', sa.DateTime(timezone=True), nullable=True)
    )

    # ── therapists: currency + default session price ──────────────────────────
    op.add_column('therapists',
        sa.Column('default_currency', sa.String(3), nullable=False, server_default='USD')
    )
    op.add_column('therapists',
        sa.Column('ils_exchange_rate', sa.Numeric(10, 4), nullable=True, server_default='3.70')
    )
    op.add_column('therapists',
        sa.Column('default_session_price', sa.Numeric(10, 2), nullable=True)
    )

    # ── invoices: currency ────────────────────────────────────────────────────
    op.add_column('invoices',
        sa.Column('currency', sa.String(3), nullable=False, server_default='USD')
    )


def downgrade():
    op.drop_column('invoices', 'currency')
    op.drop_column('therapists', 'default_session_price')
    op.drop_column('therapists', 'ils_exchange_rate')
    op.drop_column('therapists', 'default_currency')
    op.drop_column('clients', 'reset_token_expires')
    op.drop_column('clients', 'reset_token')
