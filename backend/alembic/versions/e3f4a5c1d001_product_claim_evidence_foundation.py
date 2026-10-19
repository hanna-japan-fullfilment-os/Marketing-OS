"""BUILD6R V3.45 product claim evidence foundation.

Revision ID: e3f4a5c1d001
Revises: dd7f8d847cd9
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3f4a5c1d001"
down_revision: Union[
    str,
    Sequence[str],
    None,
] = "dd7f8d847cd9"

branch_labels: Union[
    str,
    Sequence[str],
    None,
] = None

depends_on: Union[
    str,
    Sequence[str],
    None,
] = None


def upgrade() -> None:
    op.create_table(
        "product_claim_evidence",

        sa.Column(
            "product_id",
            sa.String(length=32),
            nullable=False,
        ),

        sa.Column(
            "research_run_id",
            sa.String(length=32),
            nullable=True,
        ),

        sa.Column(
            "research_insight_id",
            sa.String(length=32),
            nullable=True,
        ),

        sa.Column(
            "claim_key",
            sa.String(length=64),
            nullable=False,
        ),

        sa.Column(
            "claim_text",
            sa.Text(),
            nullable=False,
        ),

        sa.Column(
            "normalized_claim",
            sa.Text(),
            nullable=False,
        ),

        sa.Column(
            "claim_type",
            sa.String(length=40),
            nullable=False,
        ),

        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="candidate",
        ),

        sa.Column(
            "evidence_strength",
            sa.String(length=40),
            nullable=False,
            server_default="",
        ),

        sa.Column(
            "marketing_eligible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),

        sa.Column(
            "source_ids",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),

        sa.Column(
            "source_excerpt",
            sa.Text(),
            nullable=False,
            server_default="",
        ),

        sa.Column(
            "source_scope",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),

        sa.Column(
            "territory",
            sa.String(length=100),
            nullable=False,
            server_default="",
        ),

        sa.Column(
            "evidence_period",
            sa.String(length=200),
            nullable=False,
            server_default="",
        ),

        sa.Column(
            "footnote",
            sa.Text(),
            nullable=False,
            server_default="",
        ),

        sa.Column(
            "rejection_reason",
            sa.Text(),
            nullable=False,
            server_default="",
        ),

        sa.Column(
            "verification_method",
            sa.String(length=100),
            nullable=False,
            server_default="",
        ),

        sa.Column(
            "verifier",
            sa.String(length=200),
            nullable=False,
            server_default="",
        ),

        sa.Column(
            "verified_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),

        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),

        sa.Column(
            "promoted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),

        sa.Column(
            "id",
            sa.String(length=32),
            nullable=False,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),

        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),

        sa.CheckConstraint(
            (
                "status IN "
                "('candidate', 'verified', 'rejected')"
            ),
            name="ck_product_claim_evidence_status",
        ),

        sa.CheckConstraint(
            (
                "evidence_strength IN "
                "('', 'official_primary', "
                "'official_secondary', "
                "'authoritative_third_party', "
                "'owner_confirmed')"
            ),
            name="ck_product_claim_evidence_strength",
        ),

        sa.CheckConstraint(
            (
                "claim_type IN "
                "('ingredient', 'composition', "
                "'feature', 'benefit', 'usage', "
                "'size', 'origin', 'ranking', "
                "'award', 'quantified_result', "
                "'certification', "
                "'regulatory_status', "
                "'popularity', 'availability', "
                "'other')"
            ),
            name="ck_product_claim_evidence_type",
        ),

        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            ondelete="CASCADE",
        ),

        sa.ForeignKeyConstraint(
            ["research_run_id"],
            ["research_runs.id"],
            ondelete="SET NULL",
        ),

        sa.ForeignKeyConstraint(
            ["research_insight_id"],
            ["research_insights.id"],
            ondelete="SET NULL",
        ),

        sa.PrimaryKeyConstraint(
            "id"
        ),

        sa.UniqueConstraint(
            "product_id",
            "claim_key",
            name=(
                "uq_product_claim_evidence_"
                "product_key"
            ),
        ),
    )

    op.create_index(
        "ix_product_claim_evidence_product_id",
        "product_claim_evidence",
        ["product_id"],
        unique=False,
    )

    op.create_index(
        "ix_product_claim_evidence_research_run_id",
        "product_claim_evidence",
        ["research_run_id"],
        unique=False,
    )

    op.create_index(
        "ix_product_claim_evidence_research_insight_id",
        "product_claim_evidence",
        ["research_insight_id"],
        unique=False,
    )

    op.create_index(
        "ix_product_claim_evidence_status",
        "product_claim_evidence",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_product_claim_evidence_status",
        table_name="product_claim_evidence",
    )

    op.drop_index(
        "ix_product_claim_evidence_research_insight_id",
        table_name="product_claim_evidence",
    )

    op.drop_index(
        "ix_product_claim_evidence_research_run_id",
        table_name="product_claim_evidence",
    )

    op.drop_index(
        "ix_product_claim_evidence_product_id",
        table_name="product_claim_evidence",
    )

    op.drop_table(
        "product_claim_evidence"
    )
