"""Browser regression for stale NodeOS credentials and the shared gray theme."""

import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest


DASHBOARD = Path(__file__).resolve().parents[1] / "static" / "index.html"


@pytest.mark.skipif(os.getenv("COMPUTEMESH_BROWSER_E2E") != "1", reason="browser E2E opt-in")
@pytest.mark.parametrize("width", [390, 1280])
def test_expired_dashboard_token_can_be_replaced_without_reload(width):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path=os.getenv("COMPUTEMESH_BROWSER_EXECUTABLE") or None
        )
        page = browser.new_page(viewport={"width": width, "height": 900}, locale="de-DE")
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script("""
            sessionStorage.setItem('computemesh.nodeAuthToken', 'expired-token');
            window.prompt = () => 'fresh-token';
        """)

        def serve(route):
            path = urlsplit(route.request.url).path
            if path in ("", "/"):
                route.fulfill(path=str(DASHBOARD))
            elif path == "/api/status":
                if route.request.headers.get("x-node-auth-token") != "fresh-token":
                    route.fulfill(status=401, json={"error": {"code": 401}})
                else:
                    route.fulfill(json={
                        "node_id": "test-node", "is_windows": True,
                        "inventory": {"gpus": [], "total_vram_bytes": 0},
                        "config": {"rig_name": "test-node", "vram_reserve_mb": 512},
                        "telemetry": {}, "software": {"current_version": "test"},
                        "network": {"interfaces": [
                            {"interface": "web", "url": "https://mesh.inetconnector.com/"},
                            {"interface": "lan", "url": "javascript:alert(1)"},
                        ]},
                        "global_mesh": {
                            "source": "authenticated_registry", "total_nodes_online": 1,
                            "total_vram_gb": 16, "total_compute_tflops": 0,
                            "total_gpus_active": 1, "total_tokens_processed": 0,
                            "nodes": [{"node_id": "<img src=x onerror=alert(1)>",
                                       "gpu_summary": "<svg onload=alert(1)>",
                                       "gpus_count": 1, "vram_gb": 16, "tflops": 0}],
                        },
                    })
            elif path.startswith("/api/"):
                route.fulfill(json={})
            else:
                route.fulfill(status=404, body="Not found")

        page.route("https://node.test/**", serve)
        try:
            page.goto("https://node.test/#config")
            page.wait_for_function("document.querySelector('#header-status').textContent === 'ONLINE'")
            assert page.evaluate("sessionStorage.getItem('computemesh.nodeAuthToken')") == "fresh-token"
            assert not page.locator("#auth-required-banner").is_visible()
            assert page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(24, 26, 28)"
            assert page.evaluate("getComputedStyle(document.querySelector('.nav-tab.active')).backgroundColor") == "rgb(193, 212, 205)"
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            assert page.locator("#remote-ip-chips a[href^='javascript:']").count() == 0
            assert page.locator("#mesh-nodes-list img, #mesh-nodes-list svg").count() == 0
            assert errors == []

            page.evaluate("sessionStorage.setItem('computemesh.nodeAuthToken', 'expired-token')")
            page.add_init_script("window.prompt = () => null")
            page.reload()
            page.wait_for_function("document.querySelector('#auth-required-banner').style.display === 'flex'")
            assert page.evaluate("sessionStorage.getItem('computemesh.nodeAuthToken')") is None
            page.evaluate("window.prompt = () => 'fresh-token'")
            page.locator("#auth-retry-button").click()
            page.wait_for_function("document.querySelector('#header-status').textContent === 'ONLINE'")
            assert not page.locator("#auth-required-banner").is_visible()
            assert errors == []
        finally:
            browser.close()
