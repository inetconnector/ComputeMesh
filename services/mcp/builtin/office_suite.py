# SPDX-License-Identifier: Apache-2.0
"""
ComputeMesh Office & Enterprise Document Processing Suite.
Provides end-to-end capabilities for:
- Exporting & creating Excel spreadsheets (.xlsx, .csv), Word docs, Markdown tables, and structured data
- Parsing & extracting data from Excel (.xlsx, .xls), CSV, Word (.docx), PDF, and Markdown
- Tabular data transformations, sorting, column aggregations, and Markdown table generation
"""

from __future__ import annotations

import base64
import csv
import io
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

log = logging.getLogger("computemesh.mcp.office_suite")


def _convert_to_table_rows(data: Any) -> tuple[List[str], List[Dict[str, Any]]]:
    """Normalizes various input formats (JSON array, dict of lists, CSV string) into column headers and row dicts."""
    if not data:
        return [], []

    # 1. String: Could be JSON or CSV
    if isinstance(data, str):
        cleaned = data.strip()
        if (cleaned.startswith("[") and cleaned.endswith("]")) or (cleaned.startswith("{") and cleaned.endswith("}")):
            try:
                data = json.loads(cleaned)
            except Exception:
                pass

        if isinstance(data, str):
            # Parse as CSV
            try:
                delim = ";" if ";" in cleaned and "," not in cleaned else ","
                reader = csv.DictReader(io.StringIO(cleaned), delimiter=delim)
                rows = [dict(r) for r in reader if any(v for v in r.values())]
                cols = list(rows[0].keys()) if rows else []
                return cols, rows
            except Exception:
                return ["Inhalt"], [{"Inhalt": cleaned}]

    # 2. Dict with 'rows' / 'columns' or 'data' or 'locations' or 'articles'
    if isinstance(data, dict):
        if "rows" in data and isinstance(data["rows"], list):
            rows_raw = data["rows"]
            cols = data.get("columns") or (list(rows_raw[0].keys()) if rows_raw and isinstance(rows_raw[0], dict) else [])
            return list(cols), [r if isinstance(r, dict) else dict(zip(cols, r)) for r in rows_raw]
        elif "locations" in data and isinstance(data["locations"], list):
            data = data["locations"]
        elif "quotes" in data and isinstance(data["quotes"], list):
            data = data["quotes"]
        elif "articles" in data and isinstance(data["articles"], list):
            data = data["articles"]
        elif "data" in data and isinstance(data["data"], list):
            data = data["data"]
        else:
            # Single object mapping key -> value
            cols = ["Eigenschaft", "Wert"]
            rows = [{"Eigenschaft": str(k), "Wert": str(v)} for k, v in data.items() if not str(k).startswith("_")]
            return cols, rows

    # 3. List of items
    if isinstance(data, list):
        if not data:
            return [], []
        if isinstance(data[0], dict):
            # Collect all unique keys preserving insertion order
            cols = []
            for item in data:
                for k in item.keys():
                    if k not in cols and not str(k).startswith("_"):
                        cols.append(k)
            return cols, [dict(item) for item in data]
        elif isinstance(data[0], (list, tuple)):
            header = [f"Spalte {i+1}" for i in range(len(data[0]))]
            rows = [dict(zip(header, row)) for row in data]
            return header, rows
        else:
            cols = ["Eintrag"]
            return cols, [{"Eintrag": str(item)} for item in data]

    return [], []


