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
        browser = playwright.chromium.launch(
            headless=True, executable_path=os.getenv("COMPUTEMESH_BROWSER_EXECUTABLE") or None
        )
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
                    assert page.locator('#live-pricing').is_visible()
                    assert page.locator('#tab-prov-btn').count() == 0
                if path == "/downloads":
                    win_button = page.locator('[data-i18n="dl_win_btn"]')
                    if language == "de":
                        assert win_button.inner_text() == "ComputeMesh (.exe) herunterladen"
                        assert page.locator('[data-i18n="dl_win_title"]').inner_text() == "Windows System-Tray-Client"
                    else:
                        assert win_button.inner_text() == "Download ComputeMesh (.exe)"
                        assert page.locator('[data-i18n="dl_win_title"]').inner_text() == "Windows Provider Agent"
                    assert "Setup" not in win_button.inner_text()
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
        browser = playwright.chromium.launch(
            headless=True, executable_path=os.getenv("COMPUTEMESH_BROWSER_EXECUTABLE") or None
        )
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
                    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                    page.wait_for_url(f"https://portal.test{target_path}")
        finally:
            browser.close()


@pytest.mark.skipif(os.getenv("COMPUTEMESH_BROWSER_E2E") != "1", reason="browser E2E opt-in")
def test_downloads_page_uses_one_language_and_short_windows_button():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path=os.getenv("COMPUTEMESH_BROWSER_EXECUTABLE") or None
        )
        page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="de-DE")

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
        page.goto("https://portal.test/downloads", wait_until="domcontentloaded", timeout=10000)
        page.wait_for_function("typeof window.switchLanguage === 'function'")
        page.evaluate("switchLanguage('de')")
        assert page.locator('[data-i18n="dl_win_btn"]').inner_text() == "ComputeMesh (.exe) herunterladen"
        assert page.locator('[data-i18n="dl_android_status"]').inner_text() == "v1.2.164 • Produktionssigniert"
        page.evaluate("switchLanguage('en')")
        assert page.locator('[data-i18n="dl_win_btn"]').inner_text() == "Download ComputeMesh (.exe)"
        assert page.locator('[data-i18n="dl_android_status"]').inner_text() == "v1.2.164 • Production signed"
        assert "Setup" not in page.locator('[data-i18n="dl_win_btn"]').inner_text()
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

    # The Agent Workspace is a canonical portal document as well.
    assert len(documents) == 29
    agent_document = PORTAL / "agent.html"
    for document in documents:
        text = document.read_text(encoding="utf-8-sig")
        header = re.search(r'<header class="site-header">.*?</header>', text, re.DOTALL)
        assert header is not None, document
        if document == agent_document:
            # The workspace intentionally uses its own compact authenticated
            # header instead of the public marketing navigation.
            assert "AGENT WORKSPACE" in header.group(0)
            assert 'href="/fleet"' in header.group(0)
            continue
        actual = hashlib.sha256(header.group(0).encode("utf-8")).hexdigest()
        assert actual == expected, document
        assert text.count('portal.css?v=5.2') == 1, document
        assert text.count('portal-business.css?v=5.1') == 1, document
        if 'portal-core.js' in text:
            assert text.count('portal-core.js?v=5.4') == 1, document
            assert 'portal-core.js?v=5.3' not in text
        assert 'portal.css?v=3.7' not in text
        assert 'portal.css?v=4.3' not in text
        if '<footer' in text:
            assert 'data-i18n="footer_rights"' in text, document


def test_download_entrypoints_and_translation_keys_are_consistent():
    downloads = (PORTAL / "downloads.html").read_text(encoding="utf-8-sig")
    downloads_index = (PORTAL / "downloads" / "index.html").read_text(encoding="utf-8-sig")
    assert downloads == downloads_index
    assert "ComputeMesh Setup (EXE) herunterladen" not in downloads
    required_keys = (
        "dl_meta_title",
        "dl_win_status",
        "dl_win_title",
        "dl_win_desc",
        "dl_win_btn",
        "dl_win_feature_cuda",
        "dl_win_feature_webui",
        "dl_win_feature_lan",
        "dl_win_platforms",
        "dl_android_status",
        "dl_android_feature_webui",
        "dl_android_feature_lan",
        "dl_android_feature_signed",
        "dl_android_store_btn",
        "dl_linux_status",
        "dl_linux_platforms",
        "dl_security_title",
        "dl_security_desc",
        "footer_github",
    )
    core = (PORTAL / "portal-core.js").read_text(encoding="utf-8-sig")
    for key in required_keys:
        assert downloads.count(f'data-i18n="{key}"') == 1, key
        assert core.count(f"{key}:") >= 2, key


