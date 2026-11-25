"""Consumer loop, retry loop and thread orchestration."""
import logging
import threading
import time

from app.kafka.base import Consumer, Producer
from app.workers.risk_worker import RiskWorker

log = logging.getLogger("risk.runner")


def run_consumer(consumer: Consumer, worker: RiskWorker, dlq_producer: Producer, dlq_topic: str, stop: threading.Event, poll_timeout: float = 0.5) -> None:
    """Manual-ack loop. A message is committed only after it was handled, or parked in the DLQ.

    handle_event never waits on callback retries, so one slow/failing partner cannot stall the queue.
    """
    while not stop.is_set():
        msg = consumer.poll(poll_timeout)
        if msg is None:
            continue
        try:
            outcome = worker.handle_event(msg.value)
            if outcome in ("invalid", "not_found"):
                dlq_producer.publish(dlq_topic, msg.key, msg.value)
            consumer.commit(msg)
        except Exception:  # unexpected (DB down, bug ...)
            log.exception("unexpected error handling event")
            try:
                dlq_producer.publish(dlq_topic, msg.key, msg.value)
                consumer.commit(msg)
            except Exception:
                log.exception("DLQ publish failed; leaving offset uncommitted for redelivery")
                time.sleep(1)


def run_retry_loop(worker: RiskWorker, stop: threading.Event, interval: float) -> None:
    ticks = 0
    while not stop.is_set():
        try:
            worker.run_retry_cycle()
            ticks += 1
            if ticks % 30 == 0:
                worker.recover_stalled()
        except Exception:
            log.exception("retry cycle failed")
        stop.wait(interval)


def start_threads(consumer, worker, dlq_producer, settings) -> tuple[threading.Event, list[threading.Thread]]:
    stop = threading.Event()
    threads = [
        threading.Thread(target=run_consumer, args=(consumer, worker, dlq_producer, settings.kafka_dlq_topic, stop), name="risk-consumer", daemon=True),
        threading.Thread(target=run_retry_loop, args=(worker, stop, settings.retry_poll_interval_seconds), name="risk-retries", daemon=True),
    ]
    for t in threads:
        t.start()
    return stop, threads
