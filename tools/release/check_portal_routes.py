#!/usr/bin/env python3
"""Offline ComputeMesh portal navigation, routes and download-link gate.

Scans all first-party HTML pages, including their declared JS bundles.
External URLs are reported (not incorrectly claimed to be reachable).
Routes reflect Apache clean-URL rewrites and explicit download aliases.
"""
from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit, unquote

CALL = re.compile(r"(?<![\w.$])([A-Za-z_$][\w$]*)\s*\(")
DECLARE = re.compile(
    r"(?:\bfunction\s+|\b(?:const|let|var)\s+|\bwindow\.)"
    r"([A-Za-z_$][\w$]*)\s*(?:\(|=)"
)
BUILTINS = {
    "if", "else", "return", "event", "String", "Number", "Boolean", "parseInt",
    "parseFloat", "setTimeout", "setInterval", "confirm", "alert", "prompt",
    "encodeURIComponent", "decodeURIComponent", "preventDefault", "stopPropagation",
}
DOWNLOAD_ALIASES = {"/downloads": "/downloads.html", "/models": "/models.html"}


class Index(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.scripts: list[str] = []
        self.handlers: list[str] = []
        self.ids: list[str] = []
        self.inline_script: list[str] = []
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(values["id"])
        for attribute in ("href", "src"):
            link = values.get(attribute)
            if isinstance(link, str):
                self.links.append((attribute, link))
        if tag == "script":
            self._in_script = not bool(values.get("src"))
            if values.get("src"):
                self.scripts.append(values["src"])
        for key, value in attrs:
            if key.startswith("on") and isinstance(value, str):
                self.handlers.extend(CALL.findall(value))

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False

    def handle_data(self, data):
        if self._in_script:
            self.inline_script.append(data)


def local_path(root: Path, current: Path, url: str) -> Path | None:
    link = url.strip()
    if not link or link.startswith("#") or link.startswith("//"):
        return None
    parsed = urlsplit(link)
    if parsed.scheme or parsed.netloc:
        return None
    if not parsed.path or any(c in parsed.path for c in ("{", "}", "$")):
        return None
    route = unquote(parsed.path)
    if "\\" in route or "\x00" in route:
        raise ValueError("unsafe path")
    if route.startswith("/"):
        candidate = root / route.lstrip("/")
    else:
        candidate = current.parent / route
    candidate = candidate.resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError("link escapes portal root")
    return candidate


def route_exists(root: Path, target: Path, artifact_dir: Path | None) -> bool:
    if target.is_file() or (target / "index.html").is_file():
        return True
    rel = "/" + target.relative_to(root).as_posix()
    alias = DOWNLOAD_ALIASES.get(rel.rstrip("/"))
    if alias and (root / alias.lstrip("/")).is_file():
        return True
    if target.suffix == "" and target.with_suffix(".html").is_file():
        return True
    if rel.startswith("/downloads/") and artifact_dir is not None:
        filename = target.name
        if re.fullmatch(r"[a-zA-Z0-9_.-]{2,130}", filename):
            return (artifact_dir / filename).is_file()
    return False


def audit(root: Path, artifact_dir: Path | None = None) -> dict:
    if not root.is_dir():
        raise ValueError("portal directory missing")
    problems: list[dict[str, str]] = []
    count = 0
    external: set[str] = set()
    for html in sorted(root.rglob("*.html")):
        # A generated web-app bundle has its own routing/build pipeline.
        if "webui" in html.relative_to(root).parts:
            continue
        parser = Index()
        parser.feed(html.read_text(encoding="utf-8"))
        count += 1
        source = html.relative_to(root).as_posix()
        duplicates = {i for i in parser.ids if parser.ids.count(i) > 1}
        for id_ in sorted(duplicates):
            problems.append({"source": source, "type": "duplicate_id", "detail": id_})
        scripts = list(parser.inline_script)
        for script in parser.scripts:
            try:
                target = local_path(root, html, script)
            except ValueError:
                problems.append({"source": source, "type": "bad_script_src", "detail": script})
                continue
            if target and target.is_file() and target.suffix == ".js":
                scripts.append(target.read_text(encoding="utf-8"))
        # Portal runtime can inject portal-core.js dynamically via portal.js.
        if any("portal.js" in script for script in parser.scripts):
            core = root / "portal-core.js"
            if core.is_file():
                scripts.append(core.read_text(encoding="utf-8"))
        declarations = set()
        for script in scripts:
            declarations.update(DECLARE.findall(script))
        for handler in sorted(set(parser.handlers)):
            if handler not in declarations and handler not in BUILTINS:
                problems.append({"source": source, "type": "missing_js_handler", "detail": handler})
        for attr, url in parser.links:
            if url.strip().startswith(("https://", "http://")):
                external.add(urlsplit(url).netloc)
                continue
            try:
                target = local_path(root, html, url)
            except ValueError:
                problems.append({"source": source, "type": "unsafe_link", "detail": url})
                continue
            if target and not route_exists(root, target, artifact_dir):
                problems.append({"source": source, "type": f"missing_{attr}", "detail": url})
    return {"checked_pages": count, "issue_count": len(problems),
            "issues": problems, "external_domains_unverified": sorted(external)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--portal", type=Path, default=Path(__file__).resolve().parents[2] / "portal")
    parser.add_argument("--artifacts-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.portal.resolve(), args.artifacts_dir.resolve() if args.artifacts_dir else None)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"checked_pages": result["checked_pages"],
                      "issue_count": result["issue_count"],
                      "external_domains_unverified": len(result["external_domains_unverified"])},
                     sort_keys=True))
    for issue in result["issues"][:60]:
        print(f"{issue['source']}: {issue['type']}: {issue['detail']}", file=sys.stderr)
    return 0 if not result["issues"] and result["checked_pages"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
