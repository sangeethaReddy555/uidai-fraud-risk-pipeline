"""Risk evaluation worker: idempotent event handling + non-blocking callback retries.

Concurrency / idempotency design
--------------------------------
1. CLAIM: UPDATE risk_transactions SET status='PROCESSING', risk_score=:s
          WHERE transaction_id=:t AND status='PENDING'
   This single statement is atomic in PostgreSQL and SQLite. When N duplicate events race,
   exactly one UPDATE affects a row (rowcount == 1); the rest see rowcount == 0 and are
   acknowledged as duplicates without scoring or calling back. No in-process lock is needed,
   so this also holds across multiple worker processes / consumer-group members.
2. COMPLETE: `UPDATE ... SET status='COMPLETED' WHERE transaction_id=:t AND status='PROCESSING'`
   -> COMPLETED can be written at most once.
3. NON-BLOCKING RETRIES: if the first callback attempt fails temporarily (5xx incl. 503, 408/425/429,
   timeouts) we persist a row in `callback_retries` with next_retry_at (exponential backoff + jitter)
   and return immediately, so the Kafka consumer moves on to the next event. A separate retry loop
   (run_retry_cycle) delivers due callbacks, claiming each row atomically (PENDING -> IN_PROGRESS).
4. Failures: permanent errors (other 4xx, blocked URL) or exhausted retries mark the transaction FAILED.
5. Crash recovery: `recover_stalled` re-queues transactions stuck in PROCESSING with no retry row.
"""
import logging
import random
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models import CallbackRetry, RiskTransaction
from app.services.callback import CallbackResult, CallbackSender, HttpCallbackSender, classify
from app.utils.time import as_utc, utcnow

log = logging.getLogger("risk.worker")


