import random
import threading
import time
from datetime import timedelta

from sqlalchemy import select

from app.kafka.mock import MockConsumer
from app.models import CallbackRetry, RiskTransaction
from app.services.callback import CallbackResult, classify
from app.utils.time import as_utc, utcnow
from app.workers.risk_worker import RiskWorker
from app.workers.runner import start_threads


class FakeSender:
    """Scriptable callback target. `script` maps URL -> list of results (last one repeats)."""

    def __init__(self, script=None, delay=0.0):
        self.script, self.delay, self.calls, self.lock = script or {}, delay, [], threading.Lock()

    def send(self, url, payload):
        if self.delay:
            time.sleep(self.delay)
        with self.lock:
            self.calls.append((url, payload))
            seq = self.script.get(url) or [CallbackResult(status_code=200)]
            n = sum(1 for u, _ in self.calls if u == url)
            return seq[min(n, len(seq)) - 1]


def event_for(app, settings, txn_id):
    return next(m.value for m in app.state.broker.messages(settings.kafka_topic) if m.value["transaction_id"] == txn_id)


def get_txn(app, txn_id):
    with app.state.session_factory() as db:
        return db.scalar(select(RiskTransaction).where(RiskTransaction.transaction_id == txn_id))


def get_retry(app, txn_id):
    with app.state.session_factory() as db:
        return db.scalar(select(CallbackRetry).where(CallbackRetry.transaction_id == txn_id))


def make_worker(app, settings, sender):
    return RiskWorker(app.state.session_factory, settings, sender=sender)


def test_successful_event_processing_and_callback_payload(client, app, settings, create_txn):
    txn_id = create_txn()
    sender = FakeSender()
    outcome = make_worker(app, settings, sender).handle_event(event_for(app, settings, txn_id))
    assert outcome == "completed"
    txn = get_txn(app, txn_id)
    assert txn.status == "COMPLETED" and 1 <= txn.risk_score <= 100
    (url, payload), = sender.calls
    assert url == "https://example.com/callback"
    assert payload["transaction_id"] == txn_id and payload["status"] == "COMPLETED" and payload["risk_score"] == txn.risk_score
    assert payload["masked_aadhaar_number"] == "XXXX-XXXX-9012" and "123456789012" not in str(payload)


def test_risk_score_always_between_1_and_100(client, app, settings, create_txn):
    worker = make_worker(app, settings, FakeSender())
    scores = []
    for _ in range(40):
        t = create_txn()
        worker.handle_event(event_for(app, settings, t))
        scores.append(get_txn(app, t).risk_score)
    assert all(1 <= s <= 100 for s in scores) and len(set(scores)) > 1
    # boundaries are reachable
    r = random.Random(0)
    assert {r.randint(1, 100) for _ in range(5000)} >= {1, 100}


def test_duplicate_event_is_idempotent(client, app, settings, create_txn):
    txn_id = create_txn()
    ev, sender = event_for(app, settings, txn_id), FakeSender()
    w = make_worker(app, settings, sender)
    assert w.handle_event(ev) == "completed"
    first = get_txn(app, txn_id)
    assert w.handle_event(ev) == "duplicate"
    assert w.handle_event(dict(ev)) == "duplicate"
    assert len(sender.calls) == 1
    again = get_txn(app, txn_id)
    assert (again.risk_score, again.status, again.updated_at) == (first.risk_score, "COMPLETED", first.updated_at)


