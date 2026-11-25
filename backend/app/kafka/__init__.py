from app.config import Settings
from app.kafka.base import Consumer, Message, Producer
from app.kafka.mock import InMemoryBroker, MockConsumer, MockProducer


def build_producer(settings: Settings, broker: InMemoryBroker | None) -> Producer:
    if settings.kafka_mode == "real":
        from app.kafka.real import KafkaProducerAdapter

        return KafkaProducerAdapter(settings.kafka_bootstrap_servers)
    return MockProducer(broker or InMemoryBroker())


def build_consumer(settings: Settings, broker: InMemoryBroker | None) -> Consumer:
    if settings.kafka_mode == "real":
        from app.kafka.real import KafkaConsumerAdapter

        return KafkaConsumerAdapter(settings.kafka_bootstrap_servers, settings.kafka_topic, settings.kafka_group_id)
    if broker is None:
        raise RuntimeError("mock Kafka consumer needs the in-process broker")
    return MockConsumer(broker, settings.kafka_topic)


__all__ = ["Consumer", "Message", "Producer", "InMemoryBroker", "build_producer", "build_consumer"]
