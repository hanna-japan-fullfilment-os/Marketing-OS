"""ai_usage scope column (Build 6 repair, Critical Defect 7/13)

Adds one column, `scope`, to the existing `ai_usage` table so a usage row's
`platform`/`language` attribution is unambiguous: `scope="campaign_global"`
for a stage that is genuinely not bound to one requested platform/language
pairing (research, strategy, creative_brief, master_campaign_concept,
campaign_copy, carousel_plan), `scope="variant"` for everything attributed
to a specific rendered/scripted `PlatformCampaignVariant`. See
`app/models/platform.py::AIUsage` and `app/services/usage_tracking.py` for
the full rationale — a live-acceptance run showed cost rows with blank
platform/language that were impossible to tell apart from a bug versus an
intentionally campaign-wide call.

Defaults to `"variant"` (never NULL, matching this table's existing
string-column convention) — the common case, and a strictly more honest
default for any pre-migration row than an empty string would be.

Revision ID: b6c7d8e9f0a1
Revises: f7a8b9c0d1e2
Create Date: 2026-09-12 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b6c7d8e9f0a1'
down_revision: Union[str, Sequence[str], None] = 'f7a8b9c0d1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ai_usage', schema=None) as batch_op:
        batch_op.add_column(sa.Column('scope', sa.String(length=20), nullable=False, server_default='variant'))


def downgrade() -> None:
    with op.batch_alter_table('ai_usage', schema=None) as batch_op:
        batch_op.drop_column('scope')
