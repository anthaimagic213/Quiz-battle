"""Add ai_runs table for AI audit logging

Revision ID: 012_add_ai_runs
Revises: 011_add_email_login_otps
Create Date: 2026-06-11 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


# revision identifiers, used by Alembic.
revision = '012_add_ai_runs'
down_revision = '011_add_email_login_otps'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ai_runs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('conversation_id', UUID(as_uuid=True), sa.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_message_id', UUID(as_uuid=True), sa.ForeignKey('messages.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ai_message_id', UUID(as_uuid=True), sa.ForeignKey('messages.id', ondelete='SET NULL'), nullable=True),
        sa.Column('intent', sa.String(50), nullable=False),
        sa.Column('router_raw', JSONB, nullable=True),
        sa.Column('router_retries', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('tool_calls', JSONB, nullable=True),
        sa.Column('composer_system', sa.Text(), nullable=True),
        sa.Column('composer_user', sa.Text(), nullable=True),
        sa.Column('composer_raw', sa.Text(), nullable=True),
        sa.Column('prompt_tokens', sa.Integer(), nullable=True),
        sa.Column('completion_tokens', sa.Integer(), nullable=True),
        sa.Column('total_tokens', sa.Integer(), nullable=True),
        sa.Column('model_name', sa.String(100), nullable=True),
        sa.Column('router_ms', sa.Integer(), nullable=True),
        sa.Column('tool_ms', sa.Integer(), nullable=True),
        sa.Column('composer_ms', sa.Integer(), nullable=True),
        sa.Column('total_ms', sa.Integer(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # Index for lookup by conversation (newest first)
    op.create_index(
        op.f('ix_ai_runs_conversation_id_created_at'),
        'ai_runs',
        ['conversation_id', 'created_at'],
        unique=False,
    )

    # Index for lookup by user_message_id
    op.create_index(
        op.f('ix_ai_runs_user_message_id'),
        'ai_runs',
        ['user_message_id'],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f('ix_ai_runs_user_message_id'), table_name='ai_runs')
    op.drop_index(op.f('ix_ai_runs_conversation_id_created_at'), table_name='ai_runs')
    op.drop_table('ai_runs')
