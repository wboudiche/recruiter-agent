"""users sessions oauth_states

Revision ID: 3e3db7988a1a
Revises: 6d81484ec385
Create Date: 2026-05-02 10:53:07.464926

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '3e3db7988a1a'
down_revision: Union[str, None] = '6d81484ec385'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=320), nullable=False),
        sa.Column('sub', sa.String(length=255), nullable=True),
        sa.Column('issuer', sa.String(length=512), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('picture', sa.String(length=2048), nullable=True),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('issuer', 'sub', name='uq_users_issuer_sub'),
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    op.create_table(
        'auth_sessions',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('user_agent', sa.String(length=512), nullable=True),
        sa.Column('ip', sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_auth_sessions_user', 'auth_sessions', ['user_id'])
    op.create_index('ix_auth_sessions_id_expires', 'auth_sessions', ['id', 'expires_at'])

    op.create_table(
        'oauth_states',
        sa.Column('state', sa.String(length=64), nullable=False),
        sa.Column('nonce', sa.String(length=64), nullable=False),
        sa.Column('pkce_verifier', sa.String(length=128), nullable=False),
        sa.Column('next_url', sa.String(length=2048), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('state'),
    )


def downgrade() -> None:
    op.drop_table('oauth_states')
    op.drop_index('ix_auth_sessions_id_expires', table_name='auth_sessions')
    op.drop_index('ix_auth_sessions_user', table_name='auth_sessions')
    op.drop_table('auth_sessions')
    op.drop_index('ix_users_email', table_name='users')
    op.drop_table('users')
