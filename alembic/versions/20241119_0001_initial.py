"""Local copy of campaigns, streams and offer bindings."""

from alembic import op
import sqlalchemy as sa

revision = "20241119_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("keitaro_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("alias", sa.String(length=255), nullable=True),
        sa.Column("domain_name", sa.String(length=255), nullable=True),
        sa.Column("group_name", sa.String(length=255), nullable=True),
        sa.Column("source_name", sa.String(length=255), nullable=True),
    )
    op.create_index("ix_campaigns_keitaro_id", "campaigns", ["keitaro_id"], unique=True)

    op.create_table(
        "streams",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("keitaro_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("offer_stream", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("dirty", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("published_json", sa.Text(), nullable=False, server_default="[]"),
    )
    op.create_index("ix_streams_campaign_id", "streams", ["campaign_id"])
    op.create_index("uq_streams_campaign_keitaro", "streams", ["campaign_id", "keitaro_id"], unique=True)

    op.create_table(
        "offer_bindings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stream_id", sa.Integer(), sa.ForeignKey("streams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("offer_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("share", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("pending_add", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_offer_bindings_stream_id", "offer_bindings", ["stream_id"])
    op.create_index("uq_offer_bindings_stream_offer", "offer_bindings", ["stream_id", "offer_id"], unique=True)


def downgrade() -> None:
    op.drop_table("offer_bindings")
    op.drop_table("streams")
    op.drop_table("campaigns")
