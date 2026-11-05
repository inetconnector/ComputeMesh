"""Unit and negative tests for ComputeMesh/tools/release/check_portal_i18n.py."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tools.release import check_portal_i18n


class TestCheckPortalI18n(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[3]
        self.portal = self.repo_root / "portal"

    def test_current_portal_passes_i18n_and_downloads_checks(self) -> None:
        pages = sorted(p for p in self.portal.glob("*.html")) + [
            self.portal / "downloads" / "index.html"
        ]
        problems: list[str] = []
        check_portal_i18n.check_i18n(self.portal, pages, problems)
        self.assertEqual(problems, [])

    def test_untagged_german_text_on_downloads_page_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_portal = Path(tmp)
            (tmp_portal / "portal-core.js").write_text(
                (self.portal / "portal-core.js").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (tmp_portal / "portal.js").write_text(
                (self.portal / "portal.js").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            bad_html = (self.portal / "downloads.html").read_text(encoding="utf-8").replace(
                'data-i18n="dl_linux_cmd_hint"', ""
            )
            page = tmp_portal / "downloads.html"
            page.write_text(bad_html, encoding="utf-8")
            problems: list[str] = []
            check_portal_i18n.check_i18n(tmp_portal, [page], problems)
            self.assertTrue(
                any("Installationsskript zuerst prüfen" in p for p in problems),
                problems,
            )

    def test_german_value_in_english_dictionary_is_rejected(self) -> None:
        self.assertTrue(
            check_portal_i18n.is_german(
                "Installationsskript zuerst prüfen, dann gezielt ausführen."
            )
        )
        self.assertFalse(
            check_portal_i18n.is_german(
                "Inspect the installer script first, then run it deliberately."
            )
        )

    def test_missing_nodeos_artifact_on_downloads_page_is_rejected(self) -> None:
        manifest = check_portal_i18n.load_manifest(self.portal)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_portal = Path(tmp)
            (tmp_portal / "downloads").mkdir()
            stripped = (
                (self.portal / "downloads.html")
                .read_text(encoding="utf-8")
                .replace("/downloads/computemesh-nodeos-x86_64.iso", "/docs#removed")
            )
            (tmp_portal / "downloads.html").write_text(stripped, encoding="utf-8")
            (tmp_portal / "downloads" / "index.html").write_text(stripped, encoding="utf-8")
            problems: list[str] = []
            check_portal_i18n.check_downloads(
                tmp_portal, manifest, problems, verify_bytes=False
            )
            self.assertTrue(
                any("computemesh-nodeos-x86_64.iso" in p for p in problems),
                problems,
            )


if __name__ == "__main__":
    unittest.main()

