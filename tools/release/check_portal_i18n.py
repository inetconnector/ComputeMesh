#!/usr/bin/env python3
"""Fail-closed portal localisation and download-artifact gate.

Mandatory before every commit and every publication of the portal
(see AGENTS.md). Checks, without network access:

1. Dictionary parity & completeness: ``translations.en`` and ``translations.de``
   in ``portal-core.js`` have 100% identical key sets, and every ``data-i18n`` /
   ``data-i18n-ph`` / ``data-i18n-title`` key used by any portal page exists,
   non-empty, in BOTH ``en`` and ``de``.
2. No untranslated text:
   - On ``downloads.html`` / ``downloads/index.html``, every natural-language
     text node must be inside a ``data-i18n`` element (or ``translate="no"`` /
     registered brand badge).
   - Across all portal HTML documents, no German text node may remain uncovered
     by ``data-i18n``, ``portal.js`` ``STATIC_TEXT_DE`` (when ``portal.js`` is
     loaded), or ``ai-auth.html`` ``studioI18n``.
3. Language purity: English dictionary values must not contain German text.
4. Downloads page integrity: ``downloads.html`` and ``downloads/index.html``
   are byte-identical, the NodeOS ISO, IMG, and runtime archive are offered,
   and every ``/downloads/<file>`` link points to an artifact that is listed in
   the signed release manifest with matching size and SHA-256.
5. Version consistency: every ``vX.Y.Z`` shown in download texts equals the
   signed manifest version, and the Android metadata agrees with it.
6. Freshness (``--publish``): runner/NodeOS/installer sources must not have
   changed after the manifest release date; otherwise the binaries are stale
   and must be rebuilt and re-signed before publishing.

Exit code 0 = PASS, 2 = NO-GO.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

LANGS = ("en", "de")
I18N_ATTRS = ("data-i18n", "data-i18n-ph", "data-i18n-title")
SKIP_TAGS = {"script", "style", "code", "pre", "kbd", "samp", "svg", "noscript", "template", "title"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
             "param", "source", "track", "wbr"}
BRAND_AND_PROPER_NOUN_ALLOWLIST = {
    "LIVE MESH",
    "🤖 Agent Workspace",
    "🤖 AGENT WORKSPACE",
    "Bismarckstraße 6",
    "97209 Veitshöchheim",
}
GERMAN_WORDS = {
    "und", "oder", "für", "mit", "nicht", "kein", "keine", "zuerst", "dann", "ansehen",
    "herunterladen", "prüfen", "dienst", "installieren", "auf", "der", "die", "das", "ist",
    "werden", "wird", "bitte", "über", "einrichtung", "unterstützt", "betriebsmodus",
    "neustart", "deinen", "deine", "dein", "sicherheit", "rechtliches", "anmelden",
}
GERMAN_CHARS = re.compile(r"[äöüÄÖÜß]")
WORD_RE = re.compile(r"[A-Za-zÄÖÜäöüß]{2,}")
VERSION_RE = re.compile(r"\bv(\d+\.\d+\.\d+)\b")
# Runner / NodeOS / installer sources whose change makes the published binaries stale.
FRESHNESS_PATHS = (
    "tools/appliance",
    "services/appliance_dashboard",
    "nodeos",
    "deploy/windows/build_installer.py",
    "deploy/appliance/install.sh",
)
FRESHNESS_PLATFORMS = (
    "windows-x64",
    "linux-x64",
    "nodeos-iso",
    "nodeos-img",
    "nodeos-runtime-x64",
    "installer-script",
)
NODEOS_FILES = (
    "computemesh-nodeos-x86_64.iso",
    "computemesh-nodeos-x86_64.img.xz",
    "computemesh-nodeos-runtime-x86_64.tar.gz",
)
AUX_DOWNLOADS = {"version.json"}


class GateError(Exception):
    pass


def load_translations(js_path: Path) -> dict[str, dict[str, str]]:
    """Evaluate the ``translations`` object literal of portal-core.js with Node."""
    src = js_path.read_text(encoding="utf-8")
    marker = "var translations = window.translations || {"
    start = src.find(marker)
    if start < 0:
        raise GateError(f"translations object not found in {js_path}")
    i = start + len(marker) - 1
    depth = 0
    quote = ""
    while i < len(src):
        ch = src[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'`":
            quote = ch
        elif src.startswith("//", i):
            i = src.find("\n", i)
            continue
        elif src.startswith("/*", i):
            i = src.find("*/", i) + 2
            continue
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    literal = src[start + len(marker) - 1: i + 1]
    script = (
        "const vm=require('vm');let s='';process.stdin.on('data',d=>s+=d);"
        "process.stdin.on('end',()=>{const o=vm.runInNewContext('('+s+')');"
        "process.stdout.write(JSON.stringify({en:o.en||{},de:o.de||{}}));});"
    )
    result = subprocess.run(["node", "-e", script], input=literal.encode("utf-8"),
                            capture_output=True, check=False)
    if result.returncode != 0:
        raise GateError(f"cannot evaluate translations: {result.stderr.decode('utf-8', 'replace')[:300]}")
    return json.loads(result.stdout.decode("utf-8"))


def load_static_text_de(portal_js_path: Path) -> set[str]:
    """Load normalized German values from ``STATIC_TEXT_DE`` in ``portal.js``."""
    if not portal_js_path.is_file():
        return set()
    src = portal_js_path.read_text(encoding="utf-8")
    match = re.search(r"const STATIC_TEXT_DE = (\{.*?\n  \});", src, re.DOTALL)
    if not match:
        return set()
    script = (
        "const vm=require('vm');let s='';process.stdin.on('data',d=>s+=d);"
        "process.stdin.on('end',()=>{const o=vm.runInNewContext('('+s+')');"
        "process.stdout.write(JSON.stringify(Object.values(o)));});"
    )
    result = subprocess.run(["node", "-e", script], input=match.group(1).encode("utf-8"),
                            capture_output=True, check=False)
    if result.returncode != 0:
        raise GateError(f"cannot evaluate STATIC_TEXT_DE: {result.stderr.decode('utf-8', 'replace')[:300]}")
    values = json.loads(result.stdout.decode("utf-8"))
    return {" ".join(str(v).split()) for v in values}


class PageScanner(HTMLParser):
    def __init__(self, *, dynamic_i18n_ids: set[str] | None = None) -> None:
        super().__init__(convert_charrefs=True)
        self.dynamic_i18n_ids = dynamic_i18n_ids or set()
        self.stack: list[tuple[str, bool, bool]] = []  # (tag, covered, skipped)
        self.keys: dict[str, set[str]] = {a: set() for a in I18N_ATTRS}
        self.untagged: list[tuple[int, str]] = []
        self.links: list[str] = []
        self.images: list[str] = []
        self.in_body = False

    def _state(self) -> tuple[bool, bool]:
        if not self.stack:
            return False, False
        return self.stack[-1][1], self.stack[-1][2]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag == "body":
            self.in_body = True
        for attr in I18N_ATTRS:
            if a.get(attr):
                self.keys[attr].add(a[attr])
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if tag == "img" and a.get("src"):
            self.images.append(a["src"])
        covered, skipped = self._state()
        elem_id = a.get("id", "")
        covered = covered or bool(a.get("data-i18n")) or (elem_id in self.dynamic_i18n_ids)
        skipped = skipped or tag in SKIP_TAGS or a.get("translate") == "no" \
            or "notranslate" in a.get("class", "").split()
        if tag not in VOID_TAGS:
            self.stack.append((tag, covered, skipped))

    def handle_endtag(self, tag: str) -> None:
        for idx in range(len(self.stack) - 1, -1, -1):
            if self.stack[idx][0] == tag:
                del self.stack[idx:]
                return

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text or not self.in_body:
            return
        covered, skipped = self._state()
        if covered or skipped or text in BRAND_AND_PROPER_NOUN_ALLOWLIST:
            return
        words = WORD_RE.findall(text)
        german = bool(GERMAN_CHARS.search(text)) or any(w.lower() in GERMAN_WORDS for w in words)
        if german or len(words) >= 2:
            self.untagged.append((self.getpos()[0], text))


def _extract_dynamic_i18n_ids(raw_html: str) -> set[str]:
    """Return element IDs bound to inline bilingual maps (e.g. applyStudioLanguage in ai-auth.html)."""
    if "var studioI18n =" not in raw_html or "function applyStudioLanguage" not in raw_html:
        return set()
    return set(re.findall(r"getElementById\(['\"]([^'\"]+)['\"]\)", raw_html))


def scan_page(path: Path) -> PageScanner:
    raw = path.read_text(encoding="utf-8")
    scanner = PageScanner(dynamic_i18n_ids=_extract_dynamic_i18n_ids(raw))
    scanner.feed(raw)
    return scanner


def is_german(value: str) -> bool:
    plain = re.sub(r"<[^>]+>", " ", value)
    words = [w.lower() for w in WORD_RE.findall(plain)]
    hits = sum(1 for w in words if w in GERMAN_WORDS)
    return bool(GERMAN_CHARS.search(plain)) or hits >= 2


def _has_german_token(text: str) -> bool:
    words = [w.lower() for w in WORD_RE.findall(text)]
    return bool(GERMAN_CHARS.search(text)) or any(w in GERMAN_WORDS for w in words)


def check_i18n(portal: Path, pages: list[Path], problems: list[str]) -> None:
    tr = load_translations(portal / "portal-core.js")
    en_keys = set(tr.get("en", {}).keys())
    de_keys = set(tr.get("de", {}).keys())
    for missing_de in sorted(en_keys - de_keys):
        problems.append(f"portal-core.js: key '{missing_de}' present in 'en' but missing in 'de'")
    for missing_en in sorted(de_keys - en_keys):
        problems.append(f"portal-core.js: key '{missing_en}' present in 'de' but missing in 'en'")
    for key, en_val in sorted(tr.get("en", {}).items()):
        if isinstance(en_val, str) and is_german(en_val):
            problems.append(f"portal-core.js: en['{key}'] contains German text: {en_val[:80]!r}")

    known_de_static = load_static_text_de(portal / "portal.js")
    for val in tr.get("de", {}).values():
        if isinstance(val, str):
            known_de_static.add(" ".join(re.sub(r"<[^>]+>", " ", val).split()))

    strict_data_i18n_pages = {"downloads.html", "downloads/index.html"}

    for page in pages:
        raw = page.read_text(encoding="utf-8")
        has_portal_js = "portal.js" in raw
        scan = scan_page(page)
        rel = page.relative_to(portal).as_posix()
        for attr, keys in scan.keys.items():
            for key in sorted(keys):
                for lang in LANGS:
                    value = tr.get(lang, {}).get(key)
                    if not isinstance(value, str) or not value.strip():
                        problems.append(f"{rel}: {attr}='{key}' missing in '{lang}' dictionary")
                en_val = tr.get("en", {}).get(key)
                if isinstance(en_val, str) and is_german(en_val):
                    problems.append(f"{rel}: en['{key}'] contains German text: {en_val[:80]!r}")
        for line, text in scan.untagged:
            norm = " ".join(text.split())
            if has_portal_js and norm in known_de_static and rel not in strict_data_i18n_pages:
                continue
            if rel in strict_data_i18n_pages or _has_german_token(norm):
                problems.append(f"{rel}:{line}: untranslated hard-coded text: {norm[:120]!r}")


def load_manifest(portal: Path) -> dict:
    manifest_file = portal / "updates" / "version.json"
    root = portal.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from tools.security.release_signer import verify_manifest
    except ImportError as exc:  # pragma: no cover - environment defect
        raise GateError(f"release signer unavailable: {exc}") from exc
    if not verify_manifest(manifest_file):
        raise GateError("signed release manifest portal/updates/version.json is invalid/untrusted")
    return json.loads(manifest_file.read_text(encoding="utf-8"))


def check_downloads(portal: Path, manifest: dict, problems: list[str], *, verify_bytes: bool) -> None:
    from tools.release.verify_portal_bundle import ReleaseGateError, valid_artifact

    page = portal / "downloads.html"
    mirror = portal / "downloads" / "index.html"
    if page.read_bytes() != mirror.read_bytes():
        problems.append("downloads.html and downloads/index.html differ (served /downloads/ would be stale)")
    scan = scan_page(page)
    linked = {href.split("?")[0].split("#")[0].rsplit("/", 1)[-1]
              for href in scan.links if href.startswith("/downloads/")}
    for name in NODEOS_FILES:
        if name not in linked:
            problems.append(f"downloads page does not offer NodeOS artifact {name}")
    by_file = {item.get("filename"): item for item in manifest.get("platforms", {}).values()
               if isinstance(item, dict)}
    for name in sorted(linked - AUX_DOWNLOADS):
        item = by_file.get(name)
        if item is None:
            problems.append(f"/downloads/{name} is linked but not in the signed release manifest")
            continue
        target = portal / "downloads" / name
        if not target.is_file():
            problems.append(f"/downloads/{name} is linked but the artifact file is missing")
            continue
        if verify_bytes:
            try:
                valid_artifact(portal / "downloads", name, item.get("sha256"),
                               item.get("size_bytes"), item.get("url"))
            except ReleaseGateError as exc:
                problems.append(f"/downloads/{name}: {exc}")
        elif target.stat().st_size != item.get("size_bytes"):
            problems.append(f"/downloads/{name}: size differs from signed manifest")
    for src in scan.images:
        if src.startswith("/") and not src.startswith("//"):
            if not (portal / src.lstrip("/").split("?")[0]).is_file():
                problems.append(f"downloads page image missing: {src}")
    android_file = portal / "downloads" / "ComputeMesh-Android.json"
    if android_file.is_file():
        android = json.loads(android_file.read_text(encoding="utf-8"))
        if android.get("version_name", android.get("version")) != manifest.get("version"):
            problems.append("Android metadata version differs from signed manifest version")


def check_versions(portal: Path, manifest: dict, problems: list[str]) -> None:
    tr = load_translations(portal / "portal-core.js")
    want = manifest.get("version")
    for lang in LANGS:
        for key, value in tr.get(lang, {}).items():
            if key.startswith("dl_") and isinstance(value, str):
                for found in VERSION_RE.findall(value):
                    if found != want:
                        problems.append(f"{lang}['{key}'] shows v{found}, signed manifest is v{want}")


def check_freshness(root: Path, manifest: dict, problems: list[str]) -> None:
    released = datetime.fromisoformat(str(manifest.get("release_date")))
    for rel in FRESHNESS_PATHS:
        if not (root / rel).exists():
            continue
        out = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%cI", "--", rel],
                             capture_output=True, text=True, check=False).stdout.strip()
        if out and datetime.fromisoformat(out) > released:
            problems.append(
                f"artifacts stale: '{rel}' changed {out} after release {released.isoformat()} "
                f"({', '.join(FRESHNESS_PLATFORMS)} must be rebuilt, re-signed and re-hashed)"
            )


def run(root: Path, *, publish: bool, verify_bytes: bool) -> tuple[list[str], list[str]]:
    portal = root / "portal"
    pages = sorted(p for p in portal.glob("*.html")) + [portal / "downloads" / "index.html"]
    problems: list[str] = []
    warnings: list[str] = []
    check_i18n(portal, pages, problems)
    manifest = load_manifest(portal)
    check_downloads(portal, manifest, problems, verify_bytes=verify_bytes)
    check_versions(portal, manifest, problems)
    stale: list[str] = []
    check_freshness(root, manifest, stale)
    (problems if publish else warnings).extend(stale)
    return problems, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--publish", action="store_true",
                        help="publication mode: stale binaries are a hard failure")
    parser.add_argument("--skip-hash", action="store_true",
                        help="only compare sizes (never allowed together with --publish)")
    args = parser.parse_args()
    if args.publish and args.skip_hash:
        print("PORTAL_GATE_NO_GO: --skip-hash is not allowed for publication", file=sys.stderr)
        return 2
    try:
        problems, warnings = run(args.repo_root.resolve(), publish=args.publish,
                                 verify_bytes=not args.skip_hash)
    except (GateError, OSError, ValueError) as exc:
        print(f"PORTAL_GATE_NO_GO: {exc}", file=sys.stderr)
        return 2
    for w in warnings:
        print(f"WARN: {w}")
    if problems:
        for p in problems:
            print(f"FAIL: {p}")
        print(f"PORTAL_GATE_NO_GO: {len(problems)} problem(s)", file=sys.stderr)
        return 2
    print("PORTAL_GATE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