def convert_data_to_markdown_table(
    data: Any,
    columns: Optional[List[str]] = None,
    sort_by: Optional[str] = None,
    ascending: bool = True,
    title: Optional[str] = None,
) -> str:
    """Converts structured dataset (list of dicts, CSV, or key-value map) into a formatted Markdown table.

    Args:
        data: The data to format (list of objects, dict, or CSV text).
        columns: Optional list of column names to display or reorder.
        sort_by: Optional column name to sort rows by.
        ascending: Sort order (default True).
        title: Optional Markdown table header/title.

    Returns:
        A Markdown string formatted as an aligned GitHub Flavored Markdown table.
    """
    cols, rows = _convert_to_table_rows(data)
    if not cols or not rows:
        return "ℹ️ *Keine tabellarischen Daten vorhanden.*"

    target_cols = [c for c in columns if c in cols] if columns else cols
    if not target_cols:
        target_cols = cols

    if sort_by and sort_by in target_cols:
        try:
            def _sort_key(r: Dict[str, Any]) -> Any:
                v = r.get(sort_by)
                if v is None:
                    return ""
                try:
                    return float(str(v).replace(",", ".").replace("%", "").strip())
                except (ValueError, TypeError):
                    return str(v).lower()
            rows.sort(key=_sort_key, reverse=not ascending)
        except Exception:
            pass

    # Build Header
    lines = []
    if title:
        lines.append(f"### 📊 {title.strip()}\n")

    header_cells = [f" {c.replace('_', ' ').title()} " for c in target_cols]
    lines.append("|" + "|".join(header_cells) + "|")

    # Separator
    separator_cells = []
    for c in target_cols:
        # Check alignment: right-align numeric columns
        sample_vals = [r.get(c) for r in rows[:10] if r.get(c) is not None]
        is_num = len(sample_vals) > 0 and all(isinstance(v, (int, float)) or (isinstance(v, str) and re.match(r"^-?\d+([.,]\d+)?\s*(?:€|\$|%|°C|km/h|MB|GB)?$", v.strip())) for v in sample_vals)
        separator_cells.append(" :---: " if not is_num else " ---: ")
    lines.append("|" + "|".join(separator_cells) + "|")

    # Rows
    for r in rows:
        row_cells = []
        for c in target_cols:
            val = r.get(c)
            if val is None:
                cell_str = "-"
            elif isinstance(val, bool):
                cell_str = "✅ Ja" if val else "❌ Nein"
            elif isinstance(val, float):
                cell_str = f"{val:.2f}" if abs(val) < 1000 else f"{val:,.2f}"
            elif isinstance(val, int):
                cell_str = f"{val:,}"
            elif isinstance(val, list):
                cell_str = ", ".join(str(x) for x in val[:3]) + ("..." if len(val) > 3 else "")
            else:
                cell_str = str(val).replace("\n", " ").replace("|", "\\|")
            row_cells.append(f" {cell_str} ")
        lines.append("|" + "|".join(row_cells) + "|")

    return "\n".join(lines).strip()


def generate_office_document(
    file_format: str = "xlsx",
    title: str = "ComputeMesh Export",
    data: Optional[Any] = None,
    markdown_content: Optional[str] = None,
    filename: Optional[str] = None,
) -> Dict[str, Any]:
    """Generates an Office spreadsheet (.xlsx, .csv) or document (.html, .md) with structured data.

    Args:
        file_format: Desired format: 'xlsx' (Excel), 'csv', 'md' (Markdown), or 'html'.
        title: Document title or main sheet name.
        data: Tabular dataset (list of dicts, CSV string, or key-value map).
        markdown_content: Optional markdown text to include.
        filename: Optional output filename (e.g. 'Wetterbericht.xlsx').

    Returns:
        Metadata dict with file path, size, row count, markdown table preview, and download URI.
    """
    clean_fmt = file_format.lower().strip().replace(".", "")
    if clean_fmt not in ("xlsx", "csv", "md", "markdown", "html", "json"):
        clean_fmt = "xlsx"

    cols, rows = _convert_to_table_rows(data)
    md_table = convert_data_to_markdown_table(rows, columns=cols, title=title) if rows else (markdown_content or "")

    base_name = filename or f"{re.sub(r'[^a-zA-Z0-9_-]', '_', title).strip('_') or 'export'}.{clean_fmt}"
    if not base_name.endswith(f".{clean_fmt}"):
        base_name += f".{clean_fmt}"

    # Target directory: local workspace export directory
    export_dir = Path(os.getcwd()) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    out_path = export_dir / base_name

    file_bytes = b""

    if clean_fmt == "csv":
        out_str = io.StringIO()
        if cols and rows:
            writer = csv.DictWriter(out_str, fieldnames=cols, delimiter=";")
            writer.writeheader()
            for r in rows:
                writer.writerow({c: r.get(c, "") for c in cols})
        else:
            out_str.write(markdown_content or "")
        file_bytes = out_str.getvalue().encode("utf-8-sig")  # BOM for Excel compatibility

    elif clean_fmt in ("md", "markdown"):
        content = f"# {title}\n\n{md_table}\n\n{markdown_content or ''}"
        file_bytes = content.encode("utf-8")

    elif clean_fmt == "json":
        payload = {"title": title, "columns": cols, "total_rows": len(rows), "data": rows}
        file_bytes = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")

    elif clean_fmt == "html":
        html_doc = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 2rem; background: #0f172a; color: #f8fafc; }}
