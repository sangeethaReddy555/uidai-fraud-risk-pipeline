"""initial schema: risk_transactions, callback_retries

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

BigIntPK = sa.BigInteger().with_variant(sa.Integer, "sqlite")
JSONType = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "risk_transactions",
        sa.Column("id", BigIntPK, primary_key=True, autoincrement=True),
        sa.Column("transaction_id", sa.String(40), nullable=False),
        sa.Column("partner_id", sa.String(64), nullable=False),
        sa.Column("masked_aadhaar_number", sa.String(20), nullable=False),
        sa.Column("device_data", JSONType, nullable=False),
        sa.Column("callback_url", sa.String(2048), nullable=False),
        sa.Column("risk_score", sa.SmallInteger, nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('PENDING','PROCESSING','COMPLETED','FAILED')", name="ck_risk_transactions_status"),
        sa.CheckConstraint("risk_score IS NULL OR (risk_score BETWEEN 1 AND 100)", name="ck_risk_transactions_score_range"),
        sa.CheckConstraint("masked_aadhaar_number LIKE 'XXXX-XXXX-%'", name="ck_risk_transactions_masked"),
    )
    op.create_index("ux_risk_transactions_transaction_id", "risk_transactions", ["transaction_id"], unique=True)
    op.create_index("ux_risk_transactions_idempotency_key", "risk_transactions", ["idempotency_key"], unique=True)
    op.create_index("ix_risk_transactions_partner_id", "risk_transactions", ["partner_id"])
    op.create_index("ix_risk_transactions_partner_txn", "risk_transactions", ["partner_id", "transaction_id"])
    op.create_index("ix_risk_transactions_partner_created", "risk_transactions", ["partner_id", "created_at"])
    op.create_index("ix_risk_transactions_status", "risk_transactions", ["status"])

    op.create_table(
        "callback_retries",
        sa.Column("id", BigIntPK, primary_key=True, autoincrement=True),
        sa.Column("transaction_id", sa.String(40), sa.ForeignKey("risk_transactions.transaction_id", ondelete="CASCADE"), nullable=False),
        sa.Column("retry_count", sa.Integer, nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("retry_count >= 0", name="ck_callback_retries_count"),
        sa.CheckConstraint("status IN ('PENDING','IN_PROGRESS','DONE','EXHAUSTED')", name="ck_callback_retries_status"),
    )
    op.create_index("ux_callback_retries_transaction_id", "callback_retries", ["transaction_id"], unique=True)
    op.create_index("ix_callback_retries_due", "callback_retries", ["status", "next_retry_at"])


def downgrade() -> None:
    op.drop_table("callback_retries")
    op.drop_table("risk_transactions")
