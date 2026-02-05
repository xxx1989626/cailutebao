"""add shift schedule columns

Revision ID: 3f2a1c7e9b0a
Revises: 2c6bcac6aa31
Create Date: 2026-02-05
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3f2a1c7e9b0a'
down_revision = '2c6bcac6aa31'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('shift_schedules', schema=None) as batch_op:
        batch_op.add_column(sa.Column('shift_type', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('is_overtime', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('hours', sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table('shift_schedules', schema=None) as batch_op:
        batch_op.drop_column('hours')
        batch_op.drop_column('is_overtime')
        batch_op.drop_column('shift_type')
