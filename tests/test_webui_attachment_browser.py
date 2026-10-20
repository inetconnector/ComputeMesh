# SPDX-License-Identifier: Apache-2.0
"""Browser regression for the bundled chat composer's native attachment menu.

Run with COMPUTEMESH_BROWSER_E2E=1 when Playwright and Chrome/Edge are available.
"""
from __future__ import annotations

import os
import shutil
import sys
import threading
import unittest
from base64 import b64decode
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.appliance_dashboard.server import create_dashboard_server
from tools.appliance.appliance_config import load_appliance_config
from tools.appliance.hardware_detector import scan_rig_hardware_stable


@unittest.skipUnless(os.environ.get("COMPUTEMESH_BROWSER_E2E") == "1", "browser E2E opt-in")
class TestWebUIAttachmentBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from playwright.sync_api import sync_playwright

        chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
        executable = next((str(path) for path in (chrome, edge) if path.exists()), None)
        executable = executable or shutil.which("google-chrome") or shutil.which("chromium")
        if not executable:
            raise unittest.SkipTest("Chrome/Edge/Chromium not installed")

        # Browser UI tests must not start the production heartbeat worker.
        with patch("services.appliance_dashboard.tunnel_relay.start_cloud_tunnel_relay"):
            cls.server, cls.port = create_dashboard_server(
                host="127.0.0.1",
                port=0,
                config=load_appliance_config(),
                inventory=scan_rig_hardware_stable(),
                node_id="test-webui-attachments",
            )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True, executable_path=executable)

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "browser"):
            cls.browser.close()
        if hasattr(cls, "playwright"):
            cls.playwright.stop()
        if hasattr(cls, "server"):
            cls.server.shutdown()
            cls.server.server_close()

    def test_update_card_stays_clickable_above_custom_overlays(self) -> None:
        context = self.browser.new_context(viewport={"width": 390, "height": 844}, locale="de-DE")
        page = context.new_page()
        try:
            page.goto(f"http://127.0.0.1:{self.port}/webui/", wait_until="domcontentloaded")
            page.evaluate(
                """
                () => {
                    const blocker = document.createElement('div');
                    blocker.id = 'hit-test-blocker';
                    blocker.style.cssText = 'position:fixed;inset:0;z-index:1000005;background:transparent;pointer-events:auto';
                    document.body.appendChild(blocker);

                    const wrapper = document.createElement('div');
                    wrapper.className = 'fixed right-4 bottom-4 z-9999 flex flex-col items-end gap-1';
                    wrapper.innerHTML = '<div data-slot="card"><p>Update available</p><button id="update-hit-test">Reload</button></div>';
                    document.body.appendChild(wrapper);
                    document.getElementById('update-hit-test').addEventListener('click', () => {
                        document.body.dataset.updateClicked = 'yes';
                    });
                }
                """
            )
            button = page.locator("#update-hit-test")
            button.click()
            self.assertEqual(page.locator("body").get_attribute("data-update-clicked"), "yes")
            owns_hit_target = button.evaluate(
                """
                (button) => {
                    const box = button.getBoundingClientRect();
                    const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
                    return hit === button || button.contains(hit);
                }
                """
            )
            self.assertTrue(owns_hit_target, "the visible Reload button must own its physical touch target")
        finally:
            context.close()

    def test_light_theme_contrast_and_agent_panel_disclosure(self) -> None:
        context = self.browser.new_context(viewport={"width": 1280, "height": 900}, locale="de-DE")
        page = context.new_page()
        try:
            page.goto(f"http://127.0.0.1:{self.port}/webui/", wait_until="domcontentloaded")
            page.locator("#cm-agent-toggle").wait_for(timeout=15000)
            page.evaluate("document.documentElement.classList.remove('dark')")
            contrast = page.evaluate(
                """
                () => {
                    const parse = (value) => value.match(/[0-9.]+/g).slice(0, 3).map(Number);
                    const lum = (rgb) => {
                        const c = rgb.map((v) => { v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; });
                        return .2126 * c[0] + .7152 * c[1] + .0722 * c[2];
                    };
                    const style = getComputedStyle(document.body);
                    const a = lum(parse(style.color));
                    const b = lum(parse(style.backgroundColor));
                    return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
                }
                """
            )
            self.assertGreaterEqual(contrast, 4.5)
            self.assertTrue(page.locator("#cm-agent-session-panel").get_attribute("hidden") is not None)
            page.locator("#cm-agent-toggle").click()
            panel = page.locator("#cm-agent-session-panel")
            panel.wait_for(state="visible", timeout=5000)
            panel_text = panel.inner_text().lower()
            self.assertTrue(
                "längere aufgaben" in panel_text or "longer, multi-step tasks" in panel_text,
                panel_text,
            )
            self.assertGreaterEqual(float(panel.evaluate("el => parseFloat(getComputedStyle(el).fontSize)")), 14)
            page.locator(".cm-agent-close").click()
            panel.wait_for(state="hidden", timeout=5000)
        finally:
            context.close()

    def test_desktop_submenu_and_text_attachment(self) -> None:
        context = self.browser.new_context(viewport={"width": 1280, "height": 900}, locale="de-DE")
        page = context.new_page()
        chooser_events = []
        page_errors = []
        page.on("filechooser", lambda chooser: chooser_events.append(chooser))
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        try:
            page.goto(f"http://127.0.0.1:{self.port}/webui/", wait_until="domcontentloaded")
            page.locator("button.file-upload-button").first.wait_for(timeout=15000)
            page.locator("button.file-upload-button").first.click()
            page.get_by_text("Dateien hinzufügen", exact=True).last.click()
            page.get_by_text("Textdateien", exact=True).last.wait_for(timeout=5000)
            self.assertEqual(chooser_events, [], "submenu trigger must not open a file picker")

            with page.expect_file_chooser(timeout=5000) as pending:
                page.get_by_text("Textdateien", exact=True).last.click()
            pending.value.set_files({"name": "webui-check.txt", "mimeType": "text/plain", "buffer": b"Browser attachment check"})
            page.get_by_text("webui-check.txt", exact=False).first.wait_for(timeout=10000)
            self.assertEqual(len(chooser_events), 1, "one leaf click must open one file picker")

            page.route(
                "**/*chat/completions*",
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body='{"id":"browser-check","object":"chat.completion","choices":[{"index":0,"message":{"role":"assistant","content":"OK"},"finish_reason":"stop"}],"compute_mesh_execution":{"execution_id":"browser-execution","model_id":"qwen2.5-vl","provider_node_ids":["browser-node"]}}',
                ),
            )
            with page.expect_request(lambda request: request.method == "POST" and "chat/completions" in request.url, timeout=10000) as pending_request:
                page.locator("textarea").first.fill("Lies den Anhang")
                page.locator("textarea").first.press("Enter")
            request_body = pending_request.value.post_data or ""
            self.assertIn("Browser attachment check", request_body)
            self.assertIn("Lies den Anhang", request_body)
            page.locator("#cm-execution-status").filter(has_text="browser-node").wait_for(timeout=5000)
            self.assertEqual(page_errors, [], "desktop WebUI must not raise JavaScript errors")
        finally:
            context.close()

    def test_mobile_sheet_and_pdf_attachment(self) -> None:
        context = self.browser.new_context(
            viewport={"width": 390, "height": 780},
            is_mobile=True,
            has_touch=True,
            locale="de-DE",
        )
        page = context.new_page()
        chooser_events = []
        page_errors = []
        page.on("filechooser", lambda chooser: chooser_events.append(chooser))
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        try:
            page.goto(f"http://127.0.0.1:{self.port}/webui/", wait_until="domcontentloaded")
            page.locator("button.file-upload-button").first.wait_for(timeout=15000)
            page.locator("button.file-upload-button").first.click()
            pdf_action = page.locator("button:visible").filter(has_text="PDF-Dateien").first
            pdf_action.wait_for(timeout=5000)
            page.get_by_text("Dateien hinzufügen", exact=True).last.click()
            pdf_action.wait_for(state="hidden", timeout=5000)
            page.get_by_text("Dateien hinzufügen", exact=True).last.click()
            pdf_action.wait_for(timeout=5000)
            self.assertEqual(chooser_events, [], "mobile category must only expand the sheet")

            with page.expect_file_chooser(timeout=5000) as pending:
                pdf_action.click()
            pending.value.set_files({
                "name": "webui-check.pdf",
                "mimeType": "application/pdf",
                "buffer": b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF",
            })
            page.get_by_text("webui-check.pdf", exact=False).first.wait_for(timeout=10000)
            self.assertEqual(len(chooser_events), 1, "one mobile leaf click must open one file picker")
            self.assertEqual(page_errors, [], "mobile WebUI must not raise JavaScript errors")
        finally:
            context.close()

    def test_vision_image_attachment_reaches_selected_model(self) -> None:
        context = self.browser.new_context(viewport={"width": 1280, "height": 900}, locale="de-DE")
        page = context.new_page()
        page_errors = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.route(
            "**/v1/models",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='{"data":[{"id":"qwen2.5-vl","available":true,"modalities":["text","vision"]}]}',
            ),
        )
        try:
            page.goto(f"http://127.0.0.1:{self.port}/webui/", wait_until="domcontentloaded")
            page.wait_for_function(
                "window.ComputeMeshModelSelector?.getSelectedModel()?.id === 'qwen2.5-vl'",
                timeout=15000,
            )
            page.locator("button.file-upload-button").first.click()
            page.get_by_text("Dateien hinzufügen", exact=True).last.click()
            image_action = page.locator(".images-button:visible").first
            image_action.wait_for(timeout=5000)
            with page.expect_file_chooser(timeout=5000) as pending:
                image_action.click(timeout=5000)
            png = b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9YlOmwAAAABJRU5ErkJggg=="
            )
            pending.value.set_files({"name": "webui-check.png", "mimeType": "image/png", "buffer": png})
            page.locator('img[alt="webui-check.png"]').first.wait_for(timeout=10000)

            page.route(
                "**/*chat/completions*",
                lambda route: route.fulfill(status=200, content_type="application/json", body='{"choices":[]}'),
            )
            with page.expect_request(lambda request: request.method == "POST" and "chat/completions" in request.url, timeout=10000) as pending_request:
                page.locator("textarea").first.fill("Was ist auf dem Bild?")
                page.locator("textarea").first.press("Enter")
            request_body = pending_request.value.post_data or ""
            self.assertIn('"model":"qwen2.5-vl"', request_body)
            self.assertIn("data:image/png;base64,", request_body)
            self.assertEqual(page_errors, [], "vision upload must not raise JavaScript errors")
        finally:
            context.close()

    def test_stale_model_uses_gateway_when_peer_or_slots_fail(self) -> None:
        selector = (REPO_ROOT / "portal/webui/model-selector.js").read_text(encoding="utf-8")
        for failure in ("peer", "slots", "completion", "valid_selection"):
            with self.subTest(failure=failure):
                context = self.browser.new_context()
                page = context.new_page()
                completions = []

                def respond(route):
                    url = route.request.url
                    if "chat/completions" in url and "peer.test" in url:
                        route.abort()
                    elif "chat/completions" in url:
                        completions.append(route.request.post_data_json)
                        route.fulfill(json={"choices": []})
                    elif url == "https://gateway.test/webui/":
                        route.fulfill(content_type="text/html", body="<html><body></body></html>")
                    elif url.endswith("/v1/models") and "gateway.test" in url:
                        route.fulfill(json={"data": [
                            {"id": "qwen2.5:3b", "available": True},
                            {"id": "qwen2.5:1.5b", "available": True},
                        ]})
                    elif url.endswith("/v1/models") and failure == "completion":
                        route.fulfill(json={"data": [{"id": "peer:7b", "available": True}]})
                    elif "/fleet" in url:
                        nodes = [{"is_online": True, "endpoint": "https://peer.test"}]
                        route.fulfill(json={
                            "nodes": nodes if failure in ("peer", "completion") else [],
                        })
                    elif url.endswith("/slots") and failure != "slots":
                        route.fulfill(json=[])
                    else:
                        route.abort()

                page.route("**/*", respond)
                try:
                    page.goto("https://gateway.test/webui/")
                    stored = {
                        "completion": "peer:7b", "valid_selection": "qwen2.5:1.5b",
                    }.get(failure, "qwen/qwen2.5-7b-instruct")
                    page.evaluate("id => localStorage.setItem('cm_selected_model_id', id)", stored)
                    page.add_script_tag(content=selector)
                    page.evaluate("""async () => {
                        await fetch('/webui/chat/completions', {
                            method: 'POST', headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({model: 'qwen/qwen2.5-7b-instruct',
                                messages: [{role: 'user', content: 'Hallo'}]})
                        });
                    }""")
                    expected = "qwen2.5:1.5b" if failure == "valid_selection" else "qwen2.5:3b"
                    self.assertEqual(completions[0]["model"], expected)
                    saved = page.evaluate("localStorage.getItem('cm_selected_model_id')")
                    self.assertEqual(saved, expected)
                finally:
                    context.close()


if __name__ == "__main__":
    unittest.main()
