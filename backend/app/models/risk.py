"""ORM models + schema/indexing strategy.

risk_transactions
  id                     BIGINT PK (surrogate, monotonically increasing -> compact B-tree, cheap FK target)
  transaction_id         VARCHAR(40)  NOT NULL UNIQUE      public identifier (TXN + 20 hex)
  partner_id             VARCHAR(64)  NOT NULL
  masked_aadhaar_number  VARCHAR(20)  NOT NULL             e.g. XXXX-XXXX-1234 (raw number is never stored)
  device_data            JSON/JSONB   NOT NULL
  callback_url           VARCHAR(2048) NOT NULL
  risk_score             SMALLINT     NULL  (1..100)
  status                 VARCHAR(16)  NOT NULL  PENDING | PROCESSING | COMPLETED | FAILED
  idempotency_key        VARCHAR(160) NOT NULL UNIQUE
  created_at/updated_at  TIMESTAMPTZ  NOT NULL

Indexes (all three requested, plus two for the dashboard):
  ux_risk_transactions_transaction_id   UNIQUE (transaction_id)     -> worker lookups + uniqueness guarantee
  ix_risk_transactions_partner_id       (partner_id)                -> per-partner scans
  ix_risk_transactions_partner_txn      (partner_id, transaction_id)-> the audit query (equality on both
                                         columns, so it is a single B-tree descent, and an ownership check is
                                         enforced by the index key itself)
  ix_risk_transactions_partner_created  (partner_id, created_at)    -> history listing, newest first
  ix_risk_transactions_status           (status)                    -> worker/ops queries
  NOTE: (partner_id, transaction_id) already serves partner_id-only lookups as a left prefix, so
  ix_risk_transactions_partner_id is technically redundant; it is kept because the assignment asks for it.
  On a write-heavy production table you would drop it to save write amplification.

callback_retries
  id BIGINT PK, transaction_id FK -> risk_transactions.transaction_id (UNIQUE: one retry record per txn),
  retry_count, next_retry_at, last_error, status (PENDING | IN_PROGRESS | DONE | EXHAUSTED), created_at
  ix_callback_retries_due (status, next_retry_at) -> retry poller: "what is due now?"
"""
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.utils.time import utcnow

BigIntPK = BigInteger().with_variant(Integer, "sqlite")  # SQLite only autoincrements INTEGER PKs
JSONType = JSON().with_variant(JSONB(), "postgresql")

TXN_STATUSES = ("PENDING", "PROCESSING", "COMPLETED", "FAILED")
RETRY_STATUSES = ("PENDING", "IN_PROGRESS", "DONE", "EXHAUSTED")


class RiskTransaction(Base):
    __tablename__ = "risk_transactions"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    transaction_id: Mapped[str] = mapped_column(String(40), nullable=False)
    partner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    masked_aadhaar_number: Mapped[str] = mapped_column(String(20), nullable=False)
    device_data: Mapped[dict] = mapped_column(JSONType, nullable=False)
    callback_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    risk_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ux_risk_transactions_transaction_id", "transaction_id", unique=True),
        Index("ux_risk_transactions_idempotency_key", "idempotency_key", unique=True),
        Index("ix_risk_transactions_partner_id", "partner_id"),
        Index("ix_risk_transactions_partner_txn", "partner_id", "transaction_id"),
        Index("ix_risk_transactions_partner_created", "partner_id", "created_at"),
        Index("ix_risk_transactions_status", "status"),
        CheckConstraint("status IN ('PENDING','PROCESSING','COMPLETED','FAILED')", name="ck_risk_transactions_status"),
        CheckConstraint(
            "risk_score IS NULL OR (risk_score BETWEEN 1 AND 100)", name="ck_risk_transactions_score_range"
        ),
        CheckConstraint("masked_aadhaar_number LIKE 'XXXX-XXXX-%'", name="ck_risk_transactions_masked"),
    )


class CallbackRetry(Base):
    __tablename__ = "callback_retries"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    transaction_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("risk_transactions.transaction_id", ondelete="CASCADE"), nullable=False
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ux_callback_retries_transaction_id", "transaction_id", unique=True),
        Index("ix_callback_retries_due", "status", "next_retry_at"),
        CheckConstraint("retry_count >= 0", name="ck_callback_retries_count"),
        CheckConstraint(
            "status IN ('PENDING','IN_PROGRESS','DONE','EXHAUSTED')", name="ck_callback_retries_status"
        ),
    )
