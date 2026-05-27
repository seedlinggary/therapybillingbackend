"""Add business_type to therapists and create service_types table

Revision ID: 013
Revises: 012
Create Date: 2026-05-27
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '013'
down_revision = '012'
branch_labels = None
depends_on = None


def upgrade():
    # ── 1. Add business_type to therapists ──────────────────────────────────
    op.add_column('therapists', sa.Column('business_type', sa.String(128), nullable=True))

    # Seed existing therapists as 'Therapist'
    op.execute("UPDATE therapists SET business_type = 'Therapist' WHERE business_type IS NULL")

    # ── 2. Create service_types table ────────────────────────────────────────
    op.create_table(
        'service_types',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('therapist_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('therapists.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(128), nullable=False),
        sa.Column('duration_minutes', sa.Integer(), nullable=False, server_default='50'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_service_types_therapist_id', 'service_types', ['therapist_id'])

    # ── 3. Seed default service types for all existing therapists ────────────
    for name in ('Individual', 'Couples', 'Family', 'Group'):
        op.execute(f"""
            INSERT INTO service_types (id, therapist_id, name, duration_minutes, is_active, created_at)
            SELECT gen_random_uuid(), id, '{name}', 50, true, NOW()
            FROM therapists
        """)


def downgrade():
    op.drop_index('ix_service_types_therapist_id', table_name='service_types')
    op.drop_table('service_types')
    op.drop_column('therapists', 'business_type')
