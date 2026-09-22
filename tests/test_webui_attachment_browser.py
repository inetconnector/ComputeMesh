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
                    body='{"id":"browser-check","object":"chat.completion","choices":[{"index":0,"message":{"role":"assistant","content":"OK"},"finish_reason":"stop"}]}',
                ),
            )
            with page.expect_request(lambda request: request.method == "POST" and "chat/completions" in request.url, timeout=10000) as pending_request:
                page.locator("textarea").last.fill("Lies den Anhang")
                page.locator("textarea").last.press("Enter")
            request_body = pending_request.value.post_data or ""
            self.assertIn("Browser attachment check", request_body)
            self.assertIn("Lies den Anhang", request_body)
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
                page.locator("textarea").last.fill("Was ist auf dem Bild?")
                page.locator("textarea").last.press("Enter")
            request_body = pending_request.value.post_data or ""
            self.assertIn('"model":"qwen2.5-vl"', request_body)
            self.assertIn("data:image/png;base64,", request_body)
            self.assertEqual(page_errors, [], "vision upload must not raise JavaScript errors")
        finally:
            context.close()


if __name__ == "__main__":
    unittest.main()