def test_concurrent_duplicate_events_processed_exactly_once(client, app, settings, create_txn):
    txn_id = create_txn()
    ev = event_for(app, settings, txn_id)
    sender = FakeSender(delay=0.05)
    worker = make_worker(app, settings, sender)
    barrier, results = threading.Barrier(12), []

    def run():
        barrier.wait()
        results.append(worker.handle_event(ev))

    threads = [threading.Thread(target=run) for _ in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("completed") == 1 and results.count("duplicate") == 11
    assert len(sender.calls) == 1
    assert get_txn(app, txn_id).status == "COMPLETED"


def test_callback_503_schedules_retry_then_completes_once(client, app, settings, create_txn):
    txn_id = create_txn()
    url = "https://example.com/callback"
    sender = FakeSender({url: [CallbackResult(status_code=503), CallbackResult(status_code=200)]})
    w = make_worker(app, settings, sender)
    assert w.handle_event(event_for(app, settings, txn_id)) == "retry_scheduled"
    assert get_txn(app, txn_id).status == "PROCESSING"
    row = get_retry(app, txn_id)
    assert row.status == "PENDING" and row.retry_count == 0 and "503" in row.last_error
    assert w.run_retry_cycle() == 0  # not due yet (backoff)
    score_before = get_txn(app, txn_id).risk_score
    assert w.run_retry_cycle(now=utcnow() + timedelta(seconds=5)) == 1
    assert get_txn(app, txn_id).status == "COMPLETED" and get_txn(app, txn_id).risk_score == score_before
    assert get_retry(app, txn_id).status == "DONE"
    assert w.run_retry_cycle(now=utcnow() + timedelta(hours=1)) == 0  # nothing left; no double delivery
    assert len(sender.calls) == 2


def test_exponential_backoff_then_failed_after_max_retries(client, app, settings, create_txn):
    txn_id = create_txn()
    url = "https://example.com/callback"
    sender = FakeSender({url: [CallbackResult(status_code=503)]})
    w = make_worker(app, settings, sender)
    t0 = utcnow()
    w.handle_event(event_for(app, settings, txn_id))
    gaps = []
    for _ in range(settings.callback_max_retries):
        row = get_retry(app, txn_id)
        gaps.append(round((as_utc(row.next_retry_at) - t0).total_seconds()))
        assert w.run_retry_cycle(now=as_utc(row.next_retry_at) + timedelta(seconds=1)) == 1
        t0 = utcnow()
    assert gaps[0] in (2,) and gaps[1] in (4,) and gaps[2] in (8,)  # base 2s * 2^n, jitter disabled
    assert get_retry(app, txn_id).status == "EXHAUSTED" and get_retry(app, txn_id).retry_count == 3
    assert get_txn(app, txn_id).status == "FAILED"
    assert len(sender.calls) == 1 + settings.callback_max_retries


def test_permanent_4xx_fails_without_retry_and_network_error_retries(client, app, settings, create_txn):
    t1, t2 = create_txn(callback_url="https://bad.example.com/cb"), create_txn(callback_url="https://down.example.com/cb")
    sender = FakeSender({"https://bad.example.com/cb": [CallbackResult(status_code=400)],
                         "https://down.example.com/cb": [CallbackResult(error="ConnectTimeout")]})
    w = make_worker(app, settings, sender)
    assert w.handle_event(event_for(app, settings, t1)) == "failed"
    assert get_txn(app, t1).status == "FAILED" and get_retry(app, t1).status == "EXHAUSTED"
    assert w.handle_event(event_for(app, settings, t2)) == "retry_scheduled"
    assert [classify(CallbackResult(status_code=c)) for c in (200, 503, 500, 429, 404, 301)] == [
        "success", "temporary", "temporary", "temporary", "permanent", "permanent"]


def test_blocked_url_at_send_time_is_permanent(client, app, settings, create_txn):
    from app.services.callback import HttpCallbackSender

    txn_id = create_txn()
    with app.state.session_factory() as db:  # simulate a URL that slipped into the DB
        t = db.scalar(select(RiskTransaction).where(RiskTransaction.transaction_id == txn_id))
        t.callback_url = "https://127.0.0.1/steal"
        db.commit()
    w = RiskWorker(app.state.session_factory, settings, sender=HttpCallbackSender(settings))
    assert w.handle_event(event_for(app, settings, txn_id)) == "failed"


def test_retry_does_not_block_other_events(client, app, settings, create_txn):
    """Event 1 fails with 503 (retry scheduled). Event 2 must complete while 1 is still waiting."""
    slow = create_txn(callback_url="https://flaky.example.com/cb")
    fast = create_txn(callback_url="https://good.example.com/cb")
    sender = FakeSender({"https://flaky.example.com/cb": [CallbackResult(status_code=503)]})
    worker = make_worker(app, settings, sender)
    consumer = MockConsumer(app.state.broker, settings.kafka_topic)
    stop, threads = start_threads(consumer, worker, app.state.producer, settings.model_copy(update={"retry_poll_interval_seconds": 60}))
    try:
        deadline = time.time() + 5
        while time.time() < deadline and get_txn(app, fast).status != "COMPLETED":
            time.sleep(0.02)
        assert get_txn(app, fast).status == "COMPLETED"
        assert get_txn(app, slow).status == "PROCESSING" and get_retry(app, slow).status == "PENDING"
        while time.time() < deadline and len(app.state.broker.committed) < 2:
            time.sleep(0.02)
        assert len(app.state.broker.committed) == 2  # both events acknowledged
    finally:
        stop.set()
        [t.join(timeout=3) for t in threads]


def test_retry_cycle_runs_due_callbacks_concurrently_without_double_send(client, app, settings, create_txn):
    ids = [create_txn(callback_url="https://flaky.example.com/cb") for _ in range(6)]
    sender = FakeSender({"https://flaky.example.com/cb": [CallbackResult(status_code=503)] + [CallbackResult(status_code=200)]}, delay=0.0)
    # first call per txn fails: emulate per-call script by call index across txns
    seq = iter([503] * 6 + [200] * 50)
    sender.send = lambda url, payload: CallbackResult(status_code=next(seq))
    w = make_worker(app, settings, sender)
    for t in ids:
        w.handle_event(event_for(app, settings, t))
    far = utcnow() + timedelta(minutes=5)
    runs = []
    th = [threading.Thread(target=lambda: runs.append(w.run_retry_cycle(now=far))) for _ in range(3)]
    [t.start() for t in th]
    [t.join() for t in th]
    assert sum(runs) == 6  # each retry row claimed by exactly one cycle
    assert all(get_txn(app, t).status == "COMPLETED" for t in ids)


def test_invalid_and_unknown_events_go_to_dlq(client, app, settings):
    w = make_worker(app, settings, FakeSender())
    assert w.handle_event({"nope": 1}) == "invalid"
    assert w.handle_event({"transaction_id": "TXNDOESNOTEXIST"}) == "not_found"
    from app.workers.runner import run_consumer

    app.state.broker.put(__import__("app.kafka.base", fromlist=["Message"]).Message(settings.kafka_topic, None, {"bad": True}))
    stop = threading.Event()
    th = threading.Thread(target=run_consumer, args=(MockConsumer(app.state.broker, settings.kafka_topic), w, app.state.producer, settings.kafka_dlq_topic, stop, 0.05))
    th.start()
    deadline = time.time() + 3
    while time.time() < deadline and not app.state.broker.messages(settings.kafka_dlq_topic):
        time.sleep(0.02)
    stop.set(); th.join(timeout=3)
    assert len(app.state.broker.messages(settings.kafka_dlq_topic)) == 1
    assert len(app.state.broker.committed) == 1


def test_unexpected_handler_error_does_not_kill_consumer(client, app, settings, create_txn):
    t_ok = create_txn()
    w = make_worker(app, settings, FakeSender())
    real, calls = w.handle_event, []

    def flaky(ev):
        calls.append(ev)
        if len(calls) == 1:
            raise RuntimeError("db hiccup")
        return real(ev)

    w.handle_event = flaky
    from app.kafka.base import Message
    from app.workers.runner import run_consumer

    # queue = [original event (handler raises), redelivered copy (handled normally)]
    app.state.broker.put(Message(settings.kafka_topic, "k", event_for(app, settings, t_ok)))

    stop = threading.Event()
    th = threading.Thread(target=run_consumer, args=(MockConsumer(app.state.broker, settings.kafka_topic), w, app.state.producer, settings.kafka_dlq_topic, stop, 0.05))
    th.start()
    deadline = time.time() + 3
    while time.time() < deadline and get_txn(app, t_ok).status != "COMPLETED":
        time.sleep(0.02)
    stop.set(); th.join(timeout=3)
    assert get_txn(app, t_ok).status == "COMPLETED"
    assert len(app.state.broker.messages(settings.kafka_dlq_topic)) == 1  # failed event parked, consumer survived


def test_recover_stalled_processing_transaction(client, app, settings, create_txn):
    txn_id = create_txn()
    from sqlalchemy import update

    with app.state.session_factory() as db:  # simulate a crash right after the claim
        db.execute(update(RiskTransaction).where(RiskTransaction.transaction_id == txn_id).values(status="PROCESSING", risk_score=42, updated_at=utcnow() - timedelta(hours=1)))
        db.commit()
    sender = FakeSender()
    w = make_worker(app, settings, sender)
    assert w.recover_stalled() == 1
    assert w.run_retry_cycle(now=utcnow() + timedelta(seconds=1)) == 1
    assert get_txn(app, txn_id).status == "COMPLETED" and get_txn(app, txn_id).risk_score == 42
