# SPDX-License-Identifier: Apache-2.0
"""Unit and regression tests for android_play_store_tools MCP module."""

import json
import os
import unittest
from pathlib import Path

from services.mcp.builtin.android_play_store_tools import (
    validate_store_listing,
    validate_store_graphics,
    inspect_android_manifest_or_bundle,
    sync_play_console_metadata,
)
from services.mcp.tool_registry import ToolRegistry


class TestAndroidPlayStoreTools(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.temp_dir = Path("temp_test_play_store_assets")
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        if self.temp_dir.exists():
            for f in self.temp_dir.glob("**/*"):
                if f.is_file():
                    try:
                        f.unlink()
                    except Exception:
                        pass
            try:
                for d in sorted(self.temp_dir.glob("**/*"), reverse=True):
                    if d.is_dir():
                        d.rmdir()
                self.temp_dir.rmdir()
            except Exception:
                pass

    def test_validate_store_listing_valid(self):
        title = "English News Kiosk Pro"
        short_desc = "Ad-free, multi-source UK, US, CA & AU news kiosk with custom feeds."
        full_desc = "English News Kiosk Pro provides instant access to hundreds of news publications worldwide."

        res = validate_store_listing(title, short_desc, full_desc)
        self.assertTrue(res["valid"])
        self.assertEqual(len(res["errors"]), 0)
        self.assertLessEqual(res["metrics"]["title_length"], 30)
        self.assertLessEqual(res["metrics"]["short_desc_length"], 80)
        self.assertLessEqual(res["metrics"]["full_desc_length"], 4000)

    def test_validate_store_listing_exceeding_limits(self):
        long_title = "This Title Is Super Long And Far Exceeds Thirty Chars Total"
        long_short = "This short description is definitely too long because it has more than eighty characters in total length right here."
        full_desc = "Valid full description."

        res = validate_store_listing(long_title, long_short, full_desc)
        self.assertFalse(res["valid"])
        self.assertTrue(any("Title exceeds" in err for err in res["errors"]))
        self.assertTrue(any("Short description exceeds" in err for err in res["errors"]))

    def test_validate_store_listing_policy_warnings(self):
        title = "Best Kiosk App"
        short_desc = "The #1 news tool available anywhere."
        full_desc = "Get 100% free download now with guaranteed speed."

        res = validate_store_listing(title, short_desc, full_desc, check_prohibited_terms=True)
        self.assertTrue(len(res["warnings"]) > 0)

    def test_sync_play_console_metadata(self):
        res = sync_play_console_metadata(
            asset_dir=str(self.temp_dir),
            package_name="com.inetconnector.englishnewskiosk.pro",
            edition_name="englishPro",
            is_paid=True,
            default_price_eur="5.99",
        )
        self.assertTrue(res["success"])
        self.assertTrue((self.temp_dir / "package_name.txt").exists())
        self.assertTrue((self.temp_dir / "metadata.json").exists())

        pkg_txt = (self.temp_dir / "package_name.txt").read_text(encoding="utf-8").strip()
        self.assertEqual(pkg_txt, "com.inetconnector.englishnewskiosk.pro")

        meta = json.loads((self.temp_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["package_name"], "com.inetconnector.englishnewskiosk.pro")
        self.assertEqual(meta["edition"], "englishPro")
        self.assertTrue(meta["is_paid"])
        self.assertEqual(meta["default_price_eur"], "5.99")

    def test_inspect_android_manifest_or_bundle_gradle(self):
        # Create a sample build.gradle
        gradle_file = self.temp_dir / "build.gradle.kts"
        gradle_file.write_text(
            '''
            android {
                namespace = "com.inetconnector.testapp"
                defaultConfig {
                    applicationId = "com.inetconnector.testapp.pro"
                    minSdk = 24
                    targetSdk = 35
                    versionCode = 105
                    versionName = "1.5"
                }
            }
            ''',
            encoding="utf-8",
        )

        res = inspect_android_manifest_or_bundle(str(gradle_file))
        self.assertTrue(res["success"])
        self.assertEqual(res["package_name"], "com.inetconnector.testapp.pro")
        self.assertEqual(res["version_code"], 105)
        self.assertEqual(res["version_name"], "1.5")
        self.assertEqual(res["min_sdk"], 24)
        self.assertEqual(res["target_sdk"], 35)

    def test_registry_integration(self):
        res = self.registry.execute_tool(
            "validate_store_listing",
            {
                "title": "News Kiosk Pro",
                "short_description": "Clean news reader for global publications.",
                "full_description": "Read top newspapers securely and without trackers.",
            },
            is_owner=True,
        )
        self.assertTrue(res.get("valid"))


if __name__ == "__main__":
    unittest.main()