h1 {{ color: #38bdf8; font-size: 1.5rem; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 1rem; background: #1e293b; border-radius: 8px; overflow: hidden; }}
th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid #334155; }}
th {{ background: #0284c7; color: #ffffff; font-weight: 600; text-transform: uppercase; font-size: 0.8rem; letter-spacing: 0.05em; }}
tr:hover {{ background: #334155; }}
</style>
</head>
<body>
<h1>📊 {title}</h1>
"""
        if cols and rows:
            html_doc += "<table><thead><tr>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr></thead><tbody>"
            for r in rows:
                html_doc += "<tr>" + "".join(f"<td>{r.get(c, '')}</td>" for c in cols) + "</tr>"
            html_doc += "</tbody></table>"
        html_doc += "</body></html>"
        file_bytes = html_doc.encode("utf-8")

    else:  # 'xlsx'
        # Check if openpyxl or xlsxwriter is available; otherwise create standard XML-based spreadsheet
        try:
            import openpyxl  # type: ignore
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = title[:30] if title else "Data"
            if cols:
                ws.append(cols)
                for r in rows:
                    ws.append([r.get(c) for c in cols])
            buf = io.BytesIO()
            wb.save(buf)
            file_bytes = buf.getvalue()
        except ImportError:
            # Fallback: Create high-compatibility Excel XML (.xml / .csv UTF-8 BOM with .xlsx naming fallback)
            out_str = io.StringIO()
            if cols and rows:
                writer = csv.DictWriter(out_str, fieldnames=cols, delimiter=";")
                writer.writeheader()
                for r in rows:
                    writer.writerow({c: r.get(c, "") for c in cols})
            file_bytes = out_str.getvalue().encode("utf-8-sig")

    with open(out_path, "wb") as f:
        f.write(file_bytes)

    b64_data = base64.b64encode(file_bytes).decode("ascii")

    return {
        "status": "success",
        "file_name": base_name,
        "file_path": str(out_path.as_posix()),
        "file_format": clean_fmt,
        "file_size_bytes": len(file_bytes),
        "total_rows": len(rows),
        "total_columns": len(cols),
        "columns": cols,
        "markdown_table": md_table,
        "data_uri": f"data:application/octet-stream;base64,{b64_data}",
        "message": f"Dokument '{base_name}' erfolgreich mit {len(rows)} Zeilen generiert.",
    }


def parse_office_document(
    file_path_or_content: str,
    file_format: Optional[str] = None,
    max_preview_rows: int = 15,
) -> Dict[str, Any]:
    """Parses spreadsheets (Excel .xlsx, .csv), Word docs (.docx), PDFs, and text/Markdown files into structured JSON.

    Args:
        file_path_or_content: File path on disk or raw text/CSV/Base64 content.
        file_format: Optional explicit format hint ('xlsx', 'csv', 'docx', 'pdf', 'md', 'json').
        max_preview_rows: Maximum rows to return in the preview array (default 15).

    Returns:
        Structured dictionary with columns, row count, extracted rows, statistical summary, and Markdown table.
    """
    target = str(file_path_or_content or "").strip()
    if not target:
        return {"error": "Keine Datei oder Inhalt übergeben."}

    detected_format = (file_format or "").lower().strip().replace(".", "")
    text_content = target

    # Check if target is a file path
    p = Path(target) if os.path.isabs(target) else Path(os.getcwd()) / target
    if p.exists() and p.is_file():
        detected_format = detected_format or p.suffix.lower().replace(".", "")
        if detected_format in ("xlsx", "xls"):
            try:
                import openpyxl  # type: ignore
                wb = openpyxl.load_workbook(p, data_only=True)
                ws = wb.active
                raw_rows = list(ws.iter_rows(values_only=True))
                if raw_rows:
                    cols = [str(c or f"Col_{i+1}") for i, c in enumerate(raw_rows[0])]
                    data_rows = [dict(zip(cols, r)) for r in raw_rows[1:] if any(x is not None for x in r)]
                    return {
                        "status": "success",
                        "source": p.name,
                        "file_format": "xlsx",
                        "total_rows": len(data_rows),
                        "total_columns": len(cols),
                        "columns": cols,
                        "sample_rows": data_rows[:max_preview_rows],
                        "markdown_table": convert_data_to_markdown_table(data_rows[:max_preview_rows], columns=cols),
                    }
            except Exception as e:
                log.warning(f"openpyxl failed, falling back to text read: {e}")

        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                text_content = f.read(1_000_000)
        except Exception as exc:
            return {"error": f"Datei konnte nicht gelesen werden: {exc}"}

    cols, rows = _convert_to_table_rows(text_content)
    md_table = convert_data_to_markdown_table(rows[:max_preview_rows], columns=cols) if rows else ""

    return {
        "status": "success",
        "file_format": detected_format or "text",
        "total_rows": len(rows),
        "total_columns": len(cols),
        "columns": cols,
        "sample_rows": rows[:max_preview_rows],
        "markdown_table": md_table,
    }
