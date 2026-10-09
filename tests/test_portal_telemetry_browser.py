"""Exercise the deferred portal script after the document has loaded."""
import os
from pathlib import Path

import pytest


@pytest.mark.skipif(os.getenv("COMPUTEMESH_BROWSER_E2E") != "1", reason="browser E2E opt-in")
def test_late_portal_script_initializes_telemetry():
    from playwright.sync_api import sync_playwright

    core = Path(__file__).resolve().parents[1] / "portal" / "portal-core.js"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/api/**", lambda route: route.fulfill(json={}))
        page.route("**/api/v1/mesh/stats", lambda route: route.fulfill(json={
            "active_gpus": 1, "total_vram_gb": 16, "total_nodes": 1,
            "total_tflops": 0, "measurement_status": "live",
        }))
        page.route("https://portal.test/", lambda route: route.fulfill(
            content_type="text/html", body='''<html><body>
            <div id="portal-ticker-vram">-- GB</div>
            <div id="portal-ticker-gpus">--</div>
            <div id="portal-ticker-nodes">--</div>
            <div id="portal-ticker-tflops">--</div>
            </body></html>'''))
        page.goto("https://portal.test/")
        page.evaluate("localStorage.setItem('cm_portal_lang', 'de')")
        page.add_script_tag(content=core.read_text(encoding="utf-8"))
        page.wait_for_function("document.getElementById('portal-ticker-vram').textContent === '16,0 GB'")
        assert page.locator("#portal-ticker-gpus").inner_text() == "1 GPU online"
        assert page.locator("#portal-ticker-nodes").inner_text() == "1 Node aktiv"
        page.evaluate("switchLanguage('en')")
        page.evaluate("fetchMeshTelemetry()")
        assert page.locator("#portal-ticker-vram").inner_text() == "16.0 GB"
        assert page.locator("#portal-ticker-nodes").inner_text() == "1 Node active"
        assert errors == []
        browser.close()
