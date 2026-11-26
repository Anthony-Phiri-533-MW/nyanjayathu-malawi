"""indicator results gap_interpolated flag

Revision ID: f3a9c1d2b4e5
Revises: 81e246e3d6e7
Create Date: 2026-11-27 00:00:00.000000

Adds ``indicator_results.gap_interpolated`` so cloud-gap interpolation is
recorded per result (Signature Challenge property 4).  ``server_default`` is
required because SQLite refuses ``ADD COLUMN`` of a NOT NULL column without
one; existing rows correctly default to not-interpolated (false).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'f3a9c1d2b4e5'
down_revision = '81e246e3d6e7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('indicator_results', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('gap_interpolated', sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table('indicator_results', schema=None) as batch_op:
        batch_op.drop_column('gap_interpolated')
