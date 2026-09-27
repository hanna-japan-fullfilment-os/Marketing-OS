"""campaign discovery products (round 19)

Revision ID: c3a1f9d2b6e4
Revises: f1882366252f
Create Date: 2026-09-08 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3a1f9d2b6e4'
down_revision: Union[str, Sequence[str], None] = 'f1882366252f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'campaign_discovery_products',
        sa.Column('campaign_id', sa.String(length=32), nullable=False),
        sa.Column('product_id', sa.String(length=32), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('campaign_id', 'product_id', name='uq_discovery_campaign_product'),
    )
    op.create_index(
        op.f('ix_campaign_discovery_products_campaign_id'),
        'campaign_discovery_products', ['campaign_id'], unique=False,
    )
    op.create_index(
        op.f('ix_campaign_discovery_products_product_id'),
        'campaign_discovery_products', ['product_id'], unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_campaign_discovery_products_product_id'), table_name='campaign_discovery_products')
    op.drop_index(op.f('ix_campaign_discovery_products_campaign_id'), table_name='campaign_discovery_products')
    op.drop_table('campaign_discovery_products')
