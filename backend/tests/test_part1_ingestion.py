import logging

import jwt
from sqlalchemy import select

from app.models import RiskTransaction
from app.utils.logging import redact
from app.utils.masking import mask_aadhaar
from tests.conftest import AADHAAR, BODY, auth

URL = "/api/v1/risk-score/initiate"


def test_valid_request_returns_202_and_saves_pending(client, app, tokens):
    r = client.post(URL, json=BODY, headers=auth(tokens["a"]))
    assert r.status_code == 202
    data = r.json()
    assert data["status"] == "PENDING" and data["transaction_id"].startswith("TXN")
    with app.state.session_factory() as db:
        txn = db.scalar(select(RiskTransaction).where(RiskTransaction.transaction_id == data["transaction_id"]))
    assert txn.status == "PENDING" and txn.risk_score is None and txn.partner_id == "PARTNER001"


def test_aadhaar_is_masked_in_db_and_never_returned(client, app, tokens):
    r = client.post(URL, json=BODY, headers=auth(tokens["a"]))
    assert AADHAAR not in r.text
    with app.state.session_factory() as db:
        txn = db.scalar(select(RiskTransaction))
        assert txn.masked_aadhaar_number == "XXXX-XXXX-9012"
        # raw number must not appear in ANY column
        assert AADHAAR not in repr([getattr(txn, c.name) for c in txn.__table__.columns])
    assert mask_aadhaar("123456789012") == "XXXX-XXXX-9012"


def test_kafka_event_published_without_pii(client, app, tokens, settings):
    r = client.post(URL, json=BODY, headers=auth(tokens["a"]))
    msgs = app.state.broker.messages(settings.kafka_topic)
    assert len(msgs) == 1
    ev = msgs[0].value
    assert ev["event_type"] == "Risk_Evaluation_Requested"
    assert ev["transaction_id"] == r.json()["transaction_id"]
    assert AADHAAR not in str(ev)


def test_missing_token_401(client):
    r = client.post(URL, json=BODY)
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


def test_invalid_token_401(client, settings):
    assert client.post(URL, json=BODY, headers=auth("not.a.jwt")).status_code == 401
    forged = jwt.encode({"sub": "x", "partner_id": "PARTNER001", "scope": "write:risk_test"}, "wrong-secret-wrong-secret-wrong-secret", algorithm="HS256")
    assert client.post(URL, json=BODY, headers=auth(forged)).status_code == 401


def test_alg_none_token_rejected(client):
    unsigned = jwt.encode({"sub": "x", "partner_id": "PARTNER001", "scope": "write:risk_test"}, key=None, algorithm="none")
    assert client.post(URL, json=BODY, headers=auth(unsigned)).status_code == 401


def test_expired_token_401(client, settings):
    from app.utils.tokens import make_token

    t = make_token(settings, partner_id="PARTNER001", scope="write:risk_test", ttl=-10)
    assert client.post(URL, json=BODY, headers=auth(t)).status_code == 401


def test_missing_write_scope_403(client, tokens):
    assert client.post(URL, json=BODY, headers=auth(tokens["readonly"])).status_code == 403
    assert client.post(URL, json=BODY, headers=auth(tokens["none"])).status_code == 403


def test_partner_id_must_match_token(client, tokens):
    r = client.post(URL, json={**BODY, "partner_id": "PARTNER002"}, headers=auth(tokens["a"]))
    assert r.status_code == 403


def test_invalid_requests_422_and_never_echo_aadhaar(client, tokens):
    bad = [
        {**BODY, "aadhaar_number": "12345"},
        {**BODY, "aadhaar_number": "12345678901A"},
        {**BODY, "partner_id": "bad id!"},
        {**BODY, "device_data": {}},
        {**BODY, "callback_url": "not a url"},
        {**{k: v for k, v in BODY.items() if k != "callback_url"}},
        {**BODY, "unexpected": 1},
    ]
    for payload in bad:
        r = client.post(URL, json=payload, headers=auth(tokens["a"]))
        assert r.status_code == 422, payload
        assert '"input"' not in r.text and "ctx" not in r.text
        assert "12345678901A" not in r.text and "12345678" not in r.text
    r = client.post(URL, json={**BODY, "aadhaar_number": "999988887777x"}, headers=auth(tokens["a"]))
    assert "9999" not in r.text


def test_ssrf_callback_urls_rejected(client, tokens):
    for url in ["http://example.com/cb", "https://127.0.0.1/cb", "https://localhost/cb", "https://169.254.169.254/latest/meta-data",
                "https://10.0.0.5/cb", "https://[::1]/cb", "https://2130706433/cb", "https://user:pw@example.com/cb", "file:///etc/passwd"]:
        r = client.post(URL, json={**BODY, "callback_url": url}, headers=auth(tokens["a"]))
        assert r.status_code == 422, url


def test_idempotency_key_returns_same_transaction(client, app, tokens, settings):
    h = {**auth(tokens["a"]), "Idempotency-Key": "client-key-0001"}
    r1 = client.post(URL, json=BODY, headers=h)
    r2 = client.post(URL, json=BODY, headers=h)
    assert r1.json()["transaction_id"] == r2.json()["transaction_id"]
    assert len(app.state.broker.messages(settings.kafka_topic)) == 1


def test_publish_failure_marks_failed_and_returns_503(client, app, tokens):
    class Broken:
        def publish(self, *a, **k):
            raise RuntimeError("broker down")

    app.state.producer = Broken()
    r = client.post(URL, json=BODY, headers=auth(tokens["a"]))
    assert r.status_code == 503
    with app.state.session_factory() as db:
        assert db.scalar(select(RiskTransaction.status)) == "FAILED"


def test_rate_limit_429(settings, tokens):
    from fastapi.testclient import TestClient

    from app.main import create_app

    s = settings.model_copy(update={"rate_limit_initiate_per_minute": 2})
    with TestClient(create_app(s)) as c:
        codes = [c.post(URL, json=BODY, headers=auth(tokens["a"])).status_code for _ in range(4)]
    assert codes[:2] == [202, 202] and codes[2:] == [429, 429]


def test_unhandled_error_is_generic(app, tokens, settings):
    from fastapi.testclient import TestClient

    class Boom:
        def publish(self, *a, **k):
            raise RuntimeError("secret detail")

    @app.get("/boom")
    def boom():
        raise RuntimeError(f"leak {AADHAAR}")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/boom")
    assert r.status_code == 500 and r.json() == {"detail": "Internal server error"}


def test_logs_never_contain_aadhaar_or_token(client, tokens, caplog):
    with caplog.at_level(logging.DEBUG):
        client.post(URL, json=BODY, headers=auth(tokens["a"]))
    assert AADHAAR not in caplog.text and tokens["a"] not in caplog.text


def test_redaction_filter():
    assert AADHAAR not in redact(f"aadhaar={AADHAAR} and 1234 5678 9012")
    assert "eyJ" not in redact("Bearer eyJhbGciOi.eyJzdWIi.sig")
