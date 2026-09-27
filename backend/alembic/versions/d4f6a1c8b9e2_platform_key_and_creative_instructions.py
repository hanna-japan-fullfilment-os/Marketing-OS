"""campaign platform_key + brand creative_instructions (round 20)

Revision ID: d4f6a1c8b9e2
Revises: c3a1f9d2b6e4
Create Date: 2026-09-09 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4f6a1c8b9e2'
down_revision: Union[str, Sequence[str], None] = 'c3a1f9d2b6e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.add_column(sa.Column('platform_key', sa.String(length=50), nullable=True))
    with op.batch_alter_table('brands', schema=None) as batch_op:
        batch_op.add_column(sa.Column('creative_instructions', sa.Text(), nullable=False, server_default=''))


def downgrade() -> None:
    with op.batch_alter_table('brands', schema=None) as batch_op:
        batch_op.drop_column('creative_instructions')
    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.drop_column('platform_key')
