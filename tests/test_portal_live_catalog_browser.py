"""Check that public portal cards reflect the gateway's current API state."""

import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest


PORTAL = Path(__file__).resolve().parents[1] / "portal"


@pytest.mark.skipif(os.getenv("COMPUTEMESH_BROWSER_E2E") != "1", reason="browser E2E opt-in")
def test_live_models_and_protected_fleet_are_presented_without_invented_offers():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        executable = os.getenv("COMPUTEMESH_BROWSER_EXECUTABLE") or None
        browser = playwright.chromium.launch(headless=True, executable_path=executable)
        page = browser.new_page(viewport={"width": 390, "height": 780}, locale="de-DE")
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def serve(route):
            path = urlsplit(route.request.url).path
            if path == "/v1/models":
                route.fulfill(json={"data": [
                    {"id": "qwen2.5:3b", "available": True, "capabilities": ["text"]},
                    {"id": "llava:latest", "available": True, "capabilities": ["text", "vision"]},
                ]})
                return
            if path == "/api/v1/mesh/fleet":
                route.fulfill(status=401, json={"error": "Owner authentication is required"})
                return
            if path == "/api/v1/mesh/stats":
                route.fulfill(json={"active_gpus": 1, "total_vram_gb": 16,
                                    "total_nodes": 1, "total_tflops": 0, "measurement_status": "live"})
                return
            if path == "/api/v1/pricing":
                route.fulfill(json={"tiers": {
                    "unavailable-model": {"prompt_usd_per_million": 0.1,
                                          "completion_usd_per_million": 0.2}
                }})
                return
            if path.startswith(("/api/", "/v1/")):
                route.fulfill(json={})
                return
            target = PORTAL / ("index.html" if path == "/" else path.lstrip("/"))
            if not target.suffix:
                target = target.with_suffix(".html")
            if target.is_file():
                route.fulfill(path=str(target))
            else:
                route.fulfill(status=404, body="Not found")

        page.route("https://portal.test/**", serve)
        try:
            page.goto("https://portal.test/models")
            page.wait_for_function("document.querySelectorAll('#models-cards-container .model-card').length === 2")
            names = page.locator("#models-cards-container .model-name").all_inner_texts()
            assert names == ["qwen2.5:3b", "llava:latest"]
            assert "Llama 3.3 70B" not in page.locator("#models-cards-container").inner_text()
            page.evaluate("switchLanguage('en')")
            assert "Available in gateway" in page.locator("#models-cards-container").inner_text()

            page.goto("https://portal.test/pricing")
            page.wait_for_function("document.querySelector('#live-pricing').textContent.includes('No matching')")
            assert "$" not in page.locator("#live-pricing").inner_text()
            assert "Ersparnis" not in page.locator("main").inner_text()

            page.route("https://portal.test/api/v1/pricing", lambda route: route.fulfill(json={"tiers": {
                "qwen2.5:3b": {"prompt_usd_per_million": 0.12,
                                "completion_usd_per_million": 0.34}
            }}))
            page.goto("https://portal.test/pricing")
            page.wait_for_function("document.querySelector('#live-pricing td')?.textContent === 'qwen2.5:3b'")
            assert page.locator("#live-pricing td").all_inner_texts() == [
                "qwen2.5:3b", "$0.1200", "$0.3400"
            ]

            page.goto("https://portal.test/docs")
            page.wait_for_function("document.querySelector('#playground-model').options.length === 2")
            assert page.locator("#playground-model option").evaluate_all(
                "options => options.map(option => option.value)"
            ) == ["qwen2.5:3b", "llava:latest"]

            page.goto("https://portal.test/playground")
            page.wait_for_function("document.querySelector('#playground-model-select').options.length === 2")
            assert page.locator("#playground-model-select option").evaluate_all(
                "options => options.map(option => option.value)"
            ) == ["qwen2.5:3b", "llava:latest"]
            assert page.locator("#playground-send-btn").is_enabled()

            page.goto("https://portal.test/marketplace")
            page.wait_for_function("document.querySelector('#marketplace-cards-container').textContent.includes('Sign in')")
            assert page.locator("#marketplace-cards-container .market-gpu-name").count() == 0
            assert page.locator("#marketplace-cards-container a[href='/fleet']").count() == 1
            page.evaluate("switchLanguage('de')")
            assert "Anmeldung" in page.locator("#marketplace-cards-container").inner_text()
            page.evaluate("""() => {
                window.__nodeMarkupRan = false;
                renderRealMarketplaceCards([{
                    node_id: '<img src=x onerror="window.__nodeMarkupRan=true">',
                    gpus: ['<svg onload="window.__nodeMarkupRan=true">'],
                    remote_url: 'javascript:alert(1)',
                    is_online: true,
                }], true);
            }""")
            assert not page.evaluate("window.__nodeMarkupRan")
            assert page.locator("#marketplace-cards-container img, #marketplace-cards-container svg").count() == 0
            assert page.locator("#marketplace-cards-container a[href^='javascript:']").count() == 0
            assert "Nicht gemessen" in page.locator("#marketplace-cards-container").inner_text()
            page.goto("https://portal.test/")
            page.wait_for_function("document.querySelector('#portal-ticker-tflops').textContent === 'Nicht gemessen'")
            assert errors == []
        finally:
            browser.close()
