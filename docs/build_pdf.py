"""Builds Backend_YourName_Assignment.pdf from the real artefacts in this repo (test results, screenshots)."""
import collections, pathlib, re
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Polygon
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle)
from PIL import Image as PILImage

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "Backend_YourName_Assignment.pdf"
SHOTS = ROOT / "docs" / "screenshots"
NAVY, TEAL, GREY = colors.HexColor("#0b1f3a"), colors.HexColor("#0ea5a4"), colors.HexColor("#6b7a90")

ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Heading1"], textColor=NAVY, fontSize=17, spaceBefore=6, spaceAfter=8)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], textColor=NAVY, fontSize=12.5, spaceBefore=10, spaceAfter=4)
B = ParagraphStyle("B", parent=ss["BodyText"], fontSize=9.5, leading=13.5, spaceAfter=5)
SM = ParagraphStyle("SM", parent=B, fontSize=8, leading=10.5, textColor=GREY)
CODE = ParagraphStyle("CODE", fontName="Courier", fontSize=7.4, leading=9.2, backColor=colors.HexColor("#f3f6fb"), borderPadding=5, spaceAfter=8)
CELL = ParagraphStyle("CELL", parent=B, fontSize=8.3, leading=10.5, spaceAfter=0)


def P(t, s=B): return Paragraph(t, s)
def code(t): return Preformatted(t.strip("\n"), CODE)
def bullets(items): return [P("• " + i) for i in items]


