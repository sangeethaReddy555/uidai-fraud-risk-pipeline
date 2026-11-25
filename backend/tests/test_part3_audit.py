import re

from sqlalchemy import inspect, text

from app.services.transactions import AUDIT_SQL
from tests.conftest import auth

AUDIT = "/api/v1/risk-score/audit/"


def test_owner_can_audit_own_transaction(client, tokens, create_txn):
    txn_id = create_txn()
    r = client.get(AUDIT + txn_id, headers=auth(tokens["a"]))
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"transaction_id", "partner_id", "status", "risk_score", "created_at", "updated_at"}
    assert body["transaction_id"] == txn_id and body["partner_id"] == "PARTNER001" and body["status"] == "PENDING"
    assert "123456789012" not in r.text and "aadhaar" not in r.text.lower()


def test_partner_b_cannot_access_partner_a_transaction_idor(client, tokens, create_txn):
    txn_a = create_txn("a", "PARTNER001")
    forbidden = client.get(AUDIT + txn_a, headers=auth(tokens["b"]))
    missing = client.get(AUDIT + "TXNDOESNOTEXIST00001", headers=auth(tokens["b"]))
    assert forbidden.status_code == 404
    assert forbidden.json() == missing.json() == {"detail": "Transaction not found"}  # no existence oracle
    assert "PARTNER001" not in forbidden.text and txn_a not in forbidden.text
    # and the reverse direction
    txn_b = create_txn("b", "PARTNER002")
    assert client.get(AUDIT + txn_b, headers=auth(tokens["a"])).status_code == 404
    assert client.get(AUDIT + txn_b, headers=auth(tokens["b"])).status_code == 200


def test_invalid_transaction_ids(client, tokens):
    assert client.get(AUDIT + "TXN000000000000NOPE", headers=auth(tokens["a"])).status_code == 404
    for bad in ["x", "a" * 80, "TXN%27%20OR%201=1--", "TXN;DROP"]:
        assert client.get(AUDIT + bad, headers=auth(tokens["a"])).status_code in (404, 422), bad


def test_audit_requires_authentication_and_scope(client, tokens, create_txn):
    txn_id = create_txn()
    assert client.get(AUDIT + txn_id).status_code == 401
    assert client.get(AUDIT + txn_id, headers=auth("garbage")).status_code == 401
    assert client.get(AUDIT + txn_id, headers=auth(tokens["none"])).status_code == 403


def test_sql_injection_attempt_is_inert(client, tokens, create_txn):
    create_txn()
    r = client.get(AUDIT + "TXN%27%20OR%20%271%27%3D%271", headers=auth(tokens["b"]))
    assert r.status_code in (404, 422)


def test_audit_sql_is_exactly_the_required_query():
    normalized = re.sub(r"\s+", " ", str(AUDIT_SQL)).strip()
    assert normalized == (
        "SELECT transaction_id, partner_id, status, risk_score, created_at, updated_at FROM risk_transactions "
        "WHERE transaction_id = :transaction_id AND partner_id = :partner_id LIMIT 1"
    )


def test_required_indexes_exist(app):
    idx = {i["name"]: i for i in inspect(app.state.engine).get_indexes("risk_transactions")}
    assert idx["ux_risk_transactions_transaction_id"]["column_names"] == ["transaction_id"] and idx["ux_risk_transactions_transaction_id"]["unique"]
    assert idx["ix_risk_transactions_partner_id"]["column_names"] == ["partner_id"]
    assert idx["ix_risk_transactions_partner_txn"]["column_names"] == ["partner_id", "transaction_id"]
    retry_idx = {i["name"] for i in inspect(app.state.engine).get_indexes("callback_retries")}
    assert {"ix_callback_retries_due", "ux_callback_retries_transaction_id"} <= retry_idx


def test_audit_query_plan_uses_an_index_not_a_table_scan(app, create_txn):
    create_txn()
    with app.state.engine.connect() as conn:
        plan_rows = conn.execute(text("EXPLAIN QUERY PLAN " + str(AUDIT_SQL)), {"transaction_id": "TXNX", "partner_id": "PARTNER001"}).fetchall()
    plan = " | ".join(str(r[-1]) for r in plan_rows)
    assert "USING INDEX" in plan or "USING COVERING INDEX" in plan, plan
    assert "SCAN" not in plan.replace("SCAN ... USING", ""), plan
    assert any(n in plan for n in ("ix_risk_transactions_partner_txn", "ux_risk_transactions_transaction_id")), plan


def test_list_and_stats_are_partner_scoped_with_filters(client, app, settings, tokens, create_txn):
    ids_a = [create_txn("a", "PARTNER001") for _ in range(3)]
    create_txn("b", "PARTNER002")
    r = client.get("/api/v1/risk-score/transactions", headers=auth(tokens["a"]))
    assert r.json()["total"] == 3 and {i["transaction_id"] for i in r.json()["items"]} == set(ids_a)
    assert all(i["masked_aadhaar_number"] == "XXXX-XXXX-9012" for i in r.json()["items"])
    assert client.get("/api/v1/risk-score/transactions", params={"search": ids_a[0][:12]}, headers=auth(tokens["a"])).json()["total"] >= 1
    assert client.get("/api/v1/risk-score/transactions", params={"status": "FAILED"}, headers=auth(tokens["a"])).json()["total"] == 0
    assert client.get("/api/v1/risk-score/transactions", params={"status": "PENDING"}, headers=auth(tokens["a"])).json()["total"] == 3
    assert client.get("/api/v1/risk-score/transactions", params={"status": "BOGUS"}, headers=auth(tokens["a"])).status_code == 422
    s = client.get("/api/v1/risk-score/stats", headers=auth(tokens["a"])).json()
    assert (s["total"], s["pending"], s["completed"], s["failed"]) == (3, 3, 0, 0) and s["average_risk_score"] is None
    assert client.get("/api/v1/risk-score/transactions").status_code == 401


def test_dev_endpoints_present_in_development_only(settings, tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(settings)) as c:
        toks = c.get("/api/v1/dev/tokens").json()
        assert set(toks["tokens"]) == {"partner_a", "partner_b", "unauthorized"} and "not production" in toks["warning"].lower()
    prod = settings.model_copy(update={"environment": "production", "database_url": f"sqlite:///{tmp_path}/p.db"})
    with TestClient(create_app(prod)) as c:
        assert c.get("/api/v1/dev/tokens").status_code == 404


def test_production_rejects_default_secret():
    import pytest

    from app.config import Settings

    with pytest.raises(ValueError):
        Settings(environment="production")
