# SPDX-License-Identifier: Apache-2.0
"""Generic Archive & Structured Data Transformation Tool Suite for ComputeMesh MCP."""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
import tarfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional


def unpack_archive(
    archive_path: str,
    extract_to: Optional[str] = None,
    list_only: bool = False,
    workspace_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Unpacks ZIP, TAR, TAR.GZ, TAR.BZ2, or GEDZIP archives, inventorying all files and formats."""
    root = os.path.abspath(workspace_root or ".")
    abs_archive = os.path.abspath(os.path.join(root, archive_path)) if not os.path.isabs(archive_path) else archive_path
    
    if not os.path.exists(abs_archive):
        return {"error": f"Archivdatei '{archive_path}' existiert nicht.", "success": False}
        
    target_dir = os.path.abspath(os.path.join(root, extract_to)) if extract_to else os.path.splitext(abs_archive)[0]
    
    inventory: List[Dict[str, Any]] = []
    total_size = 0
    
    try:
        if zipfile.is_zipfile(abs_archive) or abs_archive.lower().endswith((".zip", ".gedzip")):
            with zipfile.ZipFile(abs_archive, "r") as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    ext = os.path.splitext(info.filename)[1].lower()
                    inventory.append({
                        "filename": info.filename,
                        "size_bytes": info.file_size,
                        "extension": ext,
                        "compressed_size": info.compress_size,
                    })
                    total_size += info.file_size
                if not list_only:
                    os.makedirs(target_dir, exist_ok=True)
                    zf.extractall(target_dir)
        elif tarfile.is_tarfile(abs_archive) or abs_archive.lower().endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2")):
            with tarfile.open(abs_archive, "r:*") as tf:
                for member in tf.getmembers():
                    if member.isdir():
                        continue
                    ext = os.path.splitext(member.name)[1].lower()
                    inventory.append({
                        "filename": member.name,
                        "size_bytes": member.size,
                        "extension": ext,
                    })
                    total_size += member.size
                if not list_only:
                    os.makedirs(target_dir, exist_ok=True)
                    tf.extractall(target_dir)
        else:
            return {"error": f"Nicht unterstütztes Archivformat für '{archive_path}'.", "success": False}
    except Exception as e:
        return {"error": f"Fehler beim Entpacken von '{archive_path}': {str(e)}", "success": False}
        
    return {
        "success": True,
        "archive_path": os.path.relpath(abs_archive, root),
        "extracted_to": os.path.relpath(target_dir, root) if not list_only else None,
        "total_files": len(inventory),
        "total_uncompressed_bytes": total_size,
        "inventory": inventory,
    }


def create_archive(
    output_path: str,
    input_paths: List[str],
    archive_type: str = "zip",
    workspace_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Packs files or directories into a ZIP, GEDZIP, or TAR.GZ archive."""
    root = os.path.abspath(workspace_root or ".")
    abs_output = os.path.abspath(os.path.join(root, output_path)) if not os.path.isabs(output_path) else output_path
    os.makedirs(os.path.dirname(abs_output), exist_ok=True)
    
    arch_type = str(archive_type or "zip").lower()
    packed_count = 0
    
    try:
        if arch_type in ("zip", "gedzip"):
            with zipfile.ZipFile(abs_output, "w", zipfile.ZIP_DEFLATED) as zf:
                for inp in input_paths:
                    abs_inp = os.path.abspath(os.path.join(root, inp)) if not os.path.isabs(inp) else inp
                    if os.path.isdir(abs_inp):
                        for dirpath, _, filenames in os.walk(abs_inp):
                            for fn in filenames:
                                fpath = os.path.join(dirpath, fn)
                                arcname = os.path.relpath(fpath, os.path.dirname(abs_inp))
                                zf.write(fpath, arcname)
                                packed_count += 1
                    elif os.path.isfile(abs_inp):
                        zf.write(abs_inp, os.path.basename(abs_inp))
                        packed_count += 1
        elif arch_type in ("tar", "tar.gz", "tgz"):
            mode = "w:gz" if "gz" in arch_type or arch_type == "tgz" else "w"
            with tarfile.open(abs_output, mode) as tf:
                for inp in input_paths:
                    abs_inp = os.path.abspath(os.path.join(root, inp)) if not os.path.isabs(inp) else inp
                    if os.path.exists(abs_inp):
                        tf.add(abs_inp, arcname=os.path.basename(abs_inp))
                        packed_count += 1
        else:
            return {"error": f"Nicht unterstützter Archivtyp '{archive_type}'.", "success": False}
    except Exception as e:
        return {"error": f"Fehler beim Erstellen des Archivs '{output_path}': {str(e)}", "success": False}
        
    return {
        "success": True,
        "output_path": os.path.relpath(abs_output, root),
        "archive_size_bytes": os.path.getsize(abs_output),
        "total_items_packed": packed_count,
    }


def convert_structured_data(
    source_path: str,
    target_format: str = "json",
    output_path: Optional[str] = None,
    workspace_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Converts structured data between CSV, TSV, JSON, Markdown tables, and text lines."""
    root = os.path.abspath(workspace_root or ".")
    abs_source = os.path.abspath(os.path.join(root, source_path)) if not os.path.isabs(source_path) else source_path
    
    if not os.path.exists(abs_source):
        return {"error": f"Quelldatei '{source_path}' nicht gefunden.", "success": False}
        
    fmt = str(target_format or "json").lower()
    
    try:
        with open(abs_source, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
            
        rows: List[Dict[str, Any]] = []
        # Detect source format
        if abs_source.endswith(".json"):
            loaded = json.loads(content)
            rows = loaded if isinstance(loaded, list) else [loaded]
        elif abs_source.endswith((".csv", ".tsv")):
            delimiter = "\t" if abs_source.endswith(".tsv") else ","
            reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
            rows = list(reader)
        else:
            # Simple line parsing
            rows = [{"line_number": i + 1, "text": line} for i, line in enumerate(content.splitlines()) if line.strip()]
            
        target_content = ""
        if fmt == "json":
            target_content = json.dumps(rows, indent=2, ensure_ascii=False)
        elif fmt in ("csv", "tsv"):
            if rows and isinstance(rows[0], dict):
                fieldnames = list(rows[0].keys())
                out_io = io.StringIO()
                delim = "\t" if fmt == "tsv" else ","
                writer = csv.DictWriter(out_io, fieldnames=fieldnames, delimiter=delim)
                writer.writeheader()
                writer.writerows(rows)
                target_content = out_io.getvalue()
        elif fmt in ("markdown", "md"):
            if rows and isinstance(rows[0], dict):
                keys = list(rows[0].keys())
                header = "| " + " | ".join(keys) + " |"
                separator = "| " + " | ".join(["---"] * len(keys)) + " |"
                md_lines = [header, separator]
                for r in rows:
                    md_lines.append("| " + " | ".join(str(r.get(k, "")) for k in keys) + " |")
                target_content = "\n".join(md_lines)
        else:
            return {"error": f"Nicht unterstütztes Zielformat '{target_format}'.", "success": False}
            
        if output_path:
            abs_target = os.path.abspath(os.path.join(root, output_path)) if not os.path.isabs(output_path) else output_path
            os.makedirs(os.path.dirname(abs_target), exist_ok=True)
            with open(abs_target, "w", encoding="utf-8") as f:
                f.write(target_content)
            return {
                "success": True,
                "output_path": os.path.relpath(abs_target, root),
                "total_records": len(rows),
                "target_format": fmt,
            }
            
        return {
            "success": True,
            "total_records": len(rows),
            "target_format": fmt,
            "content_preview": target_content[:3000],
        }
    except Exception as e:
        return {"error": f"Fehler bei der Datenkonvertierung: {str(e)}", "success": False}
