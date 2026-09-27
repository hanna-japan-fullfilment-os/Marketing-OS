"""inspiration assets (brand_assets.category_id)

Revision ID: b94f4ec947d4
Revises: a957c6dc54e6
Create Date: 2026-09-08 03:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b94f4ec947d4'
down_revision: Union[str, Sequence[str], None] = 'a957c6dc54e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('brand_assets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('category_id', sa.String(length=32), nullable=True))
        batch_op.create_index(op.f('ix_brand_assets_category_id'), ['category_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_brand_assets_category_id_categories', 'categories', ['category_id'], ['id'], ondelete='SET NULL',
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('brand_assets', schema=None) as batch_op:
        batch_op.drop_constraint('fk_brand_assets_category_id_categories', type_='foreignkey')
        batch_op.drop_index(op.f('ix_brand_assets_category_id'))
        batch_op.drop_column('category_id')
