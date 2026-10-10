"""Real document navigation and compact/mobile portal layout regression."""

import hashlib
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest

PORTAL = Path(__file__).resolve().parents[1] / "portal"
ROUTES = ("/", "/products", "/projects", "/marketplace", "/models", "/pricing", "/downloads", "/lan-mesh", "/playground", "/docs", "/security", "/status", "/fleet")


@pytest.mark.skipif(os.getenv("COMPUTEMESH_BROWSER_E2E") != "1", reason="browser E2E opt-in")
@pytest.mark.parametrize("width", [390, 1440])
def test_portal_documents_navigation_and_layout(width):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": width, "height": 900}, locale="de-DE")
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def serve(route):
            path = urlsplit(route.request.url).path
            if path.startswith(("/api/", "/v1/")):
                route.fulfill(json={"active_gpus": 1, "total_vram_gb": 16, "total_nodes": 1, "total_tflops": 0, "measurement_status": "live", "nodes": [], "data": []})
                return
            target = PORTAL / ("index.html" if path == "/" else path.lstrip("/"))
            if not target.suffix:
                target = target.with_suffix(".html")
            if target.is_file():
                route.fulfill(path=str(target))
            else:
                route.fulfill(status=404, body="Not found")

        page.route("https://portal.test/**", serve)
        page.goto("https://portal.test/")
        page.wait_for_function("document.querySelector('#portal-ticker-vram').textContent === '16,0 GB'")
        # Clicking must load a different document, not scroll in the current one.
        page.locator('.nav-links > li > a[href="/marketplace"]').click()
        page.wait_for_url("https://portal.test/marketplace")
        for path in ROUTES:
            page.goto(f"https://portal.test{path}")
            page.wait_for_function("typeof window.switchLanguage === 'function'")
            for language in ("de", "en"):
                page.evaluate("lang => switchLanguage(lang)", language)
                assert page.locator('header a[href^="#"]').count() == 0
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), (path, language, width)
                if path == "/pricing":
                    for button in page.locator('.calc-tab').all():
                        box = button.bounding_box()
                        assert box and box['x'] + box['width'] <= width + 1
                    page.locator('#tab-prov-btn').click()
                    assert page.locator('#pane-prov').is_visible()
                    page.locator('#tab-dev-btn').click()
            if path == "/":
                assert page.locator("h1").inner_text() == "ComputeMesh"
                assert page.locator('a[href="https://smartx.inetconnector.com/"]').count() > 0
                page.screenshot(path=str(Path(os.getenv("TEMP", ".")) / f"computemesh-portal-{width}.png"), full_page=True)
        assert errors == []
        browser.close()


@pytest.mark.skipif(os.getenv("COMPUTEMESH_BROWSER_E2E") != "1", reason="browser E2E opt-in")
@pytest.mark.parametrize("width", [390, 1440])
def test_navigation_dropdown_pointer_crosses_gap_and_clicks_link(width):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": 900}, locale="de-DE")

        def serve(route):
            path = urlsplit(route.request.url).path
            if path.startswith(("/api/", "/v1/")):
                route.fulfill(json={"nodes": [], "data": []})
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
            for language in ("de", "en"):
                for trigger_path, target_path in (("/products", "/models"), ("/projects", "/downloads")):
                    page.goto("https://portal.test/projects")
                    page.wait_for_function("typeof window.switchLanguage === 'function'")
                    page.evaluate("lang => switchLanguage(lang)", language)
                    group = page.locator(".nav-item.has-dropdown").filter(
                        has=page.locator(f'.nav-link[href="{trigger_path}"]')
                    )
                    trigger = group.locator(".nav-link")
                    menu = group.locator(".dropdown-menu")
                    trigger.hover()
                    expect(menu).to_be_visible()
                    page.wait_for_timeout(250)
                    trigger_box = trigger.bounding_box()
                    menu_box = menu.bounding_box()
                    bottom = trigger_box["y"] + trigger_box["height"]
                    page.mouse.move(
                        trigger_box["x"] + trigger_box["width"] / 2,
                        (bottom + menu_box["y"]) / 2,
                        steps=10,
                    )
                    expect(menu).to_be_visible(timeout=1000)
                    link = menu.locator(f'a[href="{target_path}"]')
                    box = link.bounding_box()
                    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=20)
                    expect(menu).to_be_visible()
                    link.click()
                    page.wait_for_url(f"https://portal.test{target_path}")
        finally:
            browser.close()


def test_every_portal_document_uses_the_same_navigation_and_asset_versions():
    documents = sorted(PORTAL.rglob("*.html"))
    documents = [
        path for path in documents
        if '<header class="site-header">' in path.read_text(encoding="utf-8-sig")
    ]
    canonical = re.search(
        r'<header class="site-header">.*?</header>',
        (PORTAL / "index.html").read_text(encoding="utf-8-sig"),
        re.DOTALL,
    )
    assert canonical is not None
    expected = hashlib.sha256(canonical.group(0).encode("utf-8")).hexdigest()

    assert len(documents) == 28
    for document in documents:
        text = document.read_text(encoding="utf-8-sig")
        header = re.search(r'<header class="site-header">.*?</header>', text, re.DOTALL)
        assert header is not None, document
        actual = hashlib.sha256(header.group(0).encode("utf-8")).hexdigest()
        assert actual == expected, document
        assert text.count('portal.css?v=5.2') == 1, document
        assert text.count('portal-business.css?v=5.1') == 1, document
        assert 'portal.css?v=3.7' not in text
        assert 'portal.css?v=4.3' not in text
