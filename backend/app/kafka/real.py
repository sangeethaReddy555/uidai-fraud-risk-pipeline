"""Adapters for a real Kafka cluster using kafka-python (imported lazily).

NOTE: these adapters were written to the kafka-python API but could NOT be exercised
against a live broker in the build environment (no Docker/Kafka available). Mock mode
is what the automated tests cover. Validate with docker-compose before relying on them.
"""
import json
from collections import deque
from typing import Any

from app.kafka.base import Message


class KafkaProducerAdapter:
    def __init__(self, bootstrap_servers: str):
        from kafka import KafkaProducer  # lazy: optional dependency

        self._producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers.split(","),
            value_serializer=lambda v: json.dumps(v).encode(),
            key_serializer=lambda k: k.encode() if k else None,
            acks="all",
            retries=5,
            enable_idempotence=False,
        )

    def publish(self, topic: str, key: str | None, value: dict[str, Any]) -> None:
        self._producer.send(topic, key=key, value=value).get(timeout=10)  # raises on failure


class KafkaConsumerAdapter:
    def __init__(self, bootstrap_servers: str, topic: str, group_id: str):
        from kafka import KafkaConsumer

        self._consumer = KafkaConsumer(
            topic,
            bootstrap_servers=bootstrap_servers.split(","),
            group_id=group_id,
            enable_auto_commit=False,  # manual ack after processing => at-least-once
            auto_offset_reset="earliest",
            value_deserializer=lambda b: json.loads(b.decode()),
            max_poll_records=1,
        )
        self._buffer: deque = deque()

    def poll(self, timeout: float) -> Message | None:
        if not self._buffer:
            for records in self._consumer.poll(timeout_ms=int(timeout * 1000), max_records=1).values():
                self._buffer.extend(records)
        if not self._buffer:
            return None
        rec = self._buffer.popleft()
        return Message(topic=rec.topic, key=rec.key.decode() if rec.key else None, value=rec.value, raw=rec)

    def commit(self, message: Message) -> None:
        self._consumer.commit()  # commits the current position (one record polled at a time)

    def close(self) -> None:
        self._consumer.close()
