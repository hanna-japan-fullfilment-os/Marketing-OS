"""platform_campaign_variants table (Build 2, Part F)

Revision ID: a1b2c3d4e5f6
Revises: f4a8c2e6b1d9
Create Date: 2026-09-11 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f4a8c2e6b1d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'platform_campaign_variants',
        sa.Column('campaign_id', sa.String(length=32), nullable=False),
        sa.Column('target_platform', sa.String(length=30), nullable=False),
        sa.Column('language', sa.String(length=20), nullable=False),
        sa.Column('content_type', sa.String(length=50), nullable=False),
        sa.Column('render_format_key', sa.String(length=50), nullable=False, server_default=''),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='PENDING'),
        sa.Column('slide_asset_paths', sa.JSON(), nullable=False),
        sa.Column('copy_language', sa.String(length=20), nullable=False, server_default=''),
        sa.Column('creative_direction', sa.JSON(), nullable=False),
        sa.Column('video_concept', sa.JSON(), nullable=True),
        sa.Column('qa_report_paths', sa.JSON(), nullable=False),
        sa.Column('shared_scene_source', sa.String(length=50), nullable=False, server_default=''),
        sa.Column('notes', sa.Text(), nullable=False, server_default=''),
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'campaign_id', 'target_platform', 'language', 'content_type',
            name='uq_platform_variant',
        ),
    )
    op.create_index(
        op.f('ix_platform_campaign_variants_campaign_id'),
        'platform_campaign_variants', ['campaign_id'], unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_platform_campaign_variants_campaign_id'), table_name='platform_campaign_variants',
    )
    op.drop_table('platform_campaign_variants')
