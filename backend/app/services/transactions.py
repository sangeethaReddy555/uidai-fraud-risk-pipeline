"""Transaction creation, audit lookup, listing and stats."""
import logging
import uuid
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import RiskTransaction
from app.utils.masking import mask_aadhaar
from app.utils.time import utcnow

log = logging.getLogger("risk.transactions")

# EXACT audit query required by the assignment. Both predicates are equality checks that
# line up with the composite index (partner_id, transaction_id); only 6 narrow columns
# are selected; LIMIT 1 lets the engine stop after the first hit. Ownership is enforced
# *in the query itself*, so another partner's row can never even be loaded (anti-IDOR).
AUDIT_SQL = text(
    """
    SELECT transaction_id,
           partner_id,
           status,
           risk_score,
           created_at,
           updated_at
    FROM risk_transactions
    WHERE transaction_id = :transaction_id
      AND partner_id = :partner_id
    LIMIT 1
    """
)


def new_transaction_id() -> str:
    return "TXN" + uuid.uuid4().hex[:20].upper()


def create_transaction(
    db: Session,
    *,
    partner_id: str,
    aadhaar_number: str,
    device_data: dict,
    callback_url: str,
    idempotency_header: str | None,
) -> tuple[RiskTransaction, bool]:
    """Returns (transaction, created). The raw Aadhaar is masked here and never persisted."""
    masked = mask_aadhaar(aadhaar_number)
    if idempotency_header:
        key = f"{partner_id}:{idempotency_header}"
        existing = db.scalar(select(RiskTransaction).where(RiskTransaction.idempotency_key == key))
        if existing:
            return existing, False
    txn_id = new_transaction_id()
    key = f"{partner_id}:{idempotency_header}" if idempotency_header else txn_id
    now = utcnow()
    txn = RiskTransaction(
        transaction_id=txn_id,
        partner_id=partner_id,
        masked_aadhaar_number=masked,
        device_data=device_data,
        callback_url=callback_url,
        status="PENDING",
        idempotency_key=key,
        created_at=now,
        updated_at=now,
    )
    db.add(txn)
    try:
        db.commit()
    except IntegrityError:  # concurrent request with the same Idempotency-Key
        db.rollback()
        existing = db.scalar(select(RiskTransaction).where(RiskTransaction.idempotency_key == key))
        if existing:
            return existing, False
        raise
    return txn, True


def mark_publish_failed(db: Session, txn_id: str) -> None:
    db.execute(
        update(RiskTransaction)
        .where(RiskTransaction.transaction_id == txn_id, RiskTransaction.status == "PENDING")
        .values(status="FAILED", updated_at=utcnow())
    )
    db.commit()


def audit_lookup(db: Session, transaction_id: str, partner_id: str) -> dict | None:
    row = db.execute(AUDIT_SQL, {"transaction_id": transaction_id, "partner_id": partner_id}).mappings().first()
    return dict(row) if row else None


def list_transactions(
    db: Session, partner_id: str, *, status: str | None, search: str | None, limit: int, offset: int
) -> tuple[list[RiskTransaction], int]:
    conds = [RiskTransaction.partner_id == partner_id]
    if status:
        conds.append(
            RiskTransaction.status.in_(("PENDING", "PROCESSING")) if status == "PENDING" else RiskTransaction.status == status
        )
    if search:
        like = f"%{search.replace('%', '').replace('_', '')}%"
        conds.append(RiskTransaction.transaction_id.like(like))
    total = db.scalar(select(func.count()).select_from(RiskTransaction).where(*conds)) or 0
    items = db.scalars(
        select(RiskTransaction)
        .where(*conds)
        .order_by(RiskTransaction.created_at.desc(), RiskTransaction.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return list(items), total


def stats(db: Session, partner_id: str) -> dict:
    rows = dict(
        db.execute(
            select(RiskTransaction.status, func.count()).where(RiskTransaction.partner_id == partner_id).group_by(RiskTransaction.status)
        ).all()
    )
    avg = db.scalar(
        select(func.avg(RiskTransaction.risk_score)).where(
            RiskTransaction.partner_id == partner_id, RiskTransaction.risk_score.is_not(None)
        )
    )
    buckets = {"low": 0, "medium": 0, "high": 0}
    for lo, hi, name in ((1, 33, "low"), (34, 66, "medium"), (67, 100, "high")):
        buckets[name] = (
            db.scalar(
                select(func.count()).where(
                    RiskTransaction.partner_id == partner_id, RiskTransaction.risk_score.between(lo, hi)
                )
            )
            or 0
        )
    return {
        "total": sum(rows.values()),
        "pending": rows.get("PENDING", 0) + rows.get("PROCESSING", 0),
        "completed": rows.get("COMPLETED", 0),
        "failed": rows.get("FAILED", 0),
        "average_risk_score": round(float(avg), 1) if avg is not None else None,
        "risk_buckets": buckets,
    }
