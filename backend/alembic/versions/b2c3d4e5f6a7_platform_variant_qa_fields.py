"""platform_campaign_variants QA fields (Build 3, Parts A-H)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-13 09:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('platform_campaign_variants', schema=None) as batch_op:
        batch_op.add_column(sa.Column('qa_status', sa.String(length=20), nullable=False, server_default='PENDING'))
        batch_op.add_column(sa.Column('qa_scores', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('qa_hard_fails', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('qa_attempts', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('qa_evidence_paths', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('qa_versions', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('qa_notes', sa.Text(), nullable=False, server_default=''))

    # SQLite's ADD COLUMN can't express a JSON-typed server_default of '[]'/'{}'
    # portably — backfill the JSON columns' real default value row-by-row
    # instead, matching this project's own established pattern (see
    # f4a8c2e6b1d9's Python backfill for `campaigns.languages`/
    # `target_platforms`) rather than relying on a raw SQL json literal.
    connection = op.get_bind()
    variants_table = sa.table(
        'platform_campaign_variants',
        sa.column('id', sa.String),
        sa.column('qa_hard_fails', sa.JSON),
        sa.column('qa_evidence_paths', sa.JSON),
        sa.column('qa_versions', sa.JSON),
    )
    rows = connection.execute(sa.select(variants_table.c.id)).fetchall()
    for (row_id,) in rows:
        connection.execute(
            variants_table.update().where(variants_table.c.id == row_id).values(
                qa_hard_fails=[], qa_evidence_paths=[], qa_versions={},
            )
        )


def downgrade() -> None:
    with op.batch_alter_table('platform_campaign_variants', schema=None) as batch_op:
        batch_op.drop_column('qa_notes')
        batch_op.drop_column('qa_versions')
        batch_op.drop_column('qa_evidence_paths')
        batch_op.drop_column('qa_attempts')
        batch_op.drop_column('qa_hard_fails')
        batch_op.drop_column('qa_scores')
        batch_op.drop_column('qa_status')
