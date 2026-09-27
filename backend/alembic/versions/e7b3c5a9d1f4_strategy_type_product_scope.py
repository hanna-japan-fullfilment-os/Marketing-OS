"""campaign_strategy_types.product_scope (round 20)

Revision ID: e7b3c5a9d1f4
Revises: d4f6a1c8b9e2
Create Date: 2026-09-09 12:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7b3c5a9d1f4'
down_revision: Union[str, Sequence[str], None] = 'd4f6a1c8b9e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('campaign_strategy_types', schema=None) as batch_op:
        batch_op.add_column(sa.Column('product_scope', sa.String(length=10), nullable=False, server_default='either'))


def downgrade() -> None:
    with op.batch_alter_table('campaign_strategy_types', schema=None) as batch_op:
        batch_op.drop_column('product_scope')
