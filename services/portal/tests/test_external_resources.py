"""Privacy-by-design regression tests for public portal HTML."""

from pathlib import Path
import unittest


PORTAL_DIR = Path(__file__).resolve().parents[3] / "portal"
FORBIDDEN_BROWSER_ORIGINS = (
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "cdn.jsdelivr.net",
    "googletagmanager.com",
    "google-analytics.com",
    "connect.facebook.net",
)


class ExternalResourcePrivacyTests(unittest.TestCase):
    def test_portal_html_has_no_forbidden_third_party_resources(self) -> None:
        violations: list[str] = []
        for path in sorted(PORTAL_DIR.glob("*.html")):
            text = path.read_text(encoding="utf-8")
            for origin in FORBIDDEN_BROWSER_ORIGINS:
                if origin in text:
                    violations.append(f"{path.name}: {origin}")
        self.assertEqual(violations, [], "Forbidden third-party browser resources: " + ", ".join(violations))


if __name__ == "__main__":
    unittest.main()
