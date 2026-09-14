# SPDX-License-Identifier: Apache-2.0
"""Multi-format Document Parser for ComputeMesh RAG."""

from __future__ import annotations

import csv
import io
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("computemesh.rag.parser")


def extract_text_from_file(file_path: str | Path) -> Dict[str, Any]:
    """Extracts plain text and structured metadata from a file on disk.

    Supports PDF, DOCX, TXT, Markdown, CSV, JSON, and source code files.
    """
    path = Path(file_path)
    if not path.is_file():
        return {"error": f"Datei '{file_path}' nicht gefunden.", "text": "", "metadata": {}}
    ext = path.suffix.lower()
    file_name = path.name
    size_bytes = path.stat().st_size

    try:
        if ext in (".txt", ".md", ".markdown", ".rst", ".log", ".py", ".js", ".ts", ".html", ".css", ".json", ".yaml", ".yml", ".sh", ".bat", ".sql", ".rs", ".go", ".c", ".cpp", ".h", ".hpp", ".kt", ".java"):
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return {
                "file_name": file_name,
                "file_path": str(path.resolve()),
                "extension": ext,
                "size_bytes": size_bytes,
                "text": content,
                "metadata": {"type": "plain_text", "lines": len(content.splitlines())},
            }

        elif ext == ".csv":
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.reader(f)
                rows = list(reader)
            text_lines = [", ".join(row) for row in rows[:5000]]
            return {
                "file_name": file_name,
                "file_path": str(path.resolve()),
                "extension": ext,
                "size_bytes": size_bytes,
                "text": "\n".join(text_lines),
                "metadata": {"type": "csv", "rows": len(rows), "columns": len(rows[0]) if rows else 0},
            }

        elif ext == ".pdf":
            # Try pypdf / pdfplumber if available, otherwise extract readable text blocks
            try:
                import pypdf
                reader = pypdf.PdfReader(str(path))
                pages_text = []
                for idx, page in enumerate(reader.pages):
                    ptxt = page.extract_text() or ""
                    if ptxt.strip():
                        pages_text.append(f"--- [Seite {idx+1}] ---\n{ptxt.strip()}")
                full_text = "\n\n".join(pages_text)
                return {
                    "file_name": file_name,
                    "file_path": str(path.resolve()),
                    "extension": ext,
                    "size_bytes": size_bytes,
                    "text": full_text,
                    "metadata": {"type": "pdf", "pages": len(reader.pages)},
                }
            except Exception:
                # Fallback: simple binary text extraction
                with open(path, "rb") as f:
                    raw_data = f.read()
                # Basic ASCII/UTF-8 string filter
                clean_chars = "".join(chr(b) if (32 <= b <= 126 or b in (10, 13)) else " " for b in raw_data)
                clean_text = " ".join(clean_chars.split())
                return {
                    "file_name": file_name,
                    "file_path": str(path.resolve()),
                    "extension": ext,
                    "size_bytes": size_bytes,
                    "text": clean_text[:50000],
                    "metadata": {"type": "pdf_raw"},
                }

        elif ext in (".docx", ".doc"):
            try:
                import docx
                doc = docx.Document(str(path))
                paras = [p.text for p in doc.paragraphs if p.text.strip()]
                return {
                    "file_name": file_name,
                    "file_path": str(path.resolve()),
                    "extension": ext,
                    "size_bytes": size_bytes,
                    "text": "\n\n".join(paras),
                    "metadata": {"type": "docx", "paragraphs": len(paras)},
                }
            except Exception:
                pass

        # Fallback binary text read
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        return {
            "file_name": file_name,
            "file_path": str(path.resolve()),
            "extension": ext,
            "size_bytes": size_bytes,
            "text": content,
            "metadata": {"type": "fallback_text"},
        }

    except Exception as exc:
        return {
            "error": f"Fehler beim Einlesen von '{file_name}': {exc}",
            "file_name": file_name,
            "text": "",
            "metadata": {},
        }


def parse_document_content(content: str, filename: str = "document.txt") -> Dict[str, Any]:
    """Parses raw text or string content into a document representation."""
    return {
        "file_name": filename,
        "file_path": filename,
        "extension": Path(filename).suffix.lower() or ".txt",
        "size_bytes": len(content.encode("utf-8")),
        "text": content,
        "metadata": {"type": "direct_text", "lines": len(content.splitlines())},
    }


# Alias for backward/forward compatibility
parse_document_text = parse_document_content

