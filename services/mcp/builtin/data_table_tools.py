# SPDX-License-Identifier: Apache-2.0
"""Structured Data, CSV & JSON Tabular Dataset Analyzer Tool."""

from __future__ import annotations

import csv
import io
import json
import math
import statistics
from typing import Any, Dict, List, Optional


def analyze_data_table(
    data: str,
    delimiter: Optional[str] = None,
    max_sample_rows: int = 5,
) -> Dict[str, Any]:
    """Analyzes a CSV string or JSON dataset and computes statistical column summaries."""
    raw = str(data or "").strip()
    if not raw:
        return {"error": "Keine Daten zur Analyse übergeben."}

    rows: List[Dict[str, Any]] = []

    # 1. Try parsing JSON array of objects
    if (raw.startswith("[") and raw.endswith("]")) or (raw.startswith("{") and raw.endswith("}")):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and all(isinstance(item, dict) for item in parsed):
                rows = parsed
            elif isinstance(parsed, dict):
                # Might be {"data": [...]} or dict of columns
                if "data" in parsed and isinstance(parsed["data"], list):
                    rows = [r for r in parsed["data"] if isinstance(r, dict)]
                else:
                    rows = [parsed]
        except Exception:
            pass

    # 2. Try parsing CSV
    if not rows:
        try:
            delim = delimiter or (";" if ";" in raw and "," not in raw else ",")
            reader = csv.DictReader(io.StringIO(raw), delimiter=delim)
            rows = [dict(r) for r in reader if any(v for v in r.values())]
        except Exception as exc:
            return {"error": f"Daten konnten weder als CSV noch als JSON geparst werden: {exc}"}

    if not rows:
        return {"error": "Keine Tabellenzeilen extrahiert."}

    total_rows = len(rows)
    all_columns = list(rows[0].keys())

    column_summaries: Dict[str, Any] = {}
    for col in all_columns:
        vals = [r.get(col) for r in rows if r.get(col) is not None and str(r.get(col)).strip() != ""]
        null_count = total_rows - len(vals)

        # Check numeric conversion
        num_vals: List[float] = []
        for v in vals:
            try:
                num_vals.append(float(str(v).replace(",", ".").replace("%", "").strip()))
            except (ValueError, TypeError):
                break

        is_numeric = len(num_vals) == len(vals) and len(vals) > 0

        if is_numeric and num_vals:
            column_summaries[col] = {
                "type": "numeric",
                "count": len(num_vals),
                "null_count": null_count,
                "min": min(num_vals),
                "max": max(num_vals),
                "mean": round(statistics.mean(num_vals), 4),
                "median": round(statistics.median(num_vals), 4),
                "stddev": round(statistics.stdev(num_vals), 4) if len(num_vals) > 1 else 0.0,
            }
        else:
            str_vals = [str(v).strip() for v in vals]
            distinct_vals = set(str_vals)
            column_summaries[col] = {
                "type": "categorical_or_text",
                "count": len(str_vals),
                "null_count": null_count,
                "distinct_count": len(distinct_vals),
                "top_values": [v for v, _ in collections_counter(str_vals)[:5]],
            }

    sample = rows[:max(1, min(10, int(max_sample_rows)))]

    return {
        "status": "success",
        "total_rows": total_rows,
        "total_columns": len(all_columns),
        "columns": all_columns,
        "column_summaries": column_summaries,
        "sample_preview": sample,
    }


def collections_counter(items: List[str]) -> List[tuple[str, int]]:
    counts: Dict[str, int] = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return sorted(counts.items(), key=lambda x: x[1], reverse=True)
