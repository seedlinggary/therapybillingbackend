"""Add admin_users table

Revision ID: 008
Revises: 007
Create Date: 2026-05-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'admin_users',
        sa.Column('id',              UUID(as_uuid=True), primary_key=True),
        sa.Column('email',           sa.String(255),     nullable=False, unique=True),
        sa.Column('name',            sa.String(255),     nullable=False),
        sa.Column('hashed_password', sa.String(255),     nullable=False),
        sa.Column('is_active',       sa.Boolean(),       nullable=False, server_default='true'),
        sa.Column('created_at',      sa.DateTime(timezone=True)),
    )
    op.create_index('ix_admin_users_email', 'admin_users', ['email'])


def downgrade():
    op.drop_index('ix_admin_users_email', table_name='admin_users')
    op.drop_table('admin_users')
