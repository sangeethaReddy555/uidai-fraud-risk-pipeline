"""Micro-benchmark of the audit query on a local SQLite file with N rows.

This is NOT a PostgreSQL benchmark and says nothing about your production latency. It only shows the
indexed lookup stays flat as the table grows and compares it to the same query without the indexes.
For a real figure, run EXPLAIN (ANALYZE, BUFFERS) and a load test against your target PostgreSQL.
Usage: python scripts/bench_audit_query.py [rows]
"""
import os, random, statistics, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import sqlalchemy as sa
from sqlalchemy import text

from app.config import Settings
from app.database import Base, make_engine
import app.models  # noqa: F401
from app.services.transactions import AUDIT_SQL

N = int(sys.argv[1]) if len(sys.argv) > 1 else 200_000
path = os.path.join(tempfile.mkdtemp(), "bench.db")
engine = make_engine(Settings(database_url=f"sqlite:///{path}"))
Base.metadata.create_all(engine)
rows = [
    {"t": f"TXN{i:020X}", "p": f"PARTNER{i % 500:03d}", "k": f"k{i}"} for i in range(N)
]
with engine.begin() as c:
    c.execute(text("INSERT INTO risk_transactions (transaction_id, partner_id, masked_aadhaar_number, device_data, callback_url, status, idempotency_key, created_at, updated_at) "
                   "VALUES (:t, :p, 'XXXX-XXXX-1234', '{}', 'https://example.com/cb', 'PENDING', :k, '2026-01-01 00:00:00', '2026-01-01 00:00:00')"), rows)
    c.execute(text("ANALYZE"))


def bench(label):
    sample = random.sample(rows, 2000)
    times = []
    with engine.connect() as c:
        for r in sample:
            t0 = time.perf_counter()
            c.execute(AUDIT_SQL, {"transaction_id": r["t"], "partner_id": r["p"]}).first()
            times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    print(f"{label:<28} p50={statistics.median(times):7.3f} ms  p95={times[int(.95*len(times))]:7.3f} ms  p99={times[int(.99*len(times))]:7.3f} ms  max={times[-1]:7.3f} ms")


print(f"rows={N:,} (SQLite, local file, warm cache, 2000 random lookups)")
bench("with indexes")
with engine.begin() as c:
    for name in ("ux_risk_transactions_transaction_id", "ix_risk_transactions_partner_txn", "ix_risk_transactions_partner_id", "ix_risk_transactions_partner_created"):
        c.execute(text(f"DROP INDEX {name}"))
    N_SMALL = 20_000
bench("WITHOUT indexes (full scan)") if N <= 50_000 else print("(skipping no-index run: full scans on this many rows are slow; pass a smaller row count)")
