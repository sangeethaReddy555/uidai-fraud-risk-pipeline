"""Drives the real React UI (via Playwright) against a running backend + Vite dev server,
asserts the key behaviours and saves screenshots to docs/screenshots.

Prereqs: backend on :8000 (dev mode, embedded worker, ALLOW_*_CALLBACKS=true), `npm run dev` on :5173,
         `pip install playwright && python -m playwright install chromium`.
Run:     python scripts/ui_smoke_and_screenshots.py
"""
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

from playwright.sync_api import expect, sync_playwright

OUT = pathlib.Path(__file__).resolve().parent.parent / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
API, UI = "http://localhost:8000", "http://localhost:5173"


def call(path, method="GET", token=None, body=None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def seed():
    toks = call("/api/v1/dev/tokens")[1]["tokens"]
    ta = toks["partner_a"]["token"]
    sink = f"{API}/api/v1/dev/callback-sink"
    ids = []
    for i, aad in enumerate(["234567890123", "345678901234", "456789012345", "567890123456", "678901234567"]):
        s, d = call("/api/v1/risk-score/initiate", "POST", ta, {"partner_id": "PARTNER001", "aadhaar_number": aad, "device_data": {"device_id": f"DEVICE{i+10}"}, "callback_url": sink})
        assert s == 202, d
        ids.append(d["transaction_id"])
    s, d = call("/api/v1/risk-score/initiate", "POST", ta, {"partner_id": "PARTNER001", "aadhaar_number": "789012345678", "device_data": {"device_id": "DEVICE99"}, "callback_url": f"{API}/no/such/path"})
    assert s == 202  # partner answers 404 -> permanent failure -> FAILED
    s, d = call("/api/v1/risk-score/initiate", "POST", toks["partner_b"]["token"], {"partner_id": "PARTNER002", "aadhaar_number": "890123456789", "device_data": {"device_id": "DEVB1"}, "callback_url": sink})
    assert s == 202
    time.sleep(2.5)
    return ids[0]


def main():
    a_txn = seed()
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1366, "height": 820})
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(UI)

        # Dashboard: real numbers from /stats
        expect(pg.get_by_text("Total transactions")).to_be_visible()
        pg.wait_for_selector(".stat strong")
        time.sleep(1)
        assert int(pg.locator(".stat.blue strong").inner_text()) >= 6
        assert int(pg.locator(".stat.green strong").inner_text()) >= 5
        assert int(pg.locator(".stat.red strong").inner_text()) >= 1
        pg.screenshot(path=OUT / "01_dashboard.png")

        # Initiate: client-side validation, then a real submit (dev sink answers 503 twice first)
        pg.get_by_role("button", name="Initiate Risk Score").first.click()
        pg.get_by_label("Aadhaar number (TEST data)").fill("1234")
        pg.get_by_role("button", name="Submit", exact=True).click()
        expect(pg.get_by_text("Must be exactly 12 digits")).to_be_visible()
        pg.screenshot(path=OUT / "02_initiate_validation_error.png")
        pg.get_by_label("Aadhaar number (TEST data)").fill("901234567890")
        pg.get_by_label("Simulate partner outage").check()
        pg.get_by_role("button", name="Submit", exact=True).click()
        expect(pg.get_by_text("HTTP 202")).to_be_visible()
        txn = re.search(r"TXN[0-9A-F]{20}", pg.locator(".alert.success").inner_text()).group(0)
        # the input field holds what the user typed; the API response / alert must never echo it
        assert "901234567890" not in pg.locator(".api-response").inner_text() + pg.locator(".alert").inner_text()
        pg.screenshot(path=OUT / "03_initiate_success.png")

        # Audit via link: in-progress during backoff, then COMPLETED
        pg.get_by_role("button", name="Audit it").click()
        expect(pg.locator(".details")).to_be_visible()
        first_status = pg.locator(".details .badge").inner_text()
        pg.screenshot(path=OUT / "04_audit_in_progress.png")
        deadline, status = time.time() + 20, ""
        while time.time() < deadline:
            pg.get_by_role("button", name="Fetch audit").click()
            time.sleep(0.8)
            status = pg.locator(".details .badge").inner_text()
            if status == "COMPLETED":
                break
        assert status == "COMPLETED", status
        print("audit status progression:", first_status, "->", status)
        pg.screenshot(path=OUT / "05_audit_completed.png")

        # History: masked Aadhaar, status filter, search
        pg.get_by_role("button", name="Transaction History").click()
        expect(pg.locator("tbody tr").first).to_be_visible()
        assert pg.locator("td code", has_text="XXXX-XXXX-").count() >= 5
        pg.get_by_label("Filter by status").select_option("FAILED")
        time.sleep(1)
        assert pg.locator(".badge.failed").count() >= 1
        pg.screenshot(path=OUT / "06_history_filter_failed.png")
        pg.get_by_label("Filter by status").select_option("")
        pg.get_by_placeholder("Search by transaction ID").fill(a_txn)
        pg.get_by_role("button", name="Search").click()
        time.sleep(1)
        assert pg.locator("tbody tr").count() == 1
        pg.screenshot(path=OUT / "07_history_search.png")

        # IDOR: Partner B audits Partner A's transaction -> 404, nothing leaked
        pg.get_by_label("Acting as (dev token)").select_option("partner_b")
        pg.get_by_role("button", name="Audit Details").click()
        pg.get_by_placeholder("Transaction ID").fill(a_txn)
        pg.get_by_role("button", name="Fetch audit").click()
        expect(pg.locator(".alert.error")).to_contain_text("404")
        assert "PARTNER001" not in pg.locator(".content").inner_text()
        pg.screenshot(path=OUT / "08_audit_idor_blocked_404.png")

        # Unauthorized user: 403 on initiate
        pg.get_by_label("Acting as (dev token)").select_option("unauthorized")
        pg.get_by_role("button", name="Initiate Risk Score").first.click()
        pg.get_by_role("button", name="Submit", exact=True).click()
        expect(pg.locator(".alert.error").first).to_contain_text("403")
        pg.screenshot(path=OUT / "09_unauthorized_403.png")
        b.close()

        # Mobile layout
        b = p.chromium.launch()
        m = b.new_page(viewport={"width": 390, "height": 800}, device_scale_factor=2)
        m.goto(UI)
        m.wait_for_selector(".stat strong")
        time.sleep(1)
        m.screenshot(path=OUT / "10_mobile_dashboard.png")
        m.get_by_label("Toggle menu").click()
        time.sleep(0.5)
        m.screenshot(path=OUT / "11_mobile_menu.png")
        b.close()
    assert not errors, errors
    print("UI smoke test PASSED; screenshots in", OUT)


if __name__ == "__main__":
    sys.exit(main())