def table(rows, widths, header=True):
    HC = ParagraphStyle("hc", parent=CELL, textColor=colors.white, fontName="Helvetica-Bold")
    data = [[Paragraph(str(c), HC if (header and i == 0) else CELL) for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    st = [("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#cfd8e6")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
    if header:
        st += [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
    t.setStyle(TableStyle(st))
    return t


def shot(name, caption, width=165 * mm):
    w, h = PILImage.open(SHOTS / name).size
    return KeepTogether([Image(str(SHOTS / name), width=width, height=width * h / w), P(caption, SM), Spacer(1, 4)])


def box(d, x, y, w, h, label, fill, sub=None):
    d.add(Rect(x, y, w, h, rx=5, ry=5, fillColor=fill, strokeColor=NAVY, strokeWidth=.8))
    d.add(String(x + w / 2, y + h / 2 + (3 if sub else -3), label, textAnchor="middle", fontName="Helvetica-Bold", fontSize=8, fillColor=colors.white if fill in (NAVY, TEAL) else NAVY))
    if sub:
        d.add(String(x + w / 2, y + h / 2 - 8, sub, textAnchor="middle", fontName="Helvetica", fontSize=6.3, fillColor=colors.white if fill in (NAVY, TEAL) else GREY))


def arrow(d, x1, y1, x2, y2, label=None, lx=0, ly=3):
    d.add(Line(x1, y1, x2, y2, strokeColor=GREY, strokeWidth=1))
    import math
    a = math.atan2(y2 - y1, x2 - x1)
    d.add(Polygon([x2, y2, x2 - 6 * math.cos(a - .4), y2 - 6 * math.sin(a - .4), x2 - 6 * math.cos(a + .4), y2 - 6 * math.sin(a + .4)], fillColor=GREY, strokeColor=GREY))
    if label:
        d.add(String((x1 + x2) / 2 + lx, (y1 + y2) / 2 + ly, label, textAnchor="middle", fontName="Helvetica", fontSize=6.3, fillColor=GREY))


def diagram():
    d = Drawing(480, 290)
    L = colors.HexColor("#e8f0fb")
    box(d, 5, 225, 90, 40, "React UI", TEAL, "dashboard · initiate · audit")
    box(d, 150, 225, 130, 40, "FastAPI", NAVY, "JWT · scopes · rate limit · SSRF")
    box(d, 345, 225, 130, 40, "Database", L, "risk_transactions · callback_retries")
    box(d, 150, 140, 130, 40, "Kafka topic", L, "Risk_Evaluation_Requested (mock | real)")
    box(d, 5, 60, 140, 50, "Consumer loop", L, "manual ack · DLQ for poison messages")
    box(d, 172, 60, 138, 50, "RiskWorker", NAVY, "atomic claim · score 1-100")
    box(d, 345, 105, 130, 40, "Retry loop", L, "due rows · exp. backoff + jitter")
    box(d, 345, 5, 130, 40, "Partner callback_url", colors.HexColor("#fde9c9"), "HTTPS POST, no redirects")
    arrow(d, 95, 245, 150, 245, "REST/JSON", 0, 4); arrow(d, 280, 245, 345, 245, "SQL", 0, 4)
    arrow(d, 215, 225, 215, 180, "publish event", 34, 0)
    arrow(d, 175, 140, 90, 110, "poll", -14, 2); arrow(d, 145, 85, 172, 85, None)
    arrow(d, 310, 95, 345, 120, "503 / timeout", 0, -14)
    arrow(d, 310, 70, 345, 30, "POST", -6, 4)
    arrow(d, 410, 105, 410, 45, "retry POST", 28, 0)
    arrow(d, 410, 145, 410, 225, "claims due rows", 38, 0)
    d.add(String(5, 278, "Worker and retry loop read/write the database with atomic conditional UPDATEs; the audit API reads it with one indexed query.", fontName="Helvetica-Oblique", fontSize=6.6, fillColor=GREY))
    return d


# ---- real test results
counts = collections.OrderedDict()
for line in (ROOT / "docs" / "pytest_results.txt").read_text().splitlines():
    m = re.match(r"tests/(\w+)\.py::(\S+)", line)
    if m:
        counts.setdefault(m.group(1), []).append(m.group(2).split("[")[0])
total = sum(len(v) for v in counts.values())

S = []
S += [Spacer(1, 40 * mm), P("UIDAI Sandbox", ParagraphStyle("t0", parent=H1, fontSize=14, textColor=TEAL)),
      P("Fraud Risk Scoring Pipeline", ParagraphStyle("t1", parent=H1, fontSize=30, leading=34)),
      P("Backend Technical Assignment – Implementation Report", ParagraphStyle("t2", parent=B, fontSize=13, textColor=GREY)), Spacer(1, 16 * mm),
      table([["Candidate", "YourName  (replace before submitting)"], ["GitHub repository", "&lt;paste your public repository URL here&gt;  – the repo is prepared (README, .gitignore, .env.example, tests) but has not been pushed by the assistant"],
             ["Stack", "Python FastAPI · SQLAlchemy · Alembic · PyJWT · Kafka (mock + adapter) · React (Vite)"],
             ["Data", "Fake/test Aadhaar numbers only. No connection to UIDAI or real Aadhaar data."]], [40 * mm, 125 * mm], header=False),
      Spacer(1, 10 * mm),
      P(f"<b>Verification summary:</b> {total} automated tests pass; a live end-to-end run and a Playwright UI run against the real API also passed. "
        "Real-Kafka adapters, docker-compose and PostgreSQL were <b>not</b> exercised (no Docker/broker available) and no 10 ms guarantee is claimed.", B), PageBreak()]

S += [P("1. Project overview", H1),
      P("The system accepts risk-evaluation requests from partners, stores them with the Aadhaar number masked, emits a <i>Risk_Evaluation_Requested</i> event, scores the transaction asynchronously, calls the partner back with retries, and exposes a partner-scoped audit API. A React dashboard drives all of it through the real API."),
      P("2. Architecture", H1), diagram(),
      P("The consumer never waits on retries: a failed first callback becomes a <i>callback_retries</i> row and the consumer immediately acknowledges the event and moves on. A separate loop delivers due retries.", SM),
      P("3. Technology stack", H1),
      table([["Layer", "Choice", "Notes"],
             ["API", "FastAPI, Pydantic v2", "Swagger/ReDoc generated; sanitized 422 handler"],
             ["Auth", "PyJWT (HS256), HTTP Bearer", "pinned algorithm, required claims, scopes"],
             ["DB", "SQLAlchemy 2, Alembic; SQLite (tested) / PostgreSQL (portable, untested)", "JSON→JSONB on PG; pooled connections"],
             ["Messaging", "In-memory mock broker (tested); kafka-python adapters (untested)", "manual ack, DLQ topic"],
             ["Worker", "Threads inside API (dev) or <i>python -m app.workers.main</i>", "atomic DB claims, no in-process locks"],
             ["Frontend", "React 18 + Vite, plain CSS", "responsive, light/dark aware"],
             ["Tests", "pytest, FastAPI TestClient, Playwright (UI smoke)", f"{total} backend tests"]], [25 * mm, 80 * mm, 60 * mm]), PageBreak()]

S += [P("4. Part 1 – Ingestion API", H1),
      P("<b>POST /api/v1/risk-score/initiate</b> (scope <i>write:risk_test</i>) – returns <b>202</b> with the transaction ID and status PENDING."),
      *bullets(["Validation: partner_id/device_id pattern, Aadhaar exactly 12 digits (<i>SecretStr</i>), unknown fields forbidden, callback URL length/scheme.",
                "Auth: missing/invalid/expired/forged/<i>alg=none</i> token → 401; valid token without scope → 403; body <i>partner_id</i> ≠ token's → 403.",
                "Masking: <i>123456789012</i> → <i>XXXX-XXXX-9012</i> before the INSERT; the raw number is never persisted, published, logged or returned (a test scans every column, the Kafka event, the response and the logs).",
                "Transaction ID = <i>TXN</i> + 20 hex chars (UUID4); unique constraint; status PENDING; optional <i>Idempotency-Key</i> header de-duplicates client retries.",
                "Event <i>Risk_Evaluation_Requested</i> published with transaction_id/partner_id only (no PII). If publishing fails the row is marked FAILED and 503 is returned.",
                "SSRF: https only, no credentials, no localhost/metadata names, no private/loopback/link-local/CGNAT/IPv4-mapped IPs, no decimal/hex/octal IP forms, DNS answers inspected, redirects never followed; re-checked when the callback is sent."]),
      code('''POST /api/v1/risk-score/initiate   Authorization: Bearer <token>
{"partner_id":"PARTNER001","aadhaar_number":"123456789012",
 "device_data":{"device_id":"DEVICE001"},"callback_url":"https://example.com/callback"}

HTTP/1.1 202 Accepted
{"transaction_id":"TXND5B3C12F78984CFB8954","status":"PENDING","message":"Risk evaluation requested"}'''),
      P("5. Part 2 – Background worker", H1),
      *bullets(["<b>Idempotency / concurrency:</b> one atomic statement <i>UPDATE … SET status='PROCESSING' WHERE transaction_id=? AND status='PENDING'</i>. Of 12 simultaneous duplicate events exactly one wins (test), others are acknowledged as duplicates; no callback is sent twice and COMPLETED is written only from PROCESSING.",
                "<b>Score:</b> uniform random integer 1–100, stored once and reused across retries.",
                "<b>Callback outcomes:</b> 2xx success; 503, 5xx, 408/425/429, timeouts → temporary; other 4xx, unexpected 3xx, blocked URL → permanent (FAILED).",
                "<b>Non-blocking retries:</b> temporary failure → <i>callback_retries</i> row with <i>next_retry_at</i>; delay = min(max, base·2<super>n</super>)·(1+jitter) (2 s, 4 s, 8 s … in the test config). A separate loop claims due rows atomically (PENDING→IN_PROGRESS) and retries; after the configured maximum the row is EXHAUSTED and the transaction FAILED.",
                "<b>Kafka acknowledgement:</b> offset committed only after the event is handled or parked in the DLQ; if even the DLQ publish fails the offset stays uncommitted for redelivery. Unexpected handler errors do not kill the consumer.",
                "<b>Crash recovery:</b> transactions stuck in PROCESSING without a retry row are re-queued by a sweeper.",
                "<b>Logging:</b> IDs and outcomes only, plus a redaction filter for 12-digit numbers and JWTs."]),
      P("<b>Observed in a live run</b> (dev sink answering 503 twice, backoff base 1 s): HTTP 503 → retry 1 s later → 503 → retry 2 s later → 200; the transaction went PROCESSING → COMPLETED with the same risk score and exactly one DONE retry row.", B), PageBreak()]

S += [P("6. Part 3 – Audit API and query optimization", H1),
      P("<b>GET /api/v1/risk-score/audit/{transaction_id}</b> (scope <i>read:risk_test</i>). The partner comes from the validated token, never from the request. Ownership is part of the query itself, so another partner's row is never loaded; both “not yours” and “does not exist” return the identical 404 (no existence oracle)."),
      code('''SELECT transaction_id, partner_id, status, risk_score, created_at, updated_at
FROM risk_transactions
WHERE transaction_id = :transaction_id
  AND partner_id = :partner_id
LIMIT 1;'''),
      P("<b>Why this should be fast (not a guarantee):</b> the composite index <i>(partner_id, transaction_id)</i> matches both equality predicates, so lookup is one B-tree descent; the unique <i>transaction_id</i> index also exists; only six narrow columns are read (no JSON/URL), <i>LIMIT 1</i> stops early; bound parameters allow plan caching; a connection pool (<i>pool_size</i>, <i>max_overflow</i>, <i>pool_pre_ping</i>) removes per-request connection setup."),
      P("<b>Measured locally (SQLite, warm cache, 200,000 rows, 2,000 random lookups):</b> p50 ≈ 0.03 ms, p99 ≈ 0.06 ms; without indexes (20,000 rows) p50 ≈ 0.5 ms and growing with table size. <b>This is not a PostgreSQL benchmark and does not prove a 10 ms target.</b> Verify with <i>EXPLAIN (ANALYZE, BUFFERS)</i> and a load test on the real database.", B),
      P("7. Database schema and indexing", H1),
      table([["Table", "Columns", "Constraints / indexes"],
             ["risk_transactions", "id (PK), transaction_id, partner_id, masked_aadhaar_number, device_data (JSON/JSONB), callback_url, risk_score, status, idempotency_key, created_at, updated_at",
              "UNIQUE(transaction_id); UNIQUE(idempotency_key); IX(partner_id); IX(partner_id, transaction_id); IX(partner_id, created_at); IX(status); CHECK status ∈ {PENDING, PROCESSING, COMPLETED, FAILED}; CHECK risk_score 1..100; CHECK masked format"],
             ["callback_retries", "id (PK), transaction_id (FK), retry_count, next_retry_at, last_error, status, created_at",
              "UNIQUE(transaction_id) FK ON DELETE CASCADE; IX(status, next_retry_at) for the “what is due” poll; CHECK retry_count ≥ 0; CHECK status ∈ {PENDING, IN_PROGRESS, DONE, EXHAUSTED}"]],
            [28 * mm, 70 * mm, 67 * mm]),
      P("Note: <i>(partner_id, transaction_id)</i> already serves partner_id-only lookups as a left prefix, so the single-column partner_id index is redundant; it is kept because the assignment lists it and is documented in the model for removal on write-heavy systems. Migration <i>0001</i> was verified to create the same indexes as the ORM models.", SM),
      P("8. Security implementation", H1),
      table([["Control", "Implementation"],
             ["Authentication", "Bearer JWT; signature, exp, iat, iss, aud, sub required; algorithm pinned (alg=none / forged tokens rejected)"],
             ["Authorization", "Scopes write:risk_test / read:risk_test; partner_id claim bound to every query (IDOR prevention)"],
             ["PII", "Aadhaar masked pre-persist; SecretStr; no PII in events, callbacks, logs, 422 bodies; regex redaction filter"],
             ["SSRF", "URL validation at submit and send time, DNS answer checks, no redirects, port allow-list"],
             ["Errors", "Generic 500 body; validation errors never echo input; consistent JSON errors"],
             ["Secrets", "Environment variables; production refuses the default dev secret and dev-only flags"],
             ["Transport/API", "CORS allow-list, rate limiting (429 + Retry-After), nosniff / no-store headers"],
             ["Dev tokens", "Partner A, Partner B, Unauthorized user via /api/v1/dev/tokens or scripts/generate_dev_tokens.py. <b>Not production credentials</b>; endpoint exists only when ENVIRONMENT=development"]],
            [32 * mm, 133 * mm]), PageBreak()]

S += [P("9. API request and response examples", H1),
      table([["Scenario", "Result"],
             ["Initiate, valid (Partner A)", "202 {transaction_id, status: PENDING}"],
             ["Initiate, no token", "401 {\"detail\":\"Missing bearer token\"}"],
             ["Initiate, unauthorized-user token", "403 {\"detail\":\"Missing required scope: write:risk_test\"}"],
             ["Initiate, Aadhaar “1234”", "422 {\"detail\":\"Validation failed\",\"errors\":[{\"field\":\"aadhaar_number\",\"message\":\"Value error, must be exactly 12 digits\"}]} (value not echoed)"],
             ["Initiate, callback http://169.254.169.254/…", "422 callback_url rejected"],
             ["Audit own transaction", "200 {transaction_id, partner_id, status: COMPLETED, risk_score: 62, created_at, updated_at}"],
             ["Audit Partner A's transaction as Partner B", "404 {\"detail\":\"Transaction not found\"} – identical to a non-existent ID"],
             ["Audit malformed ID", "422 (path pattern)"]], [60 * mm, 105 * mm]),
      P("Callback body sent to the partner:", B),
      code('{"transaction_id":"TXN…","risk_score":75,"status":"COMPLETED","partner_id":"PARTNER001","masked_aadhaar_number":"XXXX-XXXX-9012","device_id":"DEVICE001"}'),
      P("10. Testing results", H1),
      P(f"<b>{total} passed, 0 failed</b> (<i>cd backend &amp;&amp; pytest</i>, repeated 5× with no flakiness, including the 12-thread duplicate-event race). Full list: docs/pytest_results.txt.")]
names = {"test_part1_ingestion": "Part 1 – ingestion & security", "test_part2_worker": "Part 2 – worker, idempotency, retries", "test_part3_audit": "Part 3 – audit, IDOR, indexes, scoping", "test_url_validation": "SSRF URL validation"}
S += [table([["Test module", "Tests", "Covers"]] + [[names.get(k, k), str(len(v)), "; ".join(sorted({x.replace("test_", "").replace("_", " ") for x in v}))[:230] + "…"] for k, v in counts.items()], [48 * mm, 14 * mm, 103 * mm]),
      P("Also verified outside pytest: live uvicorn + curl run (retry/backoff, 401/403/404, DB contains only the masked number, server log contains no raw Aadhaar); Playwright UI run (validation, submit, audit progression PROCESSING→COMPLETED, filters, search, IDOR 404, 403, mobile layout). "
        "<b>Not verified:</b> real Kafka broker, PostgreSQL, docker-compose, any load/latency target on PostgreSQL.", B), PageBreak()]

S += [P("11. UI screenshots (real app, real API)", H1)]
for f, c in [("01_dashboard.png", "Dashboard – live counters and risk-score distribution from GET /stats"),
             ("03_initiate_success.png", "Initiate Risk Score – 202 response; Aadhaar not echoed"),
             ("02_initiate_validation_error.png", "Client-side form validation"),
             ("05_audit_completed.png", "Audit details after the retried callback succeeded"),
             ("06_history_filter_failed.png", "Transaction history – masked Aadhaar, status filter"),
             ("08_audit_idor_blocked_404.png", "Partner B requesting Partner A's transaction → 404, nothing leaked"),
             ("09_unauthorized_403.png", "Unauthorized user → 403 shown in the UI")]:
    S.append(shot(f, c, 150 * mm))
S += [KeepTogether([Table([[Image(str(SHOTS / "10_mobile_dashboard.png"), width=55 * mm, height=55 * mm * 1600 / 780), Image(str(SHOTS / "11_mobile_menu.png"), width=55 * mm, height=55 * mm * 1600 / 780)]]), P("Responsive layout (390 px wide): dashboard and navigation drawer", SM)]),
      PageBreak(), P("12. GitHub repository", H1),
      P("Public repository URL: <b>&lt;paste your URL here&gt;</b>. The project directory is ready to push (<i>git init &amp;&amp; git add . &amp;&amp; git commit</i>): .gitignore excludes .env, databases and node_modules; .env.example holds development-only values; no real Aadhaar numbers or secrets are included."),
      P("13. Instructions to run", H1),
      code('''# Backend
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt && cp .env.example .env
uvicorn app.main:create_app --factory --reload --port 8000     # docs at /docs

# Frontend (second terminal)
cd frontend && npm install && npm run dev                      # http://localhost:5173

# Tests
cd backend && pytest -q

# Optional: PostgreSQL + real Kafka (untested)   docker compose up -d postgres kafka
# then set DATABASE_URL, KAFKA_MODE=real, EMBEDDED_WORKER=false and run: alembic upgrade head;
# uvicorn ... ; python -m app.workers.main'''),
      P("Known limitations: insert + publish are not atomic (use a transactional outbox in production); in-memory rate limiter is per-process; DNS-rebinding between URL check and connect is only mitigated, not eliminated; delivery is at-least-once so partners should dedupe on transaction_id.", B)]


def footer(c, d):
    c.saveState(); c.setFont("Helvetica", 7.5); c.setFillColor(GREY)
    c.drawString(18 * mm, 10 * mm, "UIDAI Sandbox – Fraud Risk Scoring Pipeline · test data only"); c.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {d.page}"); c.restoreState()


SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
                  title="Backend Assignment – Fraud Risk Scoring Pipeline", author="YourName").build(S, onFirstPage=footer, onLaterPages=footer)
print("wrote", OUT)
