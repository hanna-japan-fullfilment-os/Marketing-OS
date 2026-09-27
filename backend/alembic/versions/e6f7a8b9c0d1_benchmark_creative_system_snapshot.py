"""benchmark_runs.creative_system_snapshot (Build 5 repair — Part 2)

Adds one new column to the existing `benchmark_runs` table: a complete,
immutable creative-system identity for that run (per-purpose prompt versions
— including any revision purpose that actually fired — plus the Verified
Product Facts resolver version, the renderer version, the template/layout
system version, and the run's own platform/language/content_type/
quality_mode). See `app/models/benchmark.py::BenchmarkRun.creative_system_
snapshot` and `app/services/benchmark_engine.py::build_creative_system_
snapshot` for the full rationale — this is deliberately additive alongside
the pre-existing `prompt_versions_snapshot`/`model_role_snapshot` columns,
not a replacement for either.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-09-12 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6f7a8b9c0d1'
down_revision: Union[str, Sequence[str], None] = 'd5e6f7a8b9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('benchmark_runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('creative_system_snapshot', sa.JSON(), nullable=True))

    # No backfill: this is a brand-new column on a table that, in practice, only
    # ever holds benchmark history — an existing row simply has an empty `{}`
    # snapshot (the model's own `default=dict`), honestly reflecting that no
    # complete creative-system snapshot was captured for a run made before this
    # migration, rather than a fabricated backfilled value.


def downgrade() -> None:
    with op.batch_alter_table('benchmark_runs', schema=None) as batch_op:
        batch_op.drop_column('creative_system_snapshot')
