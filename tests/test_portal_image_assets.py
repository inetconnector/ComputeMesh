"""Keep public site image files and static references usable."""

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET


PORTAL = Path(__file__).resolve().parents[1] / "portal"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}


class ImageReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "img":
            assert "alt" in values, "Every content image needs an alt attribute"
        if tag in {"img", "source"} and values.get("src"):
            self.references.append(values["src"])
        if tag in {"img", "source"} and values.get("srcset"):
            self.references.extend(item.strip().split()[0] for item in values["srcset"].split(","))
        if tag == "link" and ("icon" in values.get("rel", "") or values.get("as") == "image"):
            if values.get("href"):
                self.references.append(values["href"])
        if tag == "meta" and values.get("property") in {"og:image", "twitter:image"}:
            if values.get("content"):
                self.references.append(values["content"])
        if tag == "a" and Path(urlsplit(values.get("href", "")).path).suffix.lower() in IMAGE_EXTENSIONS:
            self.references.append(values["href"])


def test_portal_static_image_references_resolve_locally():
    checked = 0
    for page in PORTAL.rglob("*.html"):
        if "webui" in page.relative_to(PORTAL).parts:
            continue  # Bundled WebUI has its own build/Android asset contract.
        parser = ImageReferences()
        parser.feed(page.read_text(encoding="utf-8-sig"))
        for reference in parser.references:
            if reference.startswith(("data:", "blob:")):
                continue
            parsed = urlsplit(reference)
            if parsed.hostname and parsed.hostname not in {"mesh.inetconnector.com", "inetconnector.com"}:
                continue
            path = unquote(parsed.path)
            target = PORTAL / path.lstrip("/") if path.startswith("/") else page.parent / path
            assert target.is_file(), f"{page.relative_to(PORTAL)}: missing {reference}"
            assert target.stat().st_size > 0, f"{page.relative_to(PORTAL)}: empty {reference}"
            checked += 1
    assert checked > 0


def test_portal_image_files_have_valid_headers():
    checked = 0
    for target in PORTAL.rglob("*"):
        if target.suffix.lower() not in IMAGE_EXTENSIONS or not target.is_file():
            continue
        data = target.read_bytes()
        assert data, f"Empty image: {target}"
        suffix = target.suffix.lower()
        if suffix == ".svg":
            assert ET.fromstring(data).tag.endswith("svg"), target
        elif suffix == ".png":
            assert data.startswith(b"\x89PNG\r\n\x1a\n"), target
        elif suffix in {".jpg", ".jpeg"}:
            assert data.startswith(b"\xff\xd8") and data.endswith(b"\xff\xd9"), target
        elif suffix == ".webp":
            assert data.startswith(b"RIFF") and data[8:12] == b"WEBP", target
        elif suffix == ".gif":
            assert data.startswith((b"GIF87a", b"GIF89a")), target
        checked += 1
    assert checked > 0
