"""In-memory Kafka stand-in for local development and tests (single process).

Semantics mirrored: topics are queues, publish is durable for the process lifetime,
consumers must explicitly commit; uncommitted messages are tracked in `in_flight`.
It does NOT model partitions, consumer groups or redelivery after a crash.
"""
import queue
import threading
from collections import defaultdict
from typing import Any

from app.kafka.base import Message


class InMemoryBroker:
    def __init__(self) -> None:
        self._queues: dict[str, queue.Queue] = defaultdict(queue.Queue)
        self.published: list[Message] = []  # audit trail for tests
        self.committed: list[Message] = []
        self._lock = threading.Lock()

    def put(self, msg: Message) -> None:
        with self._lock:
            self.published.append(msg)
        self._queues[msg.topic].put(msg)

    def get(self, topic: str, timeout: float) -> Message | None:
        try:
            return self._queues[topic].get(timeout=timeout)
        except queue.Empty:
            return None

    def messages(self, topic: str) -> list[Message]:
        with self._lock:
            return [m for m in self.published if m.topic == topic]


class MockProducer:
    def __init__(self, broker: InMemoryBroker):
        self.broker = broker

    def publish(self, topic: str, key: str | None, value: dict[str, Any]) -> None:
        self.broker.put(Message(topic=topic, key=key, value=value))


class MockConsumer:
    def __init__(self, broker: InMemoryBroker, topic: str):
        self.broker, self.topic = broker, topic

    def poll(self, timeout: float) -> Message | None:
        return self.broker.get(self.topic, timeout)

    def commit(self, message: Message) -> None:
        self.broker.committed.append(message)

    def close(self) -> None:
        pass
