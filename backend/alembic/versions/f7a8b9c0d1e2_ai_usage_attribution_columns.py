"""ai_usage platform/language/content_type attribution (Build 6)

Adds three columns to the existing `ai_usage` table so a usage row can be
attributed to a specific (platform, language, content_type) — i.e. a specific
`PlatformCampaignVariant` — not just a campaign as a whole. See
`app/models/platform.py::AIUsage` and `app/services/usage_tracking.py` for the
full rationale. All three default to `""` (never NULL, matching this table's
existing string-column convention), so an existing row logged before this
migration reads as "not platform/language-specific" rather than a fabricated
guess.

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-09-12 13:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7a8b9c0d1e2'
down_revision: Union[str, Sequence[str], None] = 'e6f7a8b9c0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ai_usage', schema=None) as batch_op:
        batch_op.add_column(sa.Column('platform', sa.String(length=30), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('language', sa.String(length=20), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('content_type', sa.String(length=50), nullable=False, server_default=''))


def downgrade() -> None:
    with op.batch_alter_table('ai_usage', schema=None) as batch_op:
        batch_op.drop_column('content_type')
        batch_op.drop_column('language')
        batch_op.drop_column('platform')
