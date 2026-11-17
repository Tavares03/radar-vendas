"""fila no postgres

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-15 19:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0005'
down_revision: str | Sequence[str] | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('job_queue',
    sa.Column('id', sa.String(length=160), nullable=False),
    sa.Column('func', sa.String(length=200), nullable=False),
    sa.Column('args', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('kwargs', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('run_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('max_retries', sa.Integer(), nullable=False),
    sa.Column('timeout_seconds', sa.Integer(), nullable=False),
    sa.Column('enqueued_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_job_queue'))
    )
    op.create_index('ix_job_queue_pending', 'job_queue', ['status', 'run_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_job_queue_pending', table_name='job_queue')
    op.drop_table('job_queue')
