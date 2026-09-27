"""benchmark_cases + benchmark_runs tables, prompt_versions applicability/active (Build 5)

Adds the two new tables Build 5 introduces (`benchmark_cases`,
`benchmark_runs` — see `app/models/benchmark.py` for the full field-by-field
rationale) plus three new columns on the existing `prompt_versions` table
(`platform_applicability`, `language_applicability`, `active`) completing
Part A's own "prompt metadata should support platform applicability,
language applicability, version, active status" requirement.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-09-13 09:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, Sequence[str], None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('prompt_versions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('platform_applicability', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('language_applicability', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()))

    op.create_table(
        'benchmark_cases',
        sa.Column('id', sa.String(length=32), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),

        sa.Column('name', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('notes', sa.Text(), nullable=False, server_default=''),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='ACTIVE'),

        sa.Column('brand_id', sa.String(length=32), sa.ForeignKey('brands.id', ondelete='CASCADE'), nullable=False),
        sa.Column('product_id', sa.String(length=32), sa.ForeignKey('products.id', ondelete='SET NULL'), nullable=True),
        sa.Column('category_id', sa.String(length=32), sa.ForeignKey('categories.id', ondelete='SET NULL'), nullable=True),
        sa.Column('platform', sa.String(length=30), nullable=False),
        sa.Column('content_type', sa.String(length=50), nullable=False, server_default=''),
        sa.Column('language', sa.String(length=20), nullable=False),
        sa.Column('objective', sa.String(length=30), nullable=False, server_default=''),
        sa.Column('audience', sa.Text(), nullable=False, server_default=''),

        sa.Column('source_asset_paths', sa.JSON(), nullable=True),
        sa.Column('verified_product_facts_snapshot', sa.JSON(), nullable=True),

        sa.Column('expected_truths', sa.JSON(), nullable=True),
        sa.Column('prohibited_claims', sa.JSON(), nullable=True),
        sa.Column('expected_creative_characteristics', sa.JSON(), nullable=True),

        sa.Column('baseline_output_snapshot', sa.JSON(), nullable=True),
        sa.Column('owner_rating', sa.String(length=20), nullable=False, server_default=''),
        sa.Column(
            'source_feedback_id', sa.String(length=32),
            sa.ForeignKey('review_feedback.id', ondelete='SET NULL'), nullable=True,
        ),
    )
    with op.batch_alter_table('benchmark_cases', schema=None) as batch_op:
        batch_op.create_index('ix_benchmark_cases_brand_id', ['brand_id'])
        batch_op.create_index('ix_benchmark_cases_platform', ['platform'])
        batch_op.create_index('ix_benchmark_cases_language', ['language'])
        batch_op.create_index('ix_benchmark_cases_status', ['status'])

    op.create_table(
        'benchmark_runs',
        sa.Column('id', sa.String(length=32), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),

        sa.Column(
            'benchmark_case_id', sa.String(length=32),
            sa.ForeignKey('benchmark_cases.id', ondelete='CASCADE'), nullable=False,
        ),
        sa.Column('mode', sa.String(length=20), nullable=False),
        sa.Column('platform', sa.String(length=30), nullable=False),
        sa.Column('language', sa.String(length=20), nullable=False),

        sa.Column('campaign_id', sa.String(length=32), nullable=True),
        sa.Column(
            'variant_id', sa.String(length=32),
            sa.ForeignKey('platform_campaign_variants.id', ondelete='SET NULL'), nullable=True,
        ),

        sa.Column('prompt_versions_snapshot', sa.JSON(), nullable=True),
        sa.Column('model_role_snapshot', sa.JSON(), nullable=True),

        sa.Column('qa_status', sa.String(length=20), nullable=False, server_default=''),
        sa.Column('human_review_status', sa.String(length=20), nullable=False, server_default=''),
        sa.Column('qa_scores', sa.JSON(), nullable=True),
        sa.Column('hard_fails', sa.JSON(), nullable=True),

        sa.Column('weighted_score', sa.Float(), nullable=True),
        sa.Column('weights_used', sa.JSON(), nullable=True),

        sa.Column('cost_breakdown', sa.JSON(), nullable=True),

        sa.Column('is_baseline', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('notes', sa.Text(), nullable=False, server_default=''),
    )
    with op.batch_alter_table('benchmark_runs', schema=None) as batch_op:
        batch_op.create_index('ix_benchmark_runs_benchmark_case_id', ['benchmark_case_id'])
        batch_op.create_index('ix_benchmark_runs_platform', ['platform'])
        batch_op.create_index('ix_benchmark_runs_language', ['language'])

    # No backfill loop needed: `prompt_versions` rows are re-seeded from
    # scratch on every app startup (`services/seed.py::seed_all` ->
    # `ensure_prompt_versions_seeded`, an idempotent upsert-by-purpose), so
    # the new columns' real values land on the very next startup rather than
    # needing a one-time migration backfill here — matches how `prompt_
    # versions` itself was originally introduced. `benchmark_cases`/
    # `benchmark_runs` are brand-new tables with no existing rows to migrate.


def downgrade() -> None:
    op.drop_table('benchmark_runs')
    op.drop_table('benchmark_cases')

    with op.batch_alter_table('prompt_versions', schema=None) as batch_op:
        batch_op.drop_column('active')
        batch_op.drop_column('language_applicability')
        batch_op.drop_column('platform_applicability')
