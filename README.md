# UIDAI Sandbox – Fraud Risk Scoring Pipeline

FastAPI + React reference implementation of an asynchronous fraud-risk-scoring pipeline:
ingestion API → Kafka event → idempotent worker → partner callback (with non-blocking exponential-backoff retries) → secured audit API.

> **Test data only.** This project uses fake Aadhaar numbers and never connects to UIDAI or any real Aadhaar system.
> Tokens/secrets in this repo are **development values, not production credentials**.

## What was verified (and what was not)

| Area | Status |
|---|---|
| Backend API, worker, retries, idempotency, auth, IDOR, SSRF, masking | **60 automated pytest tests pass** (`cd backend && pytest`) |
| Alembic migration produces the same tables/indexes as the ORM models | Verified (SQLite) |
| Live end-to-end run (server + embedded mock-Kafka worker + dev callback sink with simulated 503s) | Verified manually with curl |
| React UI against the live API (forms, validation, filters, search, audit, 401/403/404 handling, mobile layout) | Verified with Playwright: `scripts/ui_smoke_and_screenshots.py`; screenshots in `docs/screenshots/` |
| **Mock Kafka mode** | Fully tested |
| **Real Kafka adapters** (`backend/app/kafka/real.py`) and `docker-compose.yml` | **Not tested** – no Docker/broker was available when this was built |
| **PostgreSQL** | **Not tested** – tests/benchmarks ran on SQLite. Models use portable types (JSONB variant on PG), but validate before relying on it |
| 10 ms audit-query target | **Not proven.** See [Performance](#performance-and-the-10-ms-target) |

## Architecture

```
React UI ──HTTPS/JSON──▶ FastAPI ──▶ risk_transactions (PENDING)
                           │  └─ publish Risk_Evaluation_Requested ─▶ Kafka (or in-memory mock)
                           │                                              │
                           │                         consumer loop (manual ack, DLQ on poison messages)
                           │                                              ▼
                           │              RiskWorker.handle_event: atomic claim PENDING→PROCESSING, score 1–100
                           │                                              │ POST callback_url (SSRF-checked, no redirects)
                           │                    success ─▶ COMPLETED      │
                           │        503 / timeout / 408 / 425 / 429 ─▶ callback_retries row (next_retry_at, backoff) ─▶ consumer moves on
                           │        other 4xx / blocked URL / retries exhausted ─▶ FAILED
                           └─ GET audit (ownership enforced in SQL) ◀── retry loop delivers due callbacks, claims rows atomically
```

## Quick start (no Docker, no Kafka)

```bash
# 1. Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                       # development values only
uvicorn app.main:create_app --factory --reload --port 8000
# Swagger UI: http://localhost:8000/docs      ReDoc: /redoc

# 2. Frontend (new terminal)
cd frontend
npm install
npm run dev                                                # http://localhost:5173  (proxies /api to :8000)

# 3. Tests
cd backend && pytest -q
```

`.env.example` enables the local demo callback sink (`ALLOW_HTTP_CALLBACKS`, `ALLOW_PRIVATE_CALLBACKS`). These flags
**only work with `ENVIRONMENT=development`**; the app refuses to start with them in any other environment.

In the UI pick **Partner A / Partner B / Unauthorized user** in the sidebar (tokens come from `GET /api/v1/dev/tokens`),
open *Initiate Risk Score*, tick *Simulate partner outage* to watch two 503s get retried with backoff before the
transaction reaches `COMPLETED`.

### Migrations
`AUTO_CREATE_TABLES=true` (default) creates tables on start for convenience. For real deployments:
```bash
cd backend && alembic upgrade head
```

### PostgreSQL / real Kafka (untested – see table above)
```bash
docker compose up -d postgres kafka
# .env: DATABASE_URL=postgresql+psycopg2://risk:risk_dev_only@localhost:5432/risk  KAFKA_MODE=real  EMBEDDED_WORKER=false
alembic upgrade head
uvicorn app.main:create_app --factory --port 8000            # API
python -m app.workers.main                                    # worker (separate process)
```

## API

| Method & path | Auth / scope | Success | Errors |
|---|---|---|---|
| `POST /api/v1/risk-score/initiate` | Bearer, `write:risk_test`, `partner_id` in body must equal token's | **202** `{transaction_id, status:"PENDING"}` | 401, 403, 422, 429, 503 |
| `GET /api/v1/risk-score/audit/{transaction_id}` | Bearer, `read:risk_test` | 200 audit record | 401, 403, **404 (also when owned by another partner)**, 422, 429 |
| `GET /api/v1/risk-score/transactions?status=&search=&limit=&offset=` | Bearer, `read:risk_test` | 200 (caller's rows only) | 401, 403, 422 |
| `GET /api/v1/risk-score/stats` | Bearer, `read:risk_test` | 200 counters | 401, 403 |
| `GET /api/v1/dev/tokens`, `POST /api/v1/dev/callback-sink` | dev only (404 otherwise) | | |

Optional header `Idempotency-Key` on initiate: repeating it returns the same transaction and publishes no second event.
Full OpenAPI: `/docs`, exported to [`docs/openapi.json`](docs/openapi.json).

### Sample requests (real output from a run)
```bash
TOKEN=$(curl -s localhost:8000/api/v1/dev/tokens | python -c "import sys,json;print(json.load(sys.stdin)['tokens']['partner_a']['token'])")

curl -i -X POST localhost:8000/api/v1/risk-score/initiate -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{
  "partner_id":"PARTNER001","aadhaar_number":"123456789012",
  "device_data":{"device_id":"DEVICE001"},"callback_url":"https://example.com/callback"}'
# HTTP/1.1 202 Accepted
# {"transaction_id":"TXND5B3C12F78984CFB8954","status":"PENDING","message":"Risk evaluation requested"}

curl localhost:8000/api/v1/risk-score/audit/TXND5B3C12F78984CFB8954 -H "Authorization: Bearer $TOKEN"
# {"transaction_id":"TXND5B3C12F78984CFB8954","partner_id":"PARTNER001","status":"COMPLETED","risk_score":62,
#  "created_at":"2026-11-23T11:53:29.869435Z","updated_at":"2026-11-23T11:53:34.339612Z"}

# Partner B asking for Partner A's transaction           -> 404 {"detail":"Transaction not found"}   (same as a non-existent ID)
# Unauthorized-user token on /initiate                    -> 403 {"detail":"Missing required scope: write:risk_test"}
# No token                                                -> 401 {"detail":"Missing bearer token"}
```
Callback payload delivered to the partner:
```json
{"transaction_id":"TXN…","risk_score":75,"status":"COMPLETED","partner_id":"PARTNER001","masked_aadhaar_number":"XXXX-XXXX-9012","device_id":"DEVICE001"}
```

## Design notes

**Security.** HS256 JWT validated with pinned algorithm, required `exp/iat/sub/iss/aud` (blocks `alg=none`, forged and expired tokens → 401);
missing scope or partner mismatch → 403. Aadhaar is validated (12 digits), masked to `XXXX-XXXX-1234` before the DB write, held as `SecretStr`,
never put in the Kafka event, callback-failure logs or API responses; Pydantic's 422 body (which normally echoes `input`) is replaced by a sanitized one;
a log filter additionally scrubs 12-digit numbers and JWTs. Callback URLs are SSRF-checked at submit **and again at send time**
(https only, no credentials, no localhost/metadata hosts, no private/loopback/link-local/CGNAT/IPv4-mapped IPs, no decimal/hex/octal IP tricks, DNS answers checked, redirects not followed, unusual ports rejected).
Known limit: DNS can change between check and connect (rebinding) – use an egress proxy in production. CORS is an explicit allow-list; rate limiting is per client IP (in-memory – use Redis behind multiple instances).
Secrets come from env vars; production start-up fails with the default dev secret.

**Idempotency & concurrency.** The claim `UPDATE … SET status='PROCESSING' WHERE transaction_id=? AND status='PENDING'` is atomic, so of N concurrent duplicate events exactly one affects a row (tested with 12 threads → 1 callback). `COMPLETED` is written only from `PROCESSING`. It works across processes because it relies on the database, not on locks in memory.

**Retries without blocking.** A failed first attempt writes a `callback_retries` row and returns, so the consumer immediately commits and takes the next message (tested: a flaky partner does not delay another partner's event). A separate loop picks due rows, claims each atomically, and applies `delay = min(max, base·2^n)·(1+jitter)`. Exhausted or permanent failures set the transaction to `FAILED`. A sweeper re-queues transactions stuck in `PROCESSING` after a crash.

**Status model.** `PENDING` → `PROCESSING` (scored, callback not yet delivered) → `COMPLETED` | `FAILED`. The dashboard's "Pending" counts `PENDING + PROCESSING`.

**Known gaps.** The transaction insert and the Kafka publish are not atomic (a crash between them leaves a `PENDING` row with no event); a transactional outbox would close this. If publishing fails the transaction is marked `FAILED` and the API returns 503. Delivery is at-least-once; partners should dedupe on `transaction_id`.

## Performance and the 10 ms target

The audit query is exactly the required statement (`services/transactions.py::AUDIT_SQL`). What helps it stay fast:
* **Composite index `(partner_id, transaction_id)`** – both predicates are equalities, so one B-tree descent finds the row; a test asserts the SQLite plan uses an index (no table scan). `transaction_id` is also uniquely indexed.
* **Narrow projection + `LIMIT 1`** – six columns, no `SELECT *`, no JSON/URL columns read, stops at first match.
* **Bound parameters** – no string building, and the driver/server can cache plans.
* **Connection pooling** – `pool_size`/`max_overflow` + `pool_pre_ping` avoid per-request connection setup (often several ms on PostgreSQL).
* Keep the working set in memory (`shared_buffers`) and the DB close to the API.

Local micro-benchmark (`backend/scripts/bench_audit_query.py`, **SQLite**, warm cache, 200k rows): indexed lookup p50 ≈ 0.03 ms, p99 ≈ 0.06 ms; the same lookup without indexes on 20k rows: p50 ≈ 0.5 ms and growing linearly with rows.
**This does not demonstrate a 10 ms guarantee on PostgreSQL.** Confirm with `EXPLAIN (ANALYZE, BUFFERS)` and a load test on your real database, network and data volume.

## Project layout
```
backend/app/{main,config,database}.py   models/ schemas/ routes/ services/ middleware/ workers/ kafka/ utils/
backend/tests/                          Part 1 / 2 / 3 + SSRF tests      backend/alembic/   migrations
backend/scripts/                        dev token generator, query benchmark
frontend/src/{pages,components,services,styles}   React (Vite)
docs/                                   screenshots, openapi.json, pytest_results.txt
docker-compose.yml  .gitignore  README.md
```
