import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.utils.time import as_utc

ID_PATTERN = r"^[A-Za-z0-9_-]{3,64}$"
TXN_PATTERN = r"^[A-Za-z0-9_-]{6,40}$"
Status = Literal["PENDING", "PROCESSING", "COMPLETED", "FAILED"]


class DeviceData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: str = Field(pattern=ID_PATTERN, examples=["DEVICE001"])
    os: str | None = Field(default=None, max_length=32)
    app_version: str | None = Field(default=None, max_length=32)


class InitiateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "partner_id": "PARTNER001",
                "aadhaar_number": "123456789012",
                "device_data": {"device_id": "DEVICE001"},
                "callback_url": "https://example.com/callback",
            }
        },
    )
    partner_id: str = Field(pattern=ID_PATTERN)
    # SecretStr: never printed in repr/logs. TEST DATA ONLY - 12 digits.
    aadhaar_number: SecretStr = Field(description="12-digit Aadhaar number (fake/test data only)")
    device_data: DeviceData
    callback_url: str = Field(min_length=8, max_length=2048)

    @field_validator("aadhaar_number")
    @classmethod
    def _aadhaar_12_digits(cls, v: SecretStr) -> SecretStr:
        if not re.fullmatch(r"\d{12}", v.get_secret_value()):
            raise ValueError("must be exactly 12 digits")
        return v


class InitiateResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"transaction_id": "TXN3F9A1C77D2E04B5A91C8", "status": "PENDING",
                                       "message": "Risk evaluation requested"}}
    )
    transaction_id: str
    status: Status
    message: str = "Risk evaluation requested"


class AuditResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "transaction_id": "TXN3F9A1C77D2E04B5A91C8",
                "partner_id": "PARTNER001",
                "status": "COMPLETED",
                "risk_score": 75,
                "created_at": "2026-11-23T10:00:00Z",
                "updated_at": "2026-11-23T10:00:02Z",
            }
        }
    )
    transaction_id: str
    partner_id: str
    status: Status
    risk_score: int | None
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def _tz(cls, v):
        return as_utc(v)


class TransactionItem(AuditResponse):
    masked_aadhaar_number: str


class TransactionList(BaseModel):
    items: list[TransactionItem]
    total: int
    limit: int
    offset: int


class StatsResponse(BaseModel):
    total: int
    pending: int  # PENDING + PROCESSING
    completed: int
    failed: int
    average_risk_score: float | None
    risk_buckets: dict[str, int]  # low 1-33, medium 34-66, high 67-100


class ErrorResponse(BaseModel):
    detail: str
