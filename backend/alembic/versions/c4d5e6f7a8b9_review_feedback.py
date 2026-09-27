"""review_feedback table + human_review_status (Build 4)

Adds the one new table Build 4 introduces (`review_feedback` — see
`app/models/review.py::ReviewFeedback` for the full field-by-field
rationale) plus a `human_review_status` column on both `campaigns` and
`platform_campaign_variants`, deliberately kept separate from the existing
`status` (production pipeline stage) and `qa_status` (Build 3 automated
critic verdict) columns on those same tables.

Revision ID: c4d5e6f7a8b9
Revises: b2c3d4e5f6a7
Create Date: 2026-09-11 09:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('human_review_status', sa.String(length=20), nullable=False, server_default='PENDING')
        )

    with op.batch_alter_table('platform_campaign_variants', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('human_review_status', sa.String(length=20), nullable=False, server_default='PENDING')
        )

    op.create_table(
        'review_feedback',
        sa.Column('id', sa.String(length=32), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),

        sa.Column('campaign_id', sa.String(length=32), sa.ForeignKey('campaigns.id', ondelete='CASCADE'), nullable=False),
        sa.Column(
            'platform_campaign_variant_id', sa.String(length=32),
            sa.ForeignKey('platform_campaign_variants.id', ondelete='CASCADE'), nullable=True,
        ),

        sa.Column('level', sa.String(length=20), nullable=False),
        sa.Column('asset_ref', sa.String(length=100), nullable=False, server_default=''),

        sa.Column('action', sa.String(length=20), nullable=False),
        sa.Column('reason_code', sa.String(length=50), nullable=False, server_default=''),
        sa.Column('reason_text', sa.Text(), nullable=False, server_default=''),

        sa.Column('brand_id', sa.String(length=32), sa.ForeignKey('brands.id', ondelete='SET NULL'), nullable=True),
        sa.Column('category_id', sa.String(length=32), sa.ForeignKey('categories.id', ondelete='SET NULL'), nullable=True),
        sa.Column('product_id', sa.String(length=32), sa.ForeignKey('products.id', ondelete='SET NULL'), nullable=True),
        sa.Column('platform', sa.String(length=30), nullable=False, server_default=''),
        sa.Column('language', sa.String(length=20), nullable=False, server_default=''),
        sa.Column('content_type', sa.String(length=50), nullable=False, server_default=''),
        sa.Column('objective', sa.String(length=30), nullable=False, server_default=''),

        sa.Column('reviewed_slide_asset_paths', sa.JSON(), nullable=True),
        sa.Column('reviewed_video_concept', sa.JSON(), nullable=True),
        sa.Column('reviewed_copy_snapshot', sa.JSON(), nullable=True),
        sa.Column('reviewed_creative_direction', sa.JSON(), nullable=True),
        sa.Column('reviewed_qa_status', sa.String(length=20), nullable=False, server_default=''),
        sa.Column('reviewed_qa_scores', sa.JSON(), nullable=True),
        sa.Column('reviewed_qa_hard_fails', sa.JSON(), nullable=True),
        sa.Column('reviewed_qa_attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('reviewed_qa_evidence_paths', sa.JSON(), nullable=True),
        sa.Column('reviewed_qa_versions', sa.JSON(), nullable=True),
        sa.Column('reviewed_prompt_versions', sa.JSON(), nullable=True),

        sa.Column(
            'revision_of_feedback_id', sa.String(length=32),
            sa.ForeignKey('review_feedback.id', ondelete='SET NULL'), nullable=True,
        ),
    )
    with op.batch_alter_table('review_feedback', schema=None) as batch_op:
        batch_op.create_index('ix_review_feedback_campaign_id', ['campaign_id'])
        batch_op.create_index('ix_review_feedback_platform_campaign_variant_id', ['platform_campaign_variant_id'])
        batch_op.create_index('ix_review_feedback_brand_id', ['brand_id'])

    # Note: unlike b2c3d4e5f6a7 (which backfilled JSON columns row-by-row on an
    # already-populated table), `review_feedback` is a brand-new table on every
    # upgrade path, so there are never existing rows to backfill. The JSON
    # columns are nullable at the DB level (SQLite can't enforce a non-null
    # JSON default via CREATE TABLE the way the ORM model declares
    # `default=list`/`default=dict`) — the ORM layer, not the schema, is what
    # guarantees the non-null default for rows created going forward.


def downgrade() -> None:
    op.drop_table('review_feedback')

    with op.batch_alter_table('platform_campaign_variants', schema=None) as batch_op:
        batch_op.drop_column('human_review_status')

    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.drop_column('human_review_status')
