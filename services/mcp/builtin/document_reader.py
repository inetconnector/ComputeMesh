# SPDX-License-Identifier: Apache-2.0
"""Document, Markdown and Log Content Extractor Tool."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


def extract_document_content(
    content_or_path: str,
    max_sections: int = 10,
    extract_bullet_points: bool = True,
) -> Dict[str, Any]:
    """Extracts structured headings, sections, and key takeaways from document text or a local file."""
    raw = str(content_or_path or "").strip()
    if not raw:
        return {"error": "Kein Dokumentinhalt oder Pfad übergeben."}

    # If it's a file path within workspace, read it
    text_content = raw
    is_file = False
    source_file = None
    if len(raw) < 500 and ("\n" not in raw) and (os.path.exists(raw) or os.path.exists(os.path.join(os.getcwd(), raw))):
        p = Path(raw) if os.path.isabs(raw) else Path(os.getcwd()) / raw
        if p.exists() and p.is_file():
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    text_content = f.read(500_000)
                is_file = True
                source_file = str(p.name)
            except Exception:
                pass

    lines = text_content.splitlines()
    total_lines = len(lines)
    word_count = len(text_content.split())

    # Extract Markdown headings (# Title, ## Section)
    sections: List[Dict[str, Any]] = []
    current_heading = "Einleitung / Übersicht"
    current_level = 1
    current_body: List[str] = []

    heading_re = re.compile(r"^(#{1,6})\s+(.+)$")
    for line in lines:
        m = heading_re.match(line)
        if m:
            if current_body:
                sections.append({
                    "heading": current_heading,
                    "level": current_level,
                    "preview": "\n".join(current_body[:8]).strip(),
                    "line_count": len(current_body),
                })
                current_body = []
            current_level = len(m.group(1))
            current_heading = m.group(2).strip()
        else:
            if line.strip():
                current_body.append(line)

    if current_body:
        sections.append({
            "heading": current_heading,
            "level": current_level,
            "preview": "\n".join(current_body[:8]).strip(),
            "line_count": len(current_body),
        })

    # Extract bullet points
    bullets: List[str] = []
    if extract_bullet_points:
        bullet_re = re.compile(r"^\s*[-*•]\s+(.+)$")
        for line in lines:
            m = bullet_re.match(line)
            if m and len(m.group(1).strip()) > 3:
                bullets.append(m.group(1).strip())
                if len(bullets) >= 20:
                    break

    return {
        "status": "success",
        "source": source_file or "direct_text_input",
        "is_file": is_file,
        "total_lines": total_lines,
        "word_count": word_count,
        "total_sections": len(sections),
        "sections": sections[:max(1, min(20, int(max_sections)))],
        "key_bullets": bullets[:10],
    }
