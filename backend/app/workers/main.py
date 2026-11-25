"""Standalone worker process (use with KAFKA_MODE=real):  python -m app.workers.main"""
import signal

from app.config import get_settings
from app.database import make_engine, make_session_factory
from app.kafka import build_consumer, build_producer
from app.utils.logging import configure_logging
from app.workers.risk_worker import RiskWorker
from app.workers.runner import start_threads


def main() -> None:
    configure_logging()
    settings = get_settings()
    if settings.kafka_mode != "real":
        raise SystemExit("Standalone worker needs KAFKA_MODE=real (mock Kafka only lives inside the API process).")
    sf = make_session_factory(make_engine(settings))
    worker = RiskWorker(sf, settings)
    stop, threads = start_threads(build_consumer(settings, None), worker, build_producer(settings, None), settings)
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    try:
        threads[0].join()
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
