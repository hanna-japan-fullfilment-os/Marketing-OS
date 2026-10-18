"""ai_usage budget guard adjustment for web-search accounting

Revision ID: dd7f8d847cd9
Revises: b6c7d8e9f0a1
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "dd7f8d847cd9"
down_revision: Union[str, Sequence[str], None] = "b6c7d8e9f0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ai_usage", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "budget_guard_adjustment_usd",
                sa.Float(),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_usage", schema=None) as batch_op:
        batch_op.drop_column(
            "budget_guard_adjustment_usd"
        )