def test_primary_catalog_pages_mark_page_content_for_bilingual_switching():
    assert (PORTAL / "models.html").read_bytes() == (PORTAL / "models" / "index.html").read_bytes()
    required = {
        "marketplace.html": (
            "market_provider_tag", "market_provider_title", "market_provider_desc",
            "market_provider_button", "footer_brand_desc", "footer_col_platform",
            "footer_col_resources", "footer_col_legal", "footer_rights", "footer_tech_status",
        ),
        "models.html": (
            "models_filter_all", "models_filter_code", "models_filter_reasoning",
            "models_filter_vision", "models_filter_fast", "models_integration_tag",
            "models_integration_title", "models_integration_desc", "models_copy_code",
            "footer_brand_desc", "footer_col_platform", "footer_col_resources",
            "footer_col_legal", "footer_rights", "footer_tech_status",
        ),
        "pricing.html": (
            "pricing_tag", "pricing_title", "pricing_sub", "pricing_loading",
            "pricing_disclaimer", "footer_brand_desc", "footer_col_platform",
            "footer_col_resources", "footer_col_legal", "footer_rights", "footer_tech_status",
        ),
    }
    core = (PORTAL / "portal-core.js").read_text(encoding="utf-8-sig")
    for filename, keys in required.items():
        page = (PORTAL / filename).read_text(encoding="utf-8-sig")
        for key in keys:
            assert f'data-i18n="{key}"' in page, (filename, key)
            assert core.count(f"{key}:") >= 2, key


def test_nginx_clean_models_routes_never_fall_through_to_directory_listing():
    config = (PORTAL / "vhost_nginx.conf").read_text(encoding="utf-8")
    assert "location = /models {" in config
    assert "location = /models/ {" in config
    assert config.count("try_files /models.html =404;") == 2


def test_status_page_marks_ledger_explorer_for_bilingual_switching():
    page = (PORTAL / "status.html").read_text(encoding="utf-8-sig")
    core = (PORTAL / "portal-core.js").read_text(encoding="utf-8-sig")
    required = (
        "status_ledger_title", "status_ledger_badge", "status_ledger_desc",
        "status_ledger_refresh", "status_ledger_height", "status_ledger_genesis",
        "status_ledger_receipts", "status_ledger_anchored", "status_ledger_integrity",
        "status_ledger_valid", "status_ledger_storage", "status_ledger_verify_title",
        "status_ledger_verify_placeholder", "status_ledger_verify_button",
        "status_ledger_recent_blocks", "status_tools_title", "status_tools_active",
        "status_tools_loading", "status_tools_none", "status_verify_success",
    )
    for key in required:
        assert (f'data-i18n="{key}"' in page or f'data-i18n-ph="{key}"' in page or f"'{key}'" in page), key
        assert core.count(f"{key}:") >= 2, key


def test_docs_page_marks_architecture_flow_and_footer_for_bilingual_switching():
    docs = (PORTAL / "docs.html").read_text(encoding="utf-8-sig")
    core = (PORTAL / "portal-core.js").read_text(encoding="utf-8-sig")
    for key in (
        "docs_arch_flow_1", "docs_arch_flow_2", "docs_arch_flow_3",
        "docs_arch_flow_4", "docs_arch_flow_5", "footer_brand_desc",
        "footer_col_platform", "footer_col_resources", "footer_col_legal",
        "footer_rights", "footer_tech_status",
    ):
        assert f'data-i18n="{key}"' in docs, key
        assert core.count(f"{key}:") >= 2, key
