"""Application settings, loaded from environment variables / .env.

No secrets are hardcoded for production use. The defaults below are DEVELOPMENT
ONLY and the app refuses to start outside ENVIRONMENT=development with them.
"""
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-secret-NOT-for-production-use-0123456789"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"  # development | production
    database_url: str = "sqlite:///./risk_pipeline.db"
    db_pool_size: int = 10
    db_max_overflow: int = 10
    auto_create_tables: bool = True  # convenience for dev; use Alembic in production

    # --- JWT -----------------------------------------------------------
    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "uidai-sandbox-dev"
    jwt_audience: str = "risk-score-api"
    enable_dev_tokens: bool = True  # honoured only when environment == development

    # --- HTTP ----------------------------------------------------------
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    rate_limit_initiate_per_minute: int = 30
    rate_limit_read_per_minute: int = 120

    # --- Kafka ---------------------------------------------------------
    kafka_mode: str = "mock"  # mock | real
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_topic: str = "Risk_Evaluation_Requested"
    kafka_dlq_topic: str = "Risk_Evaluation_Requested.DLQ"
    kafka_group_id: str = "risk-score-workers"
    embedded_worker: bool = True  # run consumer + retry loops inside the API process

    # --- Callback delivery ---------------------------------------------
    callback_timeout_seconds: float = 5.0
    callback_max_retries: int = 5
    callback_backoff_base_seconds: float = 2.0
    callback_backoff_max_seconds: float = 300.0
    callback_backoff_jitter: float = 0.1  # +0..10% random jitter
    retry_poll_interval_seconds: float = 1.0
    retry_batch_size: int = 50
    retry_concurrency: int = 4
    stalled_processing_seconds: int = 120

    # --- SSRF controls -------------------------------------------------
    allow_http_callbacks: bool = False  # dev only
    allow_private_callbacks: bool = False  # dev only (needed for the local callback sink)
    ssrf_dns_check: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @model_validator(mode="after")
    def _guard_production(self):
        if not self.is_development:
            if self.jwt_secret == DEV_JWT_SECRET or len(self.jwt_secret) < 32:
                raise ValueError("JWT_SECRET must be set to a strong value (>=32 chars) outside development")
            if self.allow_http_callbacks or self.allow_private_callbacks:
                raise ValueError("Insecure callback options are only allowed in development")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
