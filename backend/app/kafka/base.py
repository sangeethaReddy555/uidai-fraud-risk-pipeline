from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Message:
    topic: str
    key: str | None
    value: dict[str, Any]
    raw: Any = field(default=None, repr=False)  # adapter-specific handle (real Kafka record)


class Producer(Protocol):
    def publish(self, topic: str, key: str | None, value: dict[str, Any]) -> None: ...


class Consumer(Protocol):
    def poll(self, timeout: float) -> Message | None: ...
    def commit(self, message: Message) -> None: ...
    def close(self) -> None: ...
