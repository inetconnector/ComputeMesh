"""Keep the desktop and Android WebUI neutral theme contract synchronized."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "portal" / "webui"
ANDROID = ROOT / "apps" / "android" / "app" / "src" / "main" / "assets" / "webui"


def test_neutral_theme_is_present_and_byte_identical():
    desktop_css = (DESKTOP / "neutral-theme.css").read_bytes()
    android_css = (ANDROID / "neutral-theme.css").read_bytes()
    assert desktop_css == android_css
    assert b"--cm-bg: #181a1c" in desktop_css
    assert b"prefers-reduced-motion" in desktop_css


def test_both_webui_entrypoints_load_the_shared_theme():
    for entrypoint in (DESKTOP / "index.html", ANDROID / "index.html"):
        source = entrypoint.read_text(encoding="utf-8")
        assert './neutral-theme.css?v=20261011-4' in source
