"""verified_product_facts table + campaigns.languages/target_platforms (Build 1)

Revision ID: f4a8c2e6b1d9
Revises: e7b3c5a9d1f4
Create Date: 2026-09-11 09:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4a8c2e6b1d9'
down_revision: Union[str, Sequence[str], None] = 'e7b3c5a9d1f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'verified_product_facts',
        sa.Column('product_id', sa.String(length=32), nullable=False),
        sa.Column('verified_description', sa.Text(), nullable=False, server_default=''),
        sa.Column('verified_ingredients', sa.JSON(), nullable=False),
        sa.Column('verified_features', sa.JSON(), nullable=False),
        sa.Column('verified_benefits', sa.JSON(), nullable=False),
        sa.Column('verified_usage', sa.Text(), nullable=False, server_default=''),
        sa.Column('verified_size', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('verified_variant', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('verified_price', sa.String(length=100), nullable=False, server_default=''),
        sa.Column('verified_availability', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('verified_country_of_origin', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('verified_claims', sa.JSON(), nullable=False),
        sa.Column('prohibited_claims', sa.JSON(), nullable=False),
        sa.Column('source_asset_ids', sa.JSON(), nullable=False),
        sa.Column('source_references', sa.JSON(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='0'),
        sa.Column('provenance', sa.String(length=200), nullable=False, server_default='owner_provided'),
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('product_id', name='uq_verified_product_facts_product_id'),
    )
    op.create_index(
        op.f('ix_verified_product_facts_product_id'), 'verified_product_facts', ['product_id'], unique=True,
    )

    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.add_column(sa.Column('languages', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('target_platforms', sa.JSON(), nullable=True))

    # Backfill existing rows so every campaign has a real, non-null structured
    # value instead of relying on the ORM's Python-side `default=` (which only
    # applies to newly-inserted rows, never rows that already existed before
    # this migration ran) — mirrors every existing campaign's own `language`
    # value where one is set, so no campaign's effective language silently
    # changes just because this migration ran. Done row-by-row in Python
    # (rather than a raw SQL `json_array(...)` expression) so this doesn't
    # depend on the SQLite build in use having the JSON1 extension compiled in.
    conn = op.get_bind()
    campaigns_t = sa.table(
        'campaigns',
        sa.column('id', sa.String),
        sa.column('language', sa.String),
        sa.column('languages', sa.JSON),
        sa.column('target_platforms', sa.JSON),
    )
    for row in conn.execute(sa.select(campaigns_t.c.id, campaigns_t.c.language)).fetchall():
        lang = row.language or 'pt-BR'
        conn.execute(
            campaigns_t.update()
            .where(campaigns_t.c.id == row.id)
            .values(languages=[lang], target_platforms=['instagram'])
        )

    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.alter_column('languages', nullable=False)
        batch_op.alter_column('target_platforms', nullable=False)


def downgrade() -> None:
    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.drop_column('target_platforms')
        batch_op.drop_column('languages')

    op.drop_index(op.f('ix_verified_product_facts_product_id'), table_name='verified_product_facts')
    op.drop_table('verified_product_facts')
