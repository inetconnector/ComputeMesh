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
        assert './neutral-theme.css?v=20261026-1' in source


def test_no_neon_blue_borders_or_broken_dropdown_translations_in_entrypoints():
    for entrypoint in (DESKTOP / "index.html", ANDROID / "index.html"):
        source = entrypoint.read_text(encoding="utf-8")
        head = source.split("</head>")[0] if "</head>" in source else source
        # No neon blue or cyan borders in head styles
        assert "rgba(56, 189, 248" not in head
        assert "#38bdf8" not in head
        assert "#0284c7" not in head
        assert "#0ea5e9" not in head
        assert "rgba(0, 240, 255" not in head
        # No broken desktop translation that displaces submenus into overlapping clipped boxes
        assert "translate: -95% 50px" not in source

    # Theme CSS must be strictly neutral without neon blue border tints
    desktop_css = (DESKTOP / "neutral-theme.css").read_text(encoding="utf-8")
    assert "rgba(56, 189, 248" not in desktop_css
    assert "rgba(0, 240, 255" not in desktop_css
    assert "#38bdf8" not in desktop_css
    assert "#0ea5e9" not in desktop_css
