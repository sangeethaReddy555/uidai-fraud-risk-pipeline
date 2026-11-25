import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.utils.tokens import make_token

AADHAAR = "123456789012"  # FAKE test number
BODY = {
    "partner_id": "PARTNER001",
    "aadhaar_number": AADHAAR,
    "device_data": {"device_id": "DEVICE001"},
    "callback_url": "https://example.com/callback",
}


@pytest.fixture
def settings(tmp_path):
    return Settings(
        database_url=f"sqlite:///{tmp_path}/test.db",
        kafka_mode="mock",
        embedded_worker=False,
        ssrf_dns_check=False,  # no real DNS in tests; resolver-based checks are unit-tested separately
        rate_limit_initiate_per_minute=1000,
        rate_limit_read_per_minute=1000,
        callback_backoff_jitter=0.0,
        callback_backoff_base_seconds=2.0,
        callback_max_retries=3,
    )


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def tokens(settings):
    w = "write:risk_test read:risk_test"
    return {
        "a": make_token(settings, partner_id="PARTNER001", scope=w),
        "b": make_token(settings, partner_id="PARTNER002", scope=w),
        "readonly": make_token(settings, partner_id="PARTNER001", scope="read:risk_test"),
        "none": make_token(settings, partner_id="PARTNER999", scope="read:public"),
    }


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def create_txn(client, tokens):
    def _create(who="a", partner="PARTNER001", **overrides):
        body = {**BODY, "partner_id": partner, **overrides}
        r = client.post("/api/v1/risk-score/initiate", json=body, headers=auth(tokens[who]))
        assert r.status_code == 202, r.text
        return r.json()["transaction_id"]

    return _create
