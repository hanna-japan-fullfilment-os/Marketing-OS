"""campaign target slide count

Revision ID: f1882366252f
Revises: b94f4ec947d4
Create Date: 2026-09-07 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1882366252f'
down_revision: Union[str, Sequence[str], None] = 'b94f4ec947d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.add_column(sa.Column('target_slide_count', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.drop_column('target_slide_count')