class RiskWorker:
    def __init__(
        self,
        session_factory: sessionmaker,
        settings: Settings,
        sender: CallbackSender | None = None,
        rng: random.Random | None = None,
    ):
        self.session_factory = session_factory
        self.settings = settings
        self.sender = sender or HttpCallbackSender(settings)
        self.rng = rng or random.Random()

    # ---------------------------------------------------------------- events
    def handle_event(self, event: dict) -> str:
        """Process one Risk_Evaluation_Requested event.

        Returns one of: completed | retry_scheduled | failed | duplicate | not_found | invalid.
        Never sleeps and never waits on retries.
        """
        txn_id = event.get("transaction_id") if isinstance(event, dict) else None
        if not isinstance(txn_id, str) or not txn_id:
            log.warning("event rejected: missing transaction_id")
            return "invalid"

        score = self.rng.randint(1, 100)
        with self.session_factory() as db:
            claimed = db.execute(
                update(RiskTransaction)
                .where(RiskTransaction.transaction_id == txn_id, RiskTransaction.status == "PENDING")
                .values(status="PROCESSING", risk_score=score, updated_at=utcnow())
            ).rowcount
            db.commit()
            if claimed != 1:
                exists = db.scalar(select(RiskTransaction.id).where(RiskTransaction.transaction_id == txn_id))
                if exists is None:
                    log.warning("event for unknown transaction %s", txn_id)
                    return "not_found"
                log.info("duplicate event ignored for %s", txn_id)
                return "duplicate"
            txn = db.scalar(select(RiskTransaction).where(RiskTransaction.transaction_id == txn_id))
            payload = self._payload(txn)
            url = txn.callback_url

        log.info("scoring %s for partner %s -> score=%s", txn_id, payload["partner_id"], payload["risk_score"])
        result = self.sender.send(url, payload)
        return self._after_first_attempt(txn_id, result)

    @staticmethod
    def _payload(txn: RiskTransaction) -> dict:
        return {
            "transaction_id": txn.transaction_id,
            "risk_score": txn.risk_score,
            "status": "COMPLETED",
            "partner_id": txn.partner_id,
            "masked_aadhaar_number": txn.masked_aadhaar_number,
            "device_id": (txn.device_data or {}).get("device_id"),
        }

    def _after_first_attempt(self, txn_id: str, result: CallbackResult) -> str:
        kind = classify(result)
        with self.session_factory() as db:
            if kind == "success":
                self._complete(db, txn_id)
                db.commit()
                log.info("callback delivered for %s", txn_id)
                return "completed"
            err = self._describe(result)
            if kind == "permanent":
                self._fail(db, txn_id, err, record_retry_row=True)
                db.commit()
                log.error("callback permanently failed for %s: %s", txn_id, err)
                return "failed"
            db.add(
                CallbackRetry(
                    transaction_id=txn_id,
                    retry_count=0,
                    next_retry_at=utcnow() + self._backoff(0),
                    last_error=err,
                    status="PENDING",
                )
            )
            db.commit()
            log.warning("callback for %s failed temporarily (%s); retry scheduled", txn_id, err)
            return "retry_scheduled"

    # --------------------------------------------------------------- retries
    def run_retry_cycle(self, now: datetime | None = None) -> int:
        """Deliver all due callbacks. Returns the number of attempts made. Safe to run concurrently."""
        now = now or utcnow()
        with self.session_factory() as db:
            due = db.scalars(
                select(CallbackRetry.id)
                .where(CallbackRetry.status == "PENDING", CallbackRetry.next_retry_at <= now)
                .order_by(CallbackRetry.next_retry_at)
                .limit(self.settings.retry_batch_size)
            ).all()
        if not due:
            return 0
        with ThreadPoolExecutor(max_workers=self.settings.retry_concurrency) as pool:
            return sum(pool.map(self._attempt_retry, due))

    def _attempt_retry(self, retry_id: int) -> int:
        with self.session_factory() as db:
            claimed = db.execute(
                update(CallbackRetry).where(CallbackRetry.id == retry_id, CallbackRetry.status == "PENDING").values(status="IN_PROGRESS")
            ).rowcount
            db.commit()
            if claimed != 1:
                return 0  # another retry worker took it
            row = db.get(CallbackRetry, retry_id)
            txn = db.scalar(select(RiskTransaction).where(RiskTransaction.transaction_id == row.transaction_id))
            payload, url, txn_id = self._payload(txn), txn.callback_url, txn.transaction_id

        result = self.sender.send(url, payload)  # outside any DB transaction
        kind = classify(result)

        with self.session_factory() as db:
            row = db.get(CallbackRetry, retry_id)
            if kind == "success":
                row.status, row.last_error = "DONE", None
                self._complete(db, txn_id)
                log.info("retry delivered callback for %s after %s retries", txn_id, row.retry_count + 1)
            else:
                row.retry_count += 1
                row.last_error = self._describe(result)
                if kind == "permanent" or row.retry_count >= self.settings.callback_max_retries:
                    row.status = "EXHAUSTED"
                    self._fail(db, txn_id, row.last_error, record_retry_row=False)
                    log.error("callback for %s exhausted after %s retries", txn_id, row.retry_count)
                else:
                    row.status = "PENDING"
                    row.next_retry_at = utcnow() + self._backoff(row.retry_count)
                    log.warning("retry %s for %s failed (%s)", row.retry_count, txn_id, row.last_error)
            db.commit()
        return 1

    def recover_stalled(self, now: datetime | None = None) -> int:
        """Re-queue PROCESSING transactions that have no retry row (worker crashed mid-flight)."""
        now = now or utcnow()
        cutoff = now - timedelta(seconds=self.settings.stalled_processing_seconds)
        recovered = 0
        with self.session_factory() as db:
            stalled = db.scalars(
                select(RiskTransaction.transaction_id)
                .outerjoin(CallbackRetry, CallbackRetry.transaction_id == RiskTransaction.transaction_id)
                .where(RiskTransaction.status == "PROCESSING", RiskTransaction.updated_at < cutoff, CallbackRetry.id.is_(None))
            ).all()
            for txn_id in stalled:
                db.add(CallbackRetry(transaction_id=txn_id, retry_count=0, next_retry_at=now, last_error="recovered after stall", status="PENDING"))
                recovered += 1
            try:
                db.commit()
            except Exception:  # another recoverer won (unique transaction_id)
                db.rollback()
                recovered = 0
        return recovered

    # --------------------------------------------------------------- helpers
    def _backoff(self, retry_count: int) -> timedelta:
        s = self.settings
        delay = min(s.callback_backoff_max_seconds, s.callback_backoff_base_seconds * (2**retry_count))
        delay *= 1 + self.rng.uniform(0, s.callback_backoff_jitter)
        return timedelta(seconds=delay)

    @staticmethod
    def _describe(result: CallbackResult) -> str:
        return result.error or f"HTTP {result.status_code}"

    @staticmethod
    def _complete(db: Session, txn_id: str) -> None:
        db.execute(
            update(RiskTransaction)
            .where(RiskTransaction.transaction_id == txn_id, RiskTransaction.status == "PROCESSING")
            .values(status="COMPLETED", updated_at=utcnow())
        )

    @staticmethod
    def _fail(db: Session, txn_id: str, err: str, record_retry_row: bool) -> None:
        db.execute(
            update(RiskTransaction)
            .where(RiskTransaction.transaction_id == txn_id, RiskTransaction.status == "PROCESSING")
            .values(status="FAILED", updated_at=utcnow())
        )
        if record_retry_row:
            db.add(CallbackRetry(transaction_id=txn_id, retry_count=0, next_retry_at=utcnow(), last_error=err, status="EXHAUSTED"))
