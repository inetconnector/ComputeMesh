# SPDX-License-Identifier: Apache-2.0
"""High-density UI and Markdown formatters for ComputeMesh MCP tool outputs."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .reasoning_formatter import format_reasoning_and_thinking_blocks

def format_tool_content_if_json(content: str) -> str:
    """Format a few common raw JSON tool responses for direct user display."""
    content = format_reasoning_and_thinking_blocks(content)
    cleaned = str(content or "").strip()
    if not (cleaned.startswith("{") and cleaned.endswith("}")):
        return str(content or "")
    try:
        data = json.loads(cleaned)
        if "multiple_locations" in data and "locations" in data:
            locs = data.get("locations", [])
            lines = [
                "### 🌤️ **Wetter-Vergleich**\n",
                "| 📍 Ort | 🌡️ Temperatur | 🌡️ Gefühlt | ☁️ Zustand | 💧 Feuchtigkeit | 💨 Wind |",
                "| :--- | :---: | :---: | :--- | :---: | :---: |",
            ]
            for loc in locs:
                name = loc.get("location", "Ort")
                country = loc.get("country", "")
                name_str = f"**{name}**" + (f" *({country})*" if country and country != "Deutschland" else "")
                temp = f"{loc.get('temperature_celsius', '-')} °C"
                app_temp = f"{loc.get('apparent_temperature_celsius', '-')} °C"
                cond = loc.get("condition", "-")
                hum = f"{loc.get('humidity_percent', '-')} %"
                wind = f"{loc.get('wind_speed_kmh', '-')} km/h"
                lines.append(f"| {name_str} | {temp} | {app_temp} | {cond} | {hum} | {wind} |")
            return "\n".join(lines).strip()

        if "temperature_celsius" in data and ("location" in data or "city" in data):
            name = data.get("location") or data.get("city") or "Ort"
            country = data.get("country", "")
            name_str = f"**{name}**" + (f" *({country})*" if country else "")
            temp = data.get("temperature_celsius", "-")
            app_temp = data.get("apparent_temperature_celsius", "-")
            cond = data.get("condition", "-")
            hum = data.get("humidity_percent", "-")
            wind = data.get("wind_speed_kmh", "-")
            res = (
                f"### 🌤️ **Aktuelles Wetter für {name_str}**\n\n"
                f"| Metrik | Wert |\n"
                f"| :--- | :--- |\n"
                f"| **🌡️ Temperatur** | `{temp} °C` (Gefühlt: `{app_temp} °C`) |\n"
                f"| **☁️ Wetterlage** | `{cond}` |\n"
                f"| **💧 Luftfeuchtigkeit** | `{hum} %` |\n"
                f"| **💨 Windgeschwindigkeit** | `{wind} km/h` |\n"
                f"| **📡 Datenquelle** | `{data.get('source', 'Open-Meteo')}` |"
            )
            return res.strip()

        if "multiple_quotes" in data and "quotes" in data:
            quotes = data.get("quotes", [])
            lines = [
                "### 📈 **Finanz- & Krypto-Marktübersicht**\n",
                "| 🪙 Asset / Ticker | 💵 Kurs | 📊 24h Änderung | 📈 24h Hoch | 📉 24h Tief |",
                "| :--- | :---: | :---: | :---: | :---: |",
            ]
            for q in quotes:
                sym = q.get("symbol", "-")
                pr = q.get("price", "-")
                curr = q.get("currency", "USD")
                chg = q.get("change_percent_24h")
                chg_str = f"+{chg:.2f}%" if isinstance(chg, (int, float)) and chg > 0 else (f"{chg:.2f}%" if isinstance(chg, (int, float)) else "-")
                icon = "🟢" if isinstance(chg, (int, float)) and chg >= 0 else "🔴"
                h24 = q.get("high_24h", "-")
                l24 = q.get("low_24h", "-")
                lines.append(f"| **{sym}** | `{pr} {curr}` | {icon} `{chg_str}` | `{h24}` | `{l24}` |")
            return "\n".join(lines).strip()

        if "file_name" in data and "data_uri" in data and "markdown_table" in data:
            f_name = data.get("file_name", "Dokument")
            f_fmt = str(data.get("file_format", "xlsx")).upper()
            rows_cnt = data.get("total_rows", 0)
            md_tbl = data.get("markdown_table", "")
            d_uri = data.get("data_uri", "")
            res = f"### 📊 **Office-Export: `{f_name}`** ({f_fmt}, {rows_cnt} Zeilen)\n\n"
            if md_tbl:
                res += f"{md_tbl}\n\n"
            res += f"[⬇️ **Datei herunterladen (`{f_name}`)**]({d_uri})"
            return res.strip()

        if "_dynamic_meta" in data:
            meta = data["_dynamic_meta"]
            t_name = meta.get("tool_name", "dynamic_tool")
            t_sha = meta.get("sha256", "")[:12]
            t_sec = meta.get("execution_time_seconds", 0.0)
            status = meta.get("status", "verified_safe")
            badge = "🛡️ **Zero-Trust Sandbox (Verifiziert)**" if status == "verified_safe" else "⚠️ **Sandbox Reject**"
            res_parts = [f"### ⚡ Autonomes Dynamic Tool: `{t_name}` ({badge}, {t_sec}s, SHA: `{t_sha}`)"]
            for k, v in data.items():
                if k.startswith("_"):
                    continue
                if isinstance(v, (dict, list)):
                    res_parts.append(f"**{k}:**\n```json\n{json.dumps(v, indent=2, ensure_ascii=False)}\n```")
                else:
                    res_parts.append(f"- **{k}:** `{v}`")
            return "\n\n".join(res_parts).strip()

        if "block_height" in data and "is_chain_valid" in data:
            height = data.get("block_height", 0)
            t_blocks = data.get("total_blocks", 0)
            t_receipts = data.get("total_receipts", 0)
            is_valid = data.get("is_chain_valid", True)
            db_size = data.get("db_size_kb", 0.0)
            badge = "🟢 **Kryptografisch Verifiziert (100% Intakt)**" if is_valid else "🔴 **Integritätsfehler!**"
            res = (
                f"### ⛓️ **ComputeMesh Proof-of-Execution Blockchain**\n\n"
                f"- **Kettenstatus:** {badge}\n"
                f"- **Aktuelle Block-Höhe:** `#{height}` ({t_blocks} Blöcke gesamt)\n"
                f"- **Verifizierte PoE-Receipts:** `{t_receipts:,}` Transaktionen\n"
                f"- **Ausstehende Batches:** `{data.get('pending_receipts', 0)}` Receipts\n"
                f"- **Ledger-Speichergröße:** `{db_size} KB` *(Ultra-Compact)*\n"
            )
            return res.strip()

        if "receipt_id" in data and ("merkle_verified" in data or "is_confirmed" in data):
            rid = data.get("receipt_id", "")
            confirmed = data.get("is_confirmed", False)
            verified = data.get("merkle_verified", False)
            b_idx = data.get("block_index")
            t_name = data.get("tool_name", "")
            sec = data.get("elapsed_seconds", 0.0)
            node = data.get("node_id", "")
            badge = "🔒 **Mathematisch Bewiesen (Merkle-Proof Gültig)**" if verified else ("🟡 **Block Bestätigt**" if confirmed else "⏳ **Ausstehend im Batch**")
            res = (
                f"### 📜 **Proof-of-Execution Receipt:** `{rid}`\n\n"
                f"- **Integritätsstatus:** {badge}\n"
                f"- **Ausgeführtes Tool:** `{t_name}`\n"
                f"- **Verankerter Block:** `#{b_idx}`\n"
                f"- **Ausführender Node:** `{node}`\n"
                f"- **Ausführungsdauer:** `{sec}s`\n"
            )
            return res.strip()

        if "command" in data and "exit_code" in data and ("stdout" in data or "stderr" in data):
            cmd = data.get("command", "")
            code = data.get("exit_code", 0)
            elapsed = data.get("elapsed_seconds", 0)
            stdout = data.get("stdout", "").strip()
            stderr = data.get("stderr", "").strip()
            badge = "✅ **Erfolgreich (Code 0)**" if code == 0 else f"❌ **Fehlgeschlagen (Code {code})**"
            res = f"### 💻 Terminal Befehl: `{cmd}` ({badge}, {elapsed}s)\n\n"
            if stdout:
                res += f"```text\n{stdout}\n```\n\n"
            if stderr:
                res += f"**Stderr:**\n```text\n{stderr}\n```\n\n"
            if not stdout and not stderr:
                res += "*Keine Textausgabe.*\n"
            return res.strip()

        if "stdout" in data or "images" in data or ("status" in data and ("stdout" in data or "result" in data)):
            res_parts = []
            res_parts.append("### 🐍 Code Interpreter / Python Sandbox")
            if data.get("stdout"):
                res_parts.append(f"**Standard-Ausgabe (stdout):**\n```text\n{data['stdout'].strip()}\n```")
            if data.get("stderr"):
                res_parts.append(f"**Fehlerausgabe (stderr):**\n```text\n{data['stderr'].strip()}\n```")
            if data.get("result") is not None and str(data.get("result")) != "None":
                res_parts.append(f"**Ergebnis:** `{data['result']}`")
            for img_b64 in data.get("images", []):
                res_parts.append(f"![Generierte Grafik](data:image/png;base64,{img_b64})")
            if data.get("error"):
                res_parts.append(f"❌ **Fehler:** `{data['error']}`")
            return "\n\n".join(res_parts).strip()

        if "total_matches" in data or (isinstance(data.get("matches"), list) and data["matches"] and "line_number" in data["matches"][0]):
            q = data.get("query", "")
            tot = data.get("total_matches", len(data.get("matches", [])))
            matches = data.get("matches", [])
            if not matches:
                return f"ℹ️ Keine Treffer für **'{q}'** im Projekt gefunden."
            res = f"### 🔍 Code-Suchergebnisse für *'{q}'* ({tot} Treffer)\n\n"
            for m in matches[:15]:
                f = m.get("file", "")
                l_num = m.get("line_number", 0)
                l_code = m.get("line_content", "").strip()
                res += f"- 📄 **`{f}:{l_num}`**\n  ```text\n  {l_code}\n  ```\n"
            if len(matches) > 15:
                res += f"\n*... und {len(matches) - 15} weitere Fundstellen.*"
            return res.strip()

        if "matches" in data and isinstance(data.get("matches"), list):
            q = data.get("query", "Vector Store")
            matches = data.get("matches", [])
            if not matches:
                return f"Keine passenden Passagen für **'{q}'** in der Wissensbasis gefunden."
            res = f"### 📚 Relevante Auszüge aus der Wissensbasis für *'{q}'*:\n\n"
            for idx, m in enumerate(matches, 1):
                doc = m.get("document", "Dokument")
                score = float(m.get("score", 0.0))
                chunk_id = m.get("chunk_id", 0)
                text_content = str(m.get("text", "")).strip()
                res += f"#### {idx}. 📄 `{doc}` (Abschnitt {chunk_id}, Relevanz: {score:.1%})\n"
                res += f"> {text_content}\n\n"
            return res.strip()

        if "indexed_chunks" in data and "document_id" in data:
            doc_id = data.get("document_id", "")
            cnt = data.get("indexed_chunks", 0)
            return f"✅ **Dokument erfolgreich indexiert:** `{doc_id}` ({cnt} semantische Vektor-Chunks gespeichert)."

        if "documents" in data and isinstance(data.get("documents"), list):
            docs = data.get("documents", [])
            if not docs:
                return "ℹ️ Es sind aktuell noch keine Dokumente in der Vektordatenbank indexiert."
            res = f"### 🗄️ Indexierte Dokumente in der Wissensbasis ({len(docs)} gesamt):\n\n"
            for d in docs:
                doc_id = d.get("document_id", "")
                chunks = d.get("total_chunks", 0)
                created = d.get("indexed_at", "")
                res += f"- 📄 **`{doc_id}`** ({chunks} Chunks, hinzugefügt: {created})\n"
            return res.strip()

        if "profile" in data and "updated" in data:
            return f"✅ **Benutzerprofil aktualisiert:** Präferenzen und Fakten wurden dauerhaft im Langzeitgedächtnis gespeichert."

        if "profile" in data and isinstance(data.get("profile"), dict):
            prof = data["profile"]
            res = "### 🧠 Gespeichertes Benutzerprofil (Langzeitgedächtnis)\n\n"
            if prof.get("name"):
                res += f"- **Benutzer:** {prof.get('name')}\n"
            if prof.get("preferred_language"):
                res += f"- **Bevorzugte Sprache:** {prof.get('preferred_language')}\n"
            prefs = prof.get("preferences", [])
            if prefs:
                res += "- **Gespeicherte Präferenzen:**\n"
                for p in prefs:
                    res += f"  - {p}\n"
            facts = prof.get("facts", [])
            if facts:
                res += "- **Bekannte Fakten & Kontext:**\n"
                for f in facts:
                    res += f"  - {f}\n"
            return res.strip()

        if "gpu_count" in data and "devices" in data:
            cnt = data.get("gpu_count", 0)
            devs = data.get("devices", [])
            if not devs:
                return "ℹ️ Keine dedizierten NVIDIA CUDA oder AMD ROCm GPUs auf diesem System erkannt."
            res = f"### ⚡ GPU-Hardware-Telemetrie ({cnt} Einheit{'en' if cnt > 1 else ''})\n\n"
            for d in devs:
                name = d.get("name", "GPU")
                tot = d.get("vram_total_mb", 0)
                used = d.get("vram_used_mb", 0)
                free = d.get("vram_free_mb", 0)
                util = d.get("compute_utilization_percent", 0)
                pct = d.get("vram_usage_percent", 0)
                temp = d.get("temperature_celsius")
                res += f"#### 🎮 `{name}`\n"
                res += f"- **VRAM-Auslastung:** {used:,.0f} MB / {tot:,.0f} MB ({pct:.1f}% belegt, {free:,.0f} MB frei)\n"
                res += f"- **Compute-Auslastung:** {util} %\n"
                if temp is not None:
                    res += f"- **GPU-Temperatur:** {temp} °C\n"
                res += "\n"
            return res.strip()

        if "disk_total_gb" in data or "ram_total_gb" in data:
            os_name = data.get("os", "System")
            cpu_cnt = data.get("cpu_count", "N/A")
            res = f"### 🖥️ System-Status & Hardware-Ressourcen ({os_name})\n\n"
            res += f"- **CPU-Kerne:** {cpu_cnt}\n"
            if "ram_total_gb" in data:
                res += f"- **Arbeitsspeicher (RAM):** {data.get('ram_used_gb', 0)} GB / {data.get('ram_total_gb', 0)} GB ({data.get('ram_usage_percent', 0)}% belegt)\n"
            if "disk_total_gb" in data:
                res += f"- **Festplatte (Disk):** {data.get('disk_free_gb', 0)} GB frei von {data.get('disk_total_gb', 0)} GB ({data.get('disk_usage_percent', 0)}% belegt)\n"
            if "python_version" in data:
                res += f"- **Python:** {data.get('python_version')}\n"
            return res.strip()

        if "total_entries" in data and "entries" in data and isinstance(data.get("entries"), list):
            rel_p = data.get("relative_path", ".")
            tot = data.get("total_entries", 0)
            entries = data.get("entries", [])
            res = f"### 📂 Dateien im Workspace (`{rel_p}`, {tot} Einträge)\n\n"
            for e in entries[:25]:
                t = e.get("type", "file")
                icon = "📁" if t == "directory" else "📄"
                p = e.get("path", "")
                sz = e.get("size_bytes")
                sz_str = f" *({sz:,} Bytes)*" if sz is not None and t != "directory" else ""
                res += f"- {icon} `{p}`{sz_str}\n"
            if len(entries) > 25:
                res += f"\n*... und {len(entries) - 25} weitere Einträge.*"
            return res.strip()

        if "lines_read" in data and "content" in data and "file" in data:
            f_name = data.get("file", "")
            tot_l = data.get("total_lines", 0)
            st_l = data.get("start_line", 1)
            end_l = data.get("end_line", tot_l)
            c_text = data.get("content", "")
            ext = f_name.split(".")[-1] if "." in f_name else "text"
            return f"### 📄 `{f_name}` (Zeilen {st_l}–{end_l} von {tot_l})\n\n```{ext}\n{c_text.strip()}\n```"

        if "column_summaries" in data and "total_rows" in data:
            tot_r = data.get("total_rows", 0)
            tot_c = data.get("total_columns", 0)
            cols = data.get("column_summaries", {})
            res = f"### 📊 Datensatz-Analyse ({tot_r:,} Zeilen, {tot_c} Spalten)\n\n"
            for col_name, summ in cols.items():
                c_type = summ.get("type", "text")
                if c_type == "numeric":
                    res += f"- **`{col_name}`** *(Zahl)*: Min: `{summ.get('min')}`, Max: `{summ.get('max')}`, Mittelwert: `{summ.get('mean')}`, Median: `{summ.get('median')}`\n"
                else:
                    res += f"- **`{col_name}`** *(Text)*: `{summ.get('distinct_count')}` eindeutige Werte\n"
            return res.strip()

        if "total_sections" in data and "sections" in data and "word_count" in data:
            tot_s = data.get("total_sections", 0)
            w_cnt = data.get("word_count", 0)
            secs = data.get("sections", [])
            bullets = data.get("key_bullets", [])
            res = f"### 📑 Dokumenten-Struktur ({w_cnt:,} Wörter, {tot_s} Abschnitte)\n\n"
            if bullets:
                res += "**📌 Wichtigste Kernpunkte:**\n"
                for b in bullets[:5]:
                    res += f"- {b}\n"
                res += "\n"
            if secs:
                res += "**Gliederung:**\n"
                for s in secs[:8]:
                    h = s.get("heading", "")
                    l_cnt = s.get("line_count", 0)
                    res += f"- **{h}** ({l_cnt} Zeilen)\n"
            return res.strip()

        if "replacements_count" in data or "chunks_applied" in data:
            f_path = data.get("file_path", "Datei")
            diff = data.get("diff", "")
            applied = data.get("chunks_applied", data.get("replacements_count", 1))
            res = f"### 🛠️ Code erfolgreich angepasst (`{f_path}`)\n\n"
            res += f"- **Angewendete Änderungen:** {applied}\n"
            if diff:
                res += f"\n```diff\n{diff.strip()}\n```\n"
            return res.strip()

        if "total_matches" in data and "matches" in data and isinstance(data.get("matches"), list):
            q = data.get("query", "")
            tot = data.get("total_matches", 0)
            matches = data.get("matches", [])
            if not matches:
                return f"ℹ️ Keine Treffer für **'{q}'** im Projekt gefunden."
            res = f"### 🔍 Code-Suchergebnisse für *'{q}'* ({tot} Treffer)\n\n"
            for m in matches[:15]:
                f = m.get("file", "")
                l_num = m.get("line_number", 0)
                l_code = m.get("line_content", "").strip()
                res += f"- 📄 **`{f}:{l_num}`**\n  ```text\n  {l_code}\n  ```\n"
            if len(matches) > 15:
                res += f"\n*... und {len(matches) - 15} weitere Fundstellen.*"
            return res.strip()

        if "total_symbols" in data and "symbols" in data and isinstance(data.get("symbols"), list):
            f_name = data.get("file", "Datei")
            lang = data.get("language", "")
            syms = data.get("symbols", [])
            res = f"### 🧬 Quellcode-Symbole (`{f_name}`, {len(syms)} Symbole)\n\n"
            for s in syms:
                name = s.get("name", "")
                kind = s.get("kind", "symbol")
                line = s.get("line", 0)
                icon = "📦" if kind == "class" else ("⚡" if "func" in kind else "🔹")
                res += f"- {icon} **`{name}`** *({kind})* — Zeile {line}\n"
            return res.strip()

        if "valid" in data and "total_errors" in data and "errors" in data:
            is_valid = data.get("valid", False)
            lang = data.get("language", "Code")
            errs = data.get("errors", [])
            if is_valid:
                return f"✅ **Syntax-Validierung ({lang}):** Der Quellcode ist syntaktisch einwandfrei."
            res = f"### ❌ Syntax-Fehler erkannt ({lang})\n\n"
            for e in errs:
                l_no = e.get("line", 1)
                col = e.get("column", 0)
                msg = e.get("message", "Syntaxfehler")
                res += f"- **Zeile {l_no}, Spalte {col}:** `{msg}`\n"
            return res.strip()

        if "framework" in data and ("passed" in data or "failed" in data) and "total" in data:
            fw = data.get("framework", "Tests").upper()
            succ = data.get("success", False)
            passed = data.get("passed", 0)
            failed = data.get("failed", 0)
            el = data.get("elapsed_seconds", 0)
            badge = "✅ **ERFOLGREICH**" if succ else "❌ **FEHLGESCHLAGEN**"
            res = f"### 🧪 {fw} Test-Ergebnis: {badge}\n\n"
            res += f"- **Status:** {passed} bestanden, {failed} fehlgeschlagen in {el}s\n"
            fails = data.get("failures", [])
            if fails:
                res += "\n**Fehlgeschlagene Tests:**\n"
                for f in fails[:5]:
                    t_name = f.get("test", "")
                    t_msg = f.get("message", "")
                    res += f"- ❌ **`{t_name}`**: *{t_msg}*\n"
            return res.strip()

        if "is_git_repo" in data and ("staged" in data or "modified" in data):
            br = data.get("branch", "main")
            clean = data.get("clean", False)
            staged = data.get("staged", [])
            modified = data.get("modified", [])
            untracked = data.get("untracked", [])
            res = f"### 🌿 Git-Status (Branch: `{br}`)\n\n"
            if clean:
                res += "✅ Das Arbeitsverzeichnis ist sauber (keine ausstehenden Änderungen).\n"
            else:
                if staged:
                    res += f"**Gestagte Änderungen ({len(staged)}):**\n" + "\n".join(f"- ✅ `{f}`" for f in staged) + "\n\n"
                if modified:
                    res += f"**Modifizierte Dateien ({len(modified)}):**\n" + "\n".join(f"- 📝 `{f}`" for f in modified) + "\n\n"
                if untracked:
                    res += f"**Ungetrackte Dateien ({len(untracked)}):**\n" + "\n".join(f"- ❓ `{f}`" for f in untracked[:10]) + "\n\n"
            return res.strip()

        if "total_diff_chars" in data and "diff_preview" in data:
            diff_text = data.get("diff_preview", "")
            has_ch = data.get("has_changes", False)
            if not has_ch or not diff_text:
                return "ℹ️ Keine ungespeicherten Git-Änderungen vorhanden."
            return f"### 📝 Git-Diff Änderungen\n\n```diff\n{diff_text.strip()}\n```"

        if "total_commits_fetched" in data and "commits" in data and isinstance(data.get("commits"), list):
            commits = data.get("commits", [])
            res = f"### 📜 Git Commit-Historie ({len(commits)} Commits)\n\n"
            for c in commits:
                h = c.get("hash", "")
                dt = c.get("date", "")
                auth = c.get("author", "")
                subj = c.get("subject", "")
                res += f"- 🔖 `{h}` ({dt}, {auth}): **{subj}**\n"
            return res.strip()

        if "command" in data and "exit_code" in data and ("stdout" in data or "stderr" in data):
            cmd = data.get("command", "")
            code = data.get("exit_code", 0)
            elapsed = data.get("elapsed_seconds", 0)
            stdout = data.get("stdout", "").strip()
            stderr = data.get("stderr", "").strip()
            badge = "✅ **Erfolgreich (Code 0)**" if code == 0 else f"❌ **Fehlgeschlagen (Code {code})**"
            res = f"### 💻 Terminal Befehl: `{cmd}` ({badge}, {elapsed}s)\n\n"
            if stdout:
                res += f"```text\n{stdout}\n```\n\n"
            if stderr:
                res += f"**Stderr:**\n```text\n{stderr}\n```\n\n"
            if not stdout and not stderr:
                res += "*Keine Textausgabe.*\n"
            return res.strip()

        if "status_code" in data and ("url" in data or "reason" in data) and ("body_preview" in data or "json_data" in data or "response_headers" in data):
            code = data.get("status_code", 200)
            reason = data.get("reason", "OK")
            url = data.get("url", "")
            elapsed = data.get("elapsed_seconds", 0)
            badge = f"🟢 **{code} {reason}**" if code < 400 else f"🔴 **{code} {reason}**"
            res = f"### 🌐 HTTP Response: {badge} ({elapsed}s)\n"
            res += f"- **URL:** `{url}`\n\n"
            if data.get("json_data") is not None:
                json_str = json.dumps(data["json_data"], indent=2, ensure_ascii=False)
                res += f"```json\n{json_str[:3000]}\n```"
            elif data.get("body_preview"):
                res += f"```text\n{data['body_preview'][:3000]}\n```"
            return res.strip()

        if "full_name" in data and ("stargazers_count" in data or "stars" in data) and "html_url" in data:
            name = data.get("full_name", "")
            url = data.get("html_url", "")
            stars = data.get("stars", data.get("stargazers_count", 0))
            forks = data.get("forks", data.get("forks_count", 0))
            issues = data.get("open_issues", data.get("open_issues_count", 0))
            lang = data.get("language") or "Unbekannt"
            lic = data.get("license") or "Keine"
            desc = data.get("description") or "*Keine Beschreibung vorhanden.*"
            branch = data.get("default_branch", "main")
            res = f"### 🐙 GitHub Repository: [{name}]({url})\n\n"
            res += f"> {desc}\n\n"
            res += f"- **⭐ Sterne:** {stars:,} | **🍴 Forks:** {forks:,} | **❗ Open Issues:** {issues:,}\n"
            res += f"- **💻 Sprache:** `{lang}` | **📜 Lizenz:** `{lic}` | **🌿 Default Branch:** `{branch}`\n"
            return res.strip()

        if "error" in data and ("nicht auf github gefunden" in str(data.get("error", "")).lower() or "github api fehler" in str(data.get("error", "")).lower()):
            err_msg = str(data.get("error", ""))
            return f"### 🐙 GitHub Repository-Abfrage\n\n❌ **Fehler:** {err_msg}\n\n*Hinweis: Bitte stelle sicher, dass das Repository öffentlich erreichbar ist oder der Name exakt übereinstimmt.*"

        if "total_issues" in data and "issues" in data and isinstance(data.get("issues"), list):
            repo = data.get("repository", "")
            issues = data.get("issues", [])
            state = data.get("state", "open")
            res = f"### 🐙 GitHub Issues für `{repo}` ({len(issues)} {state})\n\n"
            if not issues:
                res += f"ℹ️ Keine {state} Issues gefunden.\n"
            for iss in issues[:15]:
                num = iss.get("number")
                title = iss.get("title", "")
                i_url = iss.get("html_url", "")
                st = iss.get("state", "open")
                st_icon = "🟢" if st == "open" else "🟣"
                auth = iss.get("author", "")
                comments = iss.get("comments_count", 0)
                labels = iss.get("labels", [])
                label_str = " " + " ".join(f"`{l}`" for l in labels) if labels else ""
                res += f"- {st_icon} [#{num} {title}]({i_url}){label_str} *(von @{auth}, 💬 {comments})*\n"
            return res.strip()

        if "issue_number" in data and "title" in data and ("comments" in data or "labels" in data):
            num = data.get("issue_number")
            title = data.get("title", "")
            st = data.get("state", "open")
            st_icon = "🟢" if st == "open" else "🟣"
            i_url = data.get("html_url", "")
            auth = data.get("author", "")
            body = data.get("body", "")
            comments = data.get("comments", [])
            res = f"### 🐙 Issue #{num}: {title} ({st_icon} {st.upper()})\n\n"
            if i_url:
                res += f"**Link:** [{i_url}]({i_url}) | **Autor:** @{auth}\n\n"
            if body:
                res += f"#### Beschreibung:\n{body.strip()}\n\n"
            if comments:
                res += f"#### 💬 Kommentare ({len(comments)}):\n"
                for c in comments[:5]:
                    c_auth = c.get("author", "")
                    c_body = c.get("body", "")
                    c_date = c.get("created_at", "")
                    res += f"- **@{c_auth}** ({c_date}):\n  > {c_body.strip()}\n\n"
            return res.strip()

        if "total_prs" in data and "pull_requests" in data and isinstance(data.get("pull_requests"), list):
            repo = data.get("repository", "")
            prs = data.get("pull_requests", [])
            state = data.get("state", "open")
            res = f"### 🐙 GitHub Pull Requests für `{repo}` ({len(prs)} {state})\n\n"
            if not prs:
                res += f"ℹ️ Keine {state} Pull Requests gefunden.\n"
            for pr in prs[:15]:
                num = pr.get("number")
                title = pr.get("title", "")
                p_url = pr.get("html_url", "")
                st = pr.get("state", "open")
                st_icon = "🟢" if st == "open" else "🟣"
                auth = pr.get("author", "")
                draft = " *(Draft)*" if pr.get("draft") else ""
                res += f"- {st_icon} [#{num} {title}]({p_url}){draft} *(von @{auth})*\n"
            return res.strip()

        if "pull_number" in data and "diff" in data:
            num = data.get("pull_number")
            diff = data.get("diff", "")
            return f"### 🐙 GitHub PR #{num} Unified Diff\n\n```diff\n{diff.strip()[:6000]}\n```"

        if "total_files" in data and "files" in data and isinstance(data.get("files"), list) and ("additions" in data or "deletions" in data):
            num = data.get("pull_number")
            tot_f = data.get("total_files", 0)
            adds = data.get("additions", 0)
            dels = data.get("deletions", 0)
            files = data.get("files", [])
            res = f"### 🐙 PR #{num} Geänderte Dateien ({tot_f} Dateien, ➕{adds} / ➖{dels})\n\n"
            for f in files[:20]:
                fn = f.get("filename", "")
                ch = f.get("changes", 0)
                st = f.get("status", "modified")
                res += f"- `{fn}` ({st}, {ch} Änderungen)\n"
            return res.strip()

        if "total_releases" in data and "releases" in data and isinstance(data.get("releases"), list):
            repo = data.get("repository", "")
            rels = data.get("releases", [])
            res = f"### 🐙 GitHub Releases für `{repo}` ({len(rels)} Releases)\n\n"
            for r in rels[:8]:
                tag = r.get("tag_name", "")
                name = r.get("name") or tag
                r_url = r.get("html_url", "")
                pub = r.get("published_at", "")
                res += f"- 📦 [{name} (`{tag}`)]({r_url}) — {pub}\n"
            return res.strip()

        if "total_workflow_runs" in data and "workflow_runs" in data and isinstance(data.get("workflow_runs"), list):
            repo = data.get("repository", "")
            runs = data.get("workflow_runs", [])
            res = f"### 🐙 GitHub Actions Workflows für `{repo}`\n\n"
            for run in runs[:10]:
                name = run.get("name", "Workflow")
                st = run.get("status", "")
                conc = run.get("conclusion") or st
                badge = "✅" if conc == "success" else ("❌" if conc == "failure" else "⏳")
                w_url = run.get("html_url", "")
                branch = run.get("head_branch", "")
                res += f"- {badge} [{name}]({w_url}) — Status: `{conc}` (Branch: `{branch}`)\n"
            return res.strip()

        if "overall_status" in data and "total_checks" in data and "items" in data and isinstance(data.get("items"), list):
            overall = data.get("overall_status", "healthy")
            icon = "🟢" if overall == "healthy" else ("🟡" if overall == "warning" else "🔴")
            tot = data.get("total_checks", 0)
            items = data.get("items", [])
            res = f"### 🩺 Workspace & System Doctor Diagnosereport: {icon} **{overall.upper()}** ({tot} Checks)\n\n"
            for it in items:
                st = it.get("status", "healthy")
                st_icon = "✅" if st == "healthy" else ("⚠️" if st == "warning" else "❌")
                name = it.get("name", "")
                summ = it.get("summary", "")
                rem = it.get("remediation", "")
                lat = it.get("latency_ms")
                lat_str = f" *({lat}ms)*" if lat else ""
                res += f"- {st_icon} **{name}**:{lat_str} {summ}\n"
                if rem:
                    res += f"  > 💡 **Empfehlung:** `{rem}`\n"
            return res.strip()

        if "staged_files_count" in data and "diffs" in data:
            txn = data.get("txn_id", "")
            cnt = data.get("staged_files_count", 0)
            diffs = data.get("diffs", {})
            res = f"### 🛡️ Quarantäne-Staging aktiv (`{txn}`, {cnt} Dateien isoliert)\n\n"
            for fn, d_text in diffs.items():
                res += f"#### 📄 `{fn}`\n```diff\n{d_text.strip()[:3000]}\n```\n\n"
            res += f"*Verwende `quarantine_commit` zur Bestätigung oder `quarantine_rollback` zum Verwerfen.*"
            return res.strip()

        if "total_committed" in data and "committed_files" in data:
            txn = data.get("txn_id", "")
            cnt = data.get("total_committed", 0)
            files = data.get("committed_files", [])
            return f"✅ **Quarantäne-Transaktion `{txn}` erfolgreich in den Workspace überführt** ({cnt} Dateien aktualisiert:\n" + "\n".join(f"- `{f}`" for f in files) + ")"

        if "mission_id" in data and "objective" in data and ("steps" in data or "status" in data):
            m_id = data.get("mission_id", "")
            obj = data.get("objective", "")
            st = data.get("status", "in_progress")
            st_badge = "🟢 In Ausführung" if st == "in_progress" else ("✅ Abgeschlossen" if st == "completed" else "🔴 Blockiert")
            res = f"### 🎯 Mission Journal: `{m_id}` ({st_badge})\n\n"
            res += f"**Ziel:** {obj}\n\n"
            steps = data.get("steps", [])
            if steps:
                res += "**Ausführungsschritte:**\n"
                for s in steps:
                    idx = s.get("step_index", 1)
                    ph = s.get("phase", "")
                    act = s.get("action", "")
                    s_st = s.get("status", "done")
                    icon = "✅" if s_st == "done" else "⏳"
                    res += f"{idx}. {icon} **[{ph.upper()}]** {act}\n"
            return res.strip()

        if "installed_count" in data and "missing_count" in data and "missing" in data and isinstance(data.get("missing"), list):
            inst_cnt = data.get("installed_count", 0)
            miss_cnt = data.get("missing_count", 0)
            missing = data.get("missing", [])
            installed = data.get("installed", [])
            res = f"### 🧰 Entwickler-Tools Audit ({inst_cnt} installiert, {miss_cnt} fehlend)\n\n"
            if missing:
                res += "**Fehlende Tools & Installationsbefehle:**\n"
                for m in missing:
                    t_name = m.get("name", "")
                    cmd = m.get("install_command", "")
                    res += f"- ❌ **`{t_name}`**: Ausführen mit `{cmd}`\n"
                res += "\n"
            if installed:
                res += f"**Installierte Tools ({len(installed)}):**\n"
                for i in installed[:8]:
                    res += f"- ✅ `{i.get('name')}`\n"
            return res.strip()

        if "total_devices" in data and "devices" in data and isinstance(data.get("devices"), list) and ("device_id" in data["devices"][0] if data["devices"] else True):
            tot = data.get("total_devices", 0)
            devs = data.get("devices", [])
            res = f"### 📱 Android ADB Edge Nodes ({tot} verbunden)\n\n"
            if not devs:
                res += "ℹ️ Aktuell keine Android-Geräte oder Emulatoren über ADB gekoppelt.\n"
            for d in devs:
                d_id = d.get("device_id", "")
                model = d.get("model", "Android")
                em = " *(Emulator)*" if d.get("is_emulator") else " *(Physical Device)*"
                res += f"- 🟢 **`{model}`** (ID: `{d_id}`){em}\n"
            return res.strip()

        if "image_url" in data or "markdown" in data:
            md = data.get("markdown")
            if md:
                return md.strip()
            url = data.get("image_url")
            prompt = data.get("prompt", "KI-Bild")
            return f"![{prompt}]({url})\n\n[⬇️ **Bild in voller Auflösung herunterladen**]({url})"

        if "safe" in data and ("resolved_public_ips" in data or "status" in data):
            safe = data.get("safe", False)
            status = data.get("status", "UNKNOWN")
            url = data.get("url", "")
            host = data.get("hostname", "")
            ips = data.get("resolved_public_ips", [])
            msg = data.get("message", "")
            badge = "✅ **SICHER**" if safe else "⛔ **BLOCKIERT / UNSICHER**"
            res = f"### 🛡️ URL-Sicherheitsprüfung: {badge}\n\n"
            res += f"- **URL:** `{url}`\n"
            res += f"- **Status:** `{status}`\n"
            if host:
                res += f"- **Host:** `{host}`\n"
            if ips:
                res += f"- **Öffentliche IP(s):** {', '.join(ips)}\n"
            res += f"\n*{msg}*"
            return res.strip()

        if "url_path" in data and "app_name" in data and "full_local_url" in data:
            title = data.get("title", data.get("app_name"))
            url_p = data.get("url_path", "")
            full_u = data.get("full_local_url", "")
            sz = data.get("size_bytes", 0)
            res = f"### 🚀 WebApp Bereitgestellt: **{title}**\n\n"
            res += f"- **📱 Interaktive WebApp / Spiel:** [🎮 **Jetzt Live Starten: {title}**]({full_u})\n"
            res += f"- **🌐 Lokaler Pfad:** `{url_p}` *({sz:,} Bytes)*\n\n"
            res += f"> 💡 **Tipp:** Du kannst die Anwendung direkt im Browser oder auf deinem Smartphone (Samsung Galaxy S25) / Mobilgerät öffnen. Volle Touch-, On-Screen D-Pad und Tastatur-Steuerung ist aktiv!"
            return res.strip()

        if "total_apps" in data and "apps" in data and isinstance(data.get("apps"), list):
            tot = data.get("total_apps", 0)
            apps = data.get("apps", [])
            res = f"### 🕹️ Gehostete Web-Anwendungen & Spiele ({tot} aktiv)\n\n"
            if not apps:
                res += "ℹ️ Aktuell sind keine Web-Apps auf diesem Node gehostet.\n"
            for a in apps:
                name = a.get("title") or a.get("app_name", "App")
                u = a.get("full_local_url") or a.get("url_path", "")
                desc = a.get("description", "")
                res += f"- 🎮 **[{name}]({u})** (`{a.get('url_path')}`)\n"
                if desc:
                    res += f"  > {desc}\n"
            return res.strip()

        if "multiple_locations" in data and "locations" in data:
            blocks = []
            for loc_data in data["locations"]:
                if not isinstance(loc_data, dict):
                    continue
                loc = loc_data.get("location", "Ort")
                temp = loc_data.get("temperature_celsius", "N/A")
                app_temp = loc_data.get("apparent_temperature_celsius")
                cond = loc_data.get("condition", "Unbekannt")
                hum = loc_data.get("humidity_percent", "N/A")
                wind = loc_data.get("wind_speed_kmh", "N/A")
                reg = loc_data.get("region")
                country = loc_data.get("country")
                loc_str = f"{loc} ({reg}, {country})" if reg and country else loc
                block = f"Aktuelles Live-Wetter für **{loc_str}**:\n"
                block += f"- **Bedingungen:** {cond}\n"
                block += f"- **Temperatur:** {temp} °C" + (f" (gefühlt {app_temp} °C)\n" if app_temp is not None else "\n")
                block += f"- **Luftfeuchtigkeit:** {hum} %\n"
                block += f"- **Windgeschwindigkeit:** {wind} km/h"
                if "precipitation_mm" in loc_data:
                    block += f"\n- **Niederschlag:** {loc_data['precipitation_mm']} mm"
                blocks.append(block.strip())
            return "\n\n---\n\n".join(blocks)

        if "temperature_celsius" in data or "condition" in data:
            loc = data.get("location", "Ort")
            temp = data.get("temperature_celsius", "N/A")
            app_temp = data.get("apparent_temperature_celsius")
            cond = data.get("condition", "Unbekannt")
            hum = data.get("humidity_percent", "N/A")
            wind = data.get("wind_speed_kmh", "N/A")
            reg = data.get("region")
            country = data.get("country")
            loc_str = f"{loc} ({reg}, {country})" if reg and country else loc
            result = f"Aktuelles Live-Wetter für **{loc_str}**:\n"
            result += f"- **Bedingungen:** {cond}\n"
            result += f"- **Temperatur:** {temp} °C" + (f" (gefühlt {app_temp} °C)\n" if app_temp is not None else "\n")
            result += f"- **Luftfeuchtigkeit:** {hum} %\n"
            result += f"- **Windgeschwindigkeit:** {wind} km/h\n"
            if "precipitation_mm" in data:
                result += f"- **Niederschlag:** {data['precipitation_mm']} mm\n"
            if data.get("source"):
                result += f"- **Quelle:** {data['source']}"
            return result.strip()

        if "multiple_symbols" in data and "quotes" in data:
            blocks = []
            for q_data in data["quotes"]:
                if not isinstance(q_data, dict):
                    continue
                symbol = str(q_data.get("symbol", "")).upper()
                name = q_data.get("name", symbol)
                price = q_data.get("price_usd") or q_data.get("price_eur") or q_data.get("price")
                change_24h = q_data.get("change_24h_percent")
                block = f"Aktueller Kurs für **{name} ({symbol})**:\n"
                block += f"- **Preis:** ${price:,.2f}" if isinstance(price, (int, float)) else f"- **Preis:** {price}\n"
                if change_24h is not None:
                    block += f"- **24h-Veränderung:** {change_24h:+.2f} %"
                blocks.append(block.strip())
            return "\n\n---\n\n".join(blocks)

        if "price_usd" in data or "symbol" in data:
            symbol = str(data.get("symbol", "")).upper()
            name = data.get("name", symbol)
            price = data.get("price_usd") or data.get("price_eur") or data.get("price")
            change_24h = data.get("change_24h_percent")
            result = f"Aktueller Börsen-/Kryptokurs für **{name} ({symbol})**:\n"
            result += f"- **Preis:** ${price:,.2f}" if isinstance(price, (int, float)) else f"- **Preis:** {price}\n"
            if change_24h is not None:
                result += f"\n- **24h-Veränderung:** {change_24h:+.2f} %"
            return result.strip()

        if "multiple_articles" in data and "articles" in data:
            blocks = []
            for art in data["articles"]:
                if not isinstance(art, dict):
                    continue
                t = art.get("title", "")
                s = art.get("summary") or art.get("extract", "")
                u = art.get("url", "")
                block = f"### 📖 **{t}** (Wikipedia)\n\n{s}"
                if u:
                    block += f"\n\n*Quelle: [{u}]({u})*"
                blocks.append(block.strip())
            return "\n\n---\n\n".join(blocks)

        if ("articles" in data or ("topic" in data and "items" in data)) and not data.get("multiple_articles"):
            articles = data.get("articles") or data.get("items") or []
            topic = data.get("topic", "Aktuelle Nachrichten")
            result = f"Aktuelle Nachrichten (**{topic}**):\n\n"
            if isinstance(articles, list):
                for index, article in enumerate(articles[:5], 1):
                    if not isinstance(article, dict):
                        continue
                    title = article.get("title", "")
                    source = article.get("source", "")
                    url = article.get("link", "")
                    summary = article.get("summary", "")
                    source_text = f" *({source})*" if source else ""
                    if url and title:
                        result += f"{index}. [{title}]({url}){source_text}\n"
                    elif title:
                        result += f"{index}. **{title}**{source_text}\n"
                    if summary:
                        result += f"   {summary}\n\n"
                    else:
                        result += "\n"
            return result.strip()

        if "results" in data and isinstance(data.get("results"), list):
            q = data.get("query", "Websuche")
            results_list = data.get("results", [])
            if not results_list:
                return f"Für die Suchanfrage **'{q}'** wurden keine Live-Websuchergebnisse gefunden."
            res_str = f"Live-Websuchergebnisse für **'{q}'**:\n\n"
            for idx, r in enumerate(results_list[:5], 1):
                if not isinstance(r, dict):
                    continue
                title = r.get("title", "")
                url = r.get("url", "")
                snippet = r.get("snippet", "")
                if url and title:
                    res_str += f"{idx}. [{title}]({url})\n"
                elif title:
                    res_str += f"{idx}. **{title}**\n"
                if snippet:
                    res_str += f"   {snippet}\n\n"
            return res_str.strip()

        if "available_tools" in data and isinstance(data.get("available_tools"), list):
            tools_list = data.get("available_tools", [])
            res_str = "### 🛠️ Aktive ComputeMesh MCP-Module & Live-Tools\n\n"
            res_str += "Folgende Live-Werkzeuge sind auf diesem Cluster einsatzbereit:\n\n"
            for t in tools_list:
                name = t.get("name", "")
                desc = t.get("description", "")
                res_str += f"- **`{name}`**: {desc}\n"
            res_str += "\n*Alle Werkzeuge können direkt durch Fragen nach aktuellen Daten (Wetter, Suche, Kurse, News etc.) genutzt werden.*"
            return res_str.strip()

        if "city" in data and ("today" in data or "tomorrow" in data or "events" in data or "rubrics" in data):
            raw_city = str(data.get("city") or data.get("requestedCity") or "Veranstaltungen").strip()
            city = raw_city.title() if raw_city else "Veranstaltungen"
            notes_str = str(data.get("notes") or "").strip()
            sections = []

            rubric_icons = {
                "KONZERTE & LIVE-MUSIK": "🎸",
                "PARTY & CLUB": "🪩",
                "BÜHNE & THEATER": "🎭",
                "FESTE & FESTIVALS": "🎪",
                "KUNST & AUSSTELLUNGEN": "🎨",
                "SPORT & FITNESS": "⚽",
                "KURSE & WORKSHOPS": "🧠",
                "KINDER & FAMILIE": "🧸",
                "SONSTIGES": "📌",
            }

            for period_key in ("today", "tomorrow"):
                period = data.get(period_key)
                if not isinstance(period, dict):
                    continue
                label = period.get("dayLabel") or ("Heute" if period_key == "today" else "Morgen")
                date_iso = period.get("dateIso", "")
                rubrics = period.get("rubrics") or {}
                events = period.get("events") or []
                highlights = period.get("highlights") or []

                header = f"### 📅 {label}" + (f" ({date_iso})" if date_iso else "")
                period_blocks = []
                seen_titles: set[tuple[str, str]] = set()

                if rubrics:
                    preferred_order = [
                        "KONZERTE & LIVE-MUSIK",
                        "PARTY & CLUB",
                        "FESTE & FESTIVALS",
                        "BÜHNE & THEATER",
                        "KUNST & AUSSTELLUNGEN",
                        "SONSTIGES",
                        "KURSE & WORKSHOPS",
                        "SPORT & FITNESS",
                        "KINDER & FAMILIE",
                    ]
                    ordered_rubrics = [r for r in preferred_order if r in rubrics] + [r for r in rubrics if r not in preferred_order]

                    for rubric_name in ordered_rubrics:
                        r_events = rubrics[rubric_name]
                        if not r_events:
                            continue
                        icon = rubric_icons.get(rubric_name, "📌")
                        rubric_lines = [f"**{icon} {rubric_name.title()}:**"]
                        added_in_rubric = 0

                        for ev in r_events:
                            t = str(ev.get("title") or "").strip()
                            v = str(ev.get("venue") or "").strip()
                            st = str(ev.get("startTime") or "").strip()
                            desc = str(ev.get("description") or "").strip()
                            u = str(ev.get("url") or "").strip()
                            dist = ev.get("distanceKm")

                            key = (t.lower(), v.lower())
                            if key in seen_titles:
                                continue
                            seen_titles.add(key)

                            time_str = f" um {st} Uhr" if st and st != "None" else ""
                            dist_str = f" (~{dist} km)" if (dist and float(dist) > 2.0) else ""
                            loc_str = f" @ {v}{dist_str}" if v else (f" {dist_str}" if dist_str else "")
                            item_hdr = f"- **{t}**{loc_str}{time_str}"
                            if u and u.startswith("http"):
                                item_hdr += f" — [Info & Tickets]({u})"
                            rubric_lines.append(item_hdr)

                            if desc and len(desc) > 15 and not desc.startswith("http"):
                                clean_desc = re.sub(r"\s+", " ", desc).replace("\n", " ").strip()
                                if clean_desc.lower() != t.lower():
                                    short_desc = clean_desc[:120].strip() + ("..." if len(clean_desc) > 120 else "")
                                    rubric_lines.append(f"  *{short_desc}*")

                            added_in_rubric += 1
                            if added_in_rubric >= 6:
                                break

                        if added_in_rubric > 0:
                            period_blocks.append("\n".join(rubric_lines))

                elif events:
                    event_lines = []
                    for idx, ev in enumerate(events[:8], 1):
                        t = str(ev.get("title") or "").strip()
                        v = str(ev.get("venue") or "").strip()
                        st = str(ev.get("startTime") or "").strip()
                        desc = str(ev.get("description") or "").strip()
                        u = str(ev.get("url") or "").strip()
                        dist = ev.get("distanceKm")

                        key = (t.lower(), v.lower())
                        if key in seen_titles:
                            continue
                        seen_titles.add(key)

                        time_str = f" um {st} Uhr" if st and st != "None" else ""
                        dist_str = f" (~{dist} km)" if (dist and float(dist) > 2.0) else ""
                        loc_str = f" @ {v}{dist_str}" if v else (f" {dist_str}" if dist_str else "")
                        item_hdr = f"{idx}. **{t}**{loc_str}{time_str}"
                        if u and u.startswith("http"):
                            item_hdr += f" — [Info & Tickets]({u})"
                        event_lines.append(item_hdr)

                        if desc and len(desc) > 15 and not desc.startswith("http"):
                            clean_desc = re.sub(r"\s+", " ", desc).replace("\n", " ").strip()
                            if clean_desc.lower() != t.lower():
                                short_desc = clean_desc[:120].strip() + ("..." if len(clean_desc) > 120 else "")
                                event_lines.append(f"   *{short_desc}*")

                    if event_lines:
                        period_blocks.append("\n".join(event_lines))

                elif highlights:
                    hl_lines = [f"- {hl}" for hl in highlights[:6]]
                    period_blocks.append("\n".join(hl_lines))

                if period_blocks:
                    sections.append(header + "\n\n" + "\n\n".join(period_blocks))

            if sections:
                banner = f"## 🎟️ Live-Veranstaltungen & Konzerte in {city}\n\n"
                if notes_str:
                    banner += f"*ℹ️ {notes_str} (today.inetconnector.com)*\n\n"
                else:
                    banner += "*Echtzeit-Daten aus dem ComputeMesh Event-Index (today.inetconnector.com)*\n\n"
                return banner + "\n\n---\n\n".join(sections)

            # Fallback to Deep Cultural Research across subculture, live clubs, village gems and calendars
            try:
                from .builtin.web_search import deep_cultural_event_search
                deep_res = deep_cultural_event_search(city, max_results=8)
                rubrics_found = deep_res.get("rubrics", {})
                if rubrics_found:
                    res_str = f"## 🎟️ Aktuelle Veranstaltungen & Kultur-Highlights in {city}\n\n"
                    res_str += f"*Tiefenrecherche für den Raum {city} (Subkultur, Live-Bühnen, Regionalkultur & Kalender):*\n\n"
                    for badge_name, items in rubrics_found.items():
                        res_str += f"### {badge_name}\n\n"
                        for idx, r in enumerate(items, 1):
                            title = r.get("title", "")
                            url = r.get("url", "")
                            snippet = r.get("snippet", "")
                            if url and title:
                                res_str += f"{idx}. [{title}]({url})\n"
                            elif title:
                                res_str += f"{idx}. **{title}**\n"
                            if snippet:
                                clean_snip = re.sub(r"\s+", " ", snippet).strip()
                                res_str += f"   *{clean_snip}*\n\n"
                        res_str += "\n"
                    return res_str.strip()
            except Exception:
                pass

            return f"Für **{city}** konnten im aktuellen Zeitraum keine passenden Veranstaltungen gefunden werden."

        if "multiple_conversions" in data and "conversions" in data:
            amt = data.get("amount", 1)
            from_c = data.get("from_currency", "EUR")
            blocks = [f"### 💱 Live-Währungsumrechnung ({amt:,.2f} {from_c})\n"]
            for conv in data["conversions"]:
                if not isinstance(conv, dict):
                    continue
                to_c = conv.get("to_currency", "")
                c_amt = conv.get("converted_amount", 0)
                rate = conv.get("rate")
                src = conv.get("source", "EZB / Live-Markt")
                if "error" in conv:
                    blocks.append(f"- ❌ **{to_c}:** {conv.get('error')}")
                else:
                    rate_str = f" (Kurs: {rate:,.4f})" if isinstance(rate, (int, float)) else f" (Kurs: {rate})"
                    blocks.append(f"- 💵 **{amt:,.2f} {from_c} = {c_amt:,.2f} {to_c}**{rate_str} *[{src}]*")
            return "\n".join(blocks).strip()

        if "multiple_clocks" in data and "clocks" in data:
            blocks = [f"### 🕒 Weltzeituhr ({len(data['clocks'])} Standorte)\n"]
            for clk in data["clocks"]:
                if not isinstance(clk, dict):
                    continue
                city = clk.get("city", "Stadt")
                t = clk.get("formatted_time", "")
                d = clk.get("formatted_date", "")
                tz = clk.get("timezone", "")
                kw = clk.get("calendar_week", "")
                offset = clk.get("utc_offset", "")
                blocks.append(
                    f"#### 📍 **{city}** ({tz})\n"
                    f"- **Uhrzeit:** `{t}` (UTC {offset})\n"
                    f"- **Datum:** {d} (KW {kw})\n"
                )
            return "\n".join(blocks).strip()

        if "multiple_stats" in data and "stats" in data:
            blocks = [f"### 🌐 Weltbank Makroökonomische Indikatoren ({len(data['stats'])} Länder)\n"]
            for stat in data["stats"]:
                if not isinstance(stat, dict):
                    continue
                c_name = stat.get("country", "")
                c_code = stat.get("country_code", "")
                ind = stat.get("indicator", "")
                series = stat.get("time_series", [])
                latest_val = stat.get("latest_value")
                latest_yr = stat.get("latest_year")
                val_str = f"{latest_val:,.2f}" if isinstance(latest_val, (int, float)) else str(latest_val)
                item_block = f"#### 📊 **{c_name} ({c_code})** — {ind}\n"
                item_block += f"- **Aktuellster Wert ({latest_yr}):** `{val_str}`\n"
                if series:
                    item_block += "- **Verlauf:** " + ", ".join(f"{s.get('year')}: `{s.get('value'):,.2f}`" if isinstance(s.get('value'), (int, float)) else f"{s.get('year')}: `{s.get('value')}`" for s in series[:4])
                blocks.append(item_block)
            return "\n\n---\n\n".join(blocks).strip()

        if "multiple_feeds" in data and "feeds" in data:
            blocks = [f"### 📰 Aktuelle Nachrichten-Feeds ({len(data['feeds'])} Themen/Quellen)\n"]
            for feed in data["feeds"]:
                if not isinstance(feed, dict):
                    continue
                topic = feed.get("topic", "Nachrichten")
                articles = feed.get("articles", [])
                feed_block = f"#### 📌 **{topic}**\n"
                for idx, a in enumerate(articles[:4], 1):
                    t = a.get("title", "")
                    u = a.get("link", "")
                    s = a.get("source", "")
                    s_str = f" *({s})*" if s else ""
                    if u and t:
                        feed_block += f"{idx}. [{t}]({u}){s_str}\n"
                    elif t:
                        feed_block += f"{idx}. **{t}**{s_str}\n"
                blocks.append(feed_block.strip())
            return "\n\n---\n\n".join(blocks).strip()

        if "multiple_countries" in data and "countries" in data:
            blocks = []
            for c_data in data["countries"]:
                if not isinstance(c_data, dict):
                    continue
                summ = c_data.get("summary")
                if summ:
                    blocks.append(summ.strip())
                else:
                    c_name = c_data.get("country_name", "Land")
                    cap = c_data.get("capital", "N/A")
                    pop = c_data.get("population", 0)
                    area = c_data.get("area_sqkm", 0)
                    reg = c_data.get("region", "")
                    block = f"### 🏛️ **{c_name}** ({reg})\n"
                    block += f"- **Hauptstadt:** {cap}\n"
                    block += f"- **Einwohner:** {pop:,} Menschen\n"
                    block += f"- **Fläche:** {area:,} km²\n"
                    blocks.append(block.strip())
            return "\n\n---\n\n".join(blocks)

        if "multiple_articles" in data and "articles" in data:
            blocks = []
            for art in data["articles"]:
                if not isinstance(art, dict):
                    continue
                t = art.get("title", "")
                s = art.get("summary") or art.get("extract", "")
                u = art.get("url", "")
                block = f"### 📖 **{t}** (Wikipedia)\n\n{s}"
                if u:
                    block += f"\n\n*Quelle: [{u}]({u})*"
                blocks.append(block.strip())
            return "\n\n---\n\n".join(blocks)

        if "multiple_compounds" in data and "compounds" in data:
            blocks = []
            for comp in data["compounds"]:
                if not isinstance(comp, dict):
                    continue
                summ = comp.get("summary")
                if summ:
                    blocks.append(summ.strip())
                elif "error" in comp:
                    blocks.append(f"❌ **{comp.get('compound_name', 'Verbindung')}:** {comp.get('error')}")
            return "\n\n---\n\n".join(blocks).strip()

        if "molecular_formula" in data and ("molecular_weight_g_mol" in data or "iupac_name" in data):
            summ = data.get("summary")
            if summ:
                return f"### 🧪 Chemische Eigenschaften (PubChem)\n\n{summ}".strip()

        if "multiple_packages" in data and "packages" in data:
            blocks = []
            for pkg in data["packages"]:
                if not isinstance(pkg, dict):
                    continue
                summ = pkg.get("summary_formatted")
                if summ:
                    blocks.append(summ.strip())
                elif "error" in pkg:
                    blocks.append(f"❌ **{pkg.get('name', 'Paket')}:** {pkg.get('error')}")
            return "\n\n---\n\n".join(blocks).strip()

        if "summary_formatted" in data and "ecosystem" in data:
            return f"### 📦 Software-Paket-Information\n\n{data['summary_formatted']}".strip()

        if "multiple_words" in data and "words" in data:
            blocks = []
            for w_data in data["words"]:
                if not isinstance(w_data, dict):
                    continue
                summ = w_data.get("summary")
                if summ:
                    blocks.append(summ.strip())
                elif "error" in w_data:
                    blocks.append(f"❌ **{w_data.get('word', 'Wort')}:** {w_data.get('error')}")
            return "\n\n---\n\n".join(blocks).strip()

        if "word" in data and "meanings" in data and "summary" in data:
            return f"### 📚 Wörterbuch-Definition\n\n{data['summary']}".strip()

        if "multiple_products" in data and "products" in data:
            blocks = []
            for p_data in data["products"]:
                if not isinstance(p_data, dict):
                    continue
                summ = p_data.get("summary")
                if summ:
                    blocks.append(summ.strip())
                elif "error" in p_data:
                    blocks.append(f"❌ **{p_data.get('product_name', 'Produkt')}:** {p_data.get('error')}")
            return "\n\n---\n\n".join(blocks).strip()

        if "nutrition_per_100g" in data and "nutriscore" in data:
            summ = data.get("summary")
            if summ:
                return f"### 🥗 Lebensmittel- & Nährwert-Information (Open Food Facts)\n\n{summ}".strip()

        if "multiple_stations" in data and "stations" in data:
            blocks = []
            for s_data in data["stations"]:
                if not isinstance(s_data, dict):
                    continue
                summ = s_data.get("summary")
                if summ:
                    blocks.append(summ.strip())
                elif "error" in s_data:
                    blocks.append(f"❌ **{s_data.get('station_name', 'Bahnhof')}:** {s_data.get('error')}")
            return "\n\n---\n\n".join(blocks).strip()

        if "departures" in data and "station_name" in data:
            summ = data.get("summary")
            if summ:
                return f"### 🚆 Bahn-Fahrplan & Abfahrten (Deutsche Bahn / HAFAS)\n\n{summ}".strip()

        if "earthquakes_count" in data and "events" in data:
            summ = data.get("summary")
            if summ:
                return f"### 🌋 Erdbeben-Feed & Seismische Aktivität (USGS)\n\n{summ}".strip()

        if "papers_found" in data and "papers" in data:
            q = data.get("query", "Forschung")
            papers = data.get("papers", [])
            if not papers:
                return f"ℹ️ Keine wissenschaftlichen Paper auf arXiv für **'{q}'** gefunden."
            res = f"### 📄 Wissenschaftliche arXiv-Publikationen für *'{q}'* ({len(papers)} Paper)\n\n"
            for idx, p in enumerate(papers[:5], 1):
                t = p.get("title", "")
                authors = ", ".join(p.get("authors", [])[:3])
                dt = p.get("published_date", "")
                url = p.get("pdf_url") or p.get("arxiv_url", "")
                abst = p.get("abstract", "")
                res += f"#### {idx}. [{t}]({url})\n"
                res += f"- **Autoren:** {authors} | **Veröffentlicht:** {dt}\n"
                if abst:
                    res += f"- **Abstract:** *{abst[:300]}...*\n\n"
            return res.strip()

        if "mode" in data and "results" in data and ("live_score_note" in data or data.get("source") == "TheSportsDB v1"):
            mode = data.get("mode", "teams")
            results = data.get("results", [])
            q = data.get("query") or data.get("date") or ""
            if not results:
                return f"ℹ️ Keine Sportergebnisse für **'{q}'** in TheSportsDB gefunden."
            res = f"### ⚽ Sportdaten & Spielplan ({mode.upper()})\n\n"
            for r in results[:5]:
                if mode == "teams":
                    name = r.get("name", "Team")
                    sport = r.get("sport", "")
                    league = r.get("league", "")
                    country = r.get("country", "")
                    stadium = r.get("stadium", "")
                    res += f"- **{name}** ({sport}, {league}, {country})" + (f" — Stadion: {stadium}\n" if stadium else "\n")
                else:
                    ev_name = r.get("name", "Spiel")
                    dt = r.get("date", "")
                    tm = r.get("time", "")
                    h_score = r.get("home_score")
                    a_score = r.get("away_score")
                    score_str = f" ({h_score} : {a_score})" if h_score is not None and a_score is not None else ""
                    res += f"- **{ev_name}**{score_str} — {dt} {tm}\n"
            return res.strip()

        if "straight_line_distance_km" in data or "driving_distance_km" in data or "estimated_driving_distance_km" in data:
            summ = data.get("summary")
            if summ:
                return f"### 🧭 Routenberechnung & Geodistanz\n\n{summ}".strip()
            o = data.get("origin", {}).get("name", "Start")
            d = data.get("destination", {}).get("name", "Ziel")
            s_dist = data.get("straight_line_distance_km", 0)
            d_dist = data.get("driving_distance_km") or data.get("estimated_driving_distance_km", 0)
            d_dur = data.get("driving_duration_formatted") or data.get("estimated_driving_duration", "")
            bearing = data.get("direction", "")
            res = f"### 🧭 Entfernung & Route: **{o}** ➔ **{d}**\n\n"
            res += f"- **Luftlinie:** {s_dist:,.2f} km (Richtung {bearing})\n"
            if d_dist:
                res += f"- **Fahrtstrecke:** ~{d_dist:,.1f} km\n"
            if d_dur:
                res += f"- **Fahrzeit:** {d_dur}\n"
            return res.strip()

        if "country_name" in data and ("capital" in data or "population" in data):
            summ = data.get("summary")
            if summ:
                return f"### 🌍 Länder-Geodaten & Fakten\n\n{summ}".strip()
            c_name = data.get("country_name", "Land")
            cap = data.get("capital", "N/A")
            pop = data.get("population", 0)
            area = data.get("area_sqkm", 0)
            reg = data.get("region", "")
            res = f"### 🏛️ **{c_name}** ({reg})\n\n"
            res += f"- **Hauptstadt:** {cap}\n"
            res += f"- **Einwohnerzahl:** {pop:,} Menschen\n"
            res += f"- **Fläche:** {area:,} km²\n"
            return res.strip()

        if "title" in data and "summary" in data:
            title = data.get("title", "")
            summary = data.get("summary", "")
            url = data.get("url", "")
            result = f"**{title}** (Wikipedia):\n\n{summary}"
            if url:
                result += f"\n\n*Quelle: [{url}]({url})*"
            return result.strip()

        if "time_series" in data and "indicator" in data and "country" in data:
            summ = data.get("summary")
            if summ:
                return f"### 🌐 Weltbank Statistik\n\n{summ}".strip()

        if "result" in data and ("expression" in data or "status" in data):
            expr = data.get("expression") or ""
            val = data.get("result")
            return f"Ergebnis: **{expr} = {val}**" if expr else f"Ergebnis: **{val}**"

        if "formatted_time" in data or "formatted_date" in data or "datetime_iso" in data or "current_time" in data or "local_time" in data:
            t = data.get("formatted_time") or data.get("current_time") or data.get("time") or ""
            d = data.get("formatted_date") or data.get("date") or ""
            city = data.get("city", "")
            tz = data.get("timezone", "Europe/Berlin")
            kw = data.get("calendar_week")
            loc_label = f" ({city}, {tz})" if city else f" ({tz})"
            res = f"Aktuelle Uhrzeit & Datum**{loc_label}**:\n"
            if t:
                res += f"- **Uhrzeit:** {t}\n"
            if d:
                res += f"- **Datum:** {d}\n"
            if kw:
                res += f"- **Kalenderwoche:** KW {kw}\n"
            return res.strip()

        if "converted_amount" in data or "exchange_rate" in data or ("from" in data and "to" in data and "rate" in data) or ("from_currency" in data and "to_currency" in data):
            fmt = data.get("formatted")
            if fmt:
                return f"### 💱 Währungsumrechnung\n\n**{fmt}**"
            src = (data.get("from_currency") or data.get("from") or "").upper()
            dst = (data.get("to_currency") or data.get("to") or "").upper()
            rate = data.get("rate") or data.get("exchange_rate")
            amt = data.get("amount", 1)
            conv = data.get("converted_amount")
            if conv is not None:
                return f"### 💱 Währungsumrechnung\n\n**{amt:,.2f} {src} = {conv:,.2f} {dst}** (Kurs: {rate})".strip()

        if "error" in data:
            err_msg = str(data.get("error", "Keine passenden Informationen gefunden."))
            q = data.get("query") or data.get("search_term")
            if q:
                return f"ℹ️ Für **'{q}'** konnten keine direkten Daten ermittelt werden ({err_msg})."
            return f"ℹ️ {err_msg}"
    except Exception:
        pass
    return str(content or "")


