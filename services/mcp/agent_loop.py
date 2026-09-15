# SPDX-License-Identifier: Apache-2.0
"""Bounded autonomous tool-calling loop for ComputeMesh MCP tools."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .config import MCPConfig, get_mcp_config
from .tool_registry import ToolRegistry

XML_TOOL_CALL_RE = re.compile(r"<tool_call>\s*({.*?})(?:\s*</tool_call>|\s*$)", re.DOTALL)
JSON_CODE_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{\s*\"(?:name|tool|function)\"\s*:\s*\"[a-zA-Z0-9_-]+\".*?\})\s*```", re.DOTALL)
RAW_JSON_TOOL_RE = re.compile(r"\{\s*\"(?:name|tool|function)\"\s*:\s*\"([a-zA-Z0-9_-]+)\"\s*,\s*\"(?:arguments|parameters)\"\s*:\s*(\{.*?\})\s*\}", re.DOTALL)
MAX_AGENT_ITERATIONS = 20
MAX_TOOL_CALLS_PER_ITERATION = 16
MAX_TOOL_MESSAGE_CHARS = 100_000


@dataclass
class ToolCallRecord:
    id: str
    name: str
    arguments: Dict[str, Any]
    result: Any


@dataclass
class AgentExecutionResult:
    final_content: str
    messages: List[Dict[str, Any]]
    tool_calls_executed: List[ToolCallRecord] = field(default_factory=list)
    iterations: int = 1
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


THINKING_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)


def format_reasoning_and_thinking_blocks(content: str) -> str:
    """Formats <think>...</think> reasoning blocks into interactive collapsible HTML accordions."""
    if not content or "<think>" not in content.lower():
        return content

    def _replace_think(match: re.Match) -> str:
        thought_text = match.group(1).strip()
        if not thought_text:
            return ""
        return (
            f'<details class="cm-thinking-block">\n'
            f'  <summary>🧠 <strong>Gedankengang anzeigen</strong> <em>(Deep Reasoning)</em></summary>\n'
            f'  <div class="cm-thinking-body">\n'
            f'{thought_text}\n'
            f'  </div>\n'
            f'</details>\n\n'
        )

    formatted = THINKING_RE.sub(_replace_think, content)
    return formatted.strip()


def format_tool_content_if_json(content: str) -> str:
    """Format a few common raw JSON tool responses for direct user display."""
    content = format_reasoning_and_thinking_blocks(content)
    cleaned = str(content or "").strip()
    if not (cleaned.startswith("{") and cleaned.endswith("}")):
        return str(content or "")
    try:
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            return str(content or "")

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

        if "full_name" in data and "stargazers_count" in data and "html_url" in data:
            name = data.get("full_name", "")
            url = data.get("html_url", "")
            stars = data.get("stargazers_count", 0)
            forks = data.get("forks_count", 0)
            issues = data.get("open_issues_count", 0)
            lang = data.get("language") or "Unbekannt"
            lic = data.get("license") or "Keine"
            desc = data.get("description") or "*Keine Beschreibung vorhanden.*"
            branch = data.get("default_branch", "main")
            res = f"### 🐙 GitHub Repository: [{name}]({url})\n\n"
            res += f"> {desc}\n\n"
            res += f"- **⭐ Sterne:** {stars:,} | **🍴 Forks:** {forks:,} | **❗ Open Issues:** {issues:,}\n"
            res += f"- **💻 Sprache:** `{lang}` | **📜 Lizenz:** `{lic}` | **🌿 Default Branch:** `{branch}`\n"
            return res.strip()

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


def _canonical_name(registry: ToolRegistry, name: str) -> str:
    tool = registry.get_tool(str(name or ""))
    return tool.name if tool is not None else str(name or "")


def _fallback_tool_calls(content: str, registry: ToolRegistry) -> List[Dict[str, Any]]:
    """Parse compatibility tool-call formats emitted by older/local models."""
    tool_calls: List[Dict[str, Any]] = []

    if "<tool_call>" in content:
        for match in XML_TOOL_CALL_RE.finditer(content):
            try:
                parsed = json.loads(match.group(1))
                if not isinstance(parsed, dict):
                    continue
                name = parsed.get("name") or parsed.get("tool") or parsed.get("function")
                if name and registry.get_tool(str(name)):
                    tool_calls.append({
                        "id": f"call_xml_{len(tool_calls)+1}",
                        "type": "function",
                        "function": {
                            "name": str(name),
                            "arguments": json.dumps(parsed.get("arguments", parsed.get("parameters", {}))),
                        },
                    })
            except (json.JSONDecodeError, TypeError):
                continue

    if not tool_calls and ("```json" in content or "```" in content):
        for match in JSON_CODE_BLOCK_RE.finditer(content):
            try:
                clean_json_str = re.sub(r"//.*", "", match.group(1))
                parsed = json.loads(clean_json_str)
                if not isinstance(parsed, dict):
                    continue
                name = parsed.get("name") or parsed.get("tool") or parsed.get("function")
                if name and registry.get_tool(str(name)):
                    tool_calls.append({
                        "id": f"call_json_{len(tool_calls)+1}",
                        "type": "function",
                        "function": {
                            "name": str(name),
                            "arguments": json.dumps(parsed.get("arguments", parsed.get("parameters", {}))),
                        },
                    })
            except (json.JSONDecodeError, TypeError):
                continue

    if not tool_calls:
        for match in RAW_JSON_TOOL_RE.finditer(content):
            name = match.group(1)
            if name and registry.get_tool(name):
                tool_calls.append({
                    "id": f"call_raw_{len(tool_calls)+1}",
                    "type": "function",
                    "function": {"name": name, "arguments": match.group(2)},
                })

    if not tool_calls and content.strip().startswith("{") and content.strip().endswith("}"):
        try:
            parsed = json.loads(content.strip())
            if isinstance(parsed, dict):
                name = parsed.get("name") or parsed.get("tool") or parsed.get("function")
                if name and registry.get_tool(str(name)):
                    tool_calls.append({
                        "id": "call_direct_1",
                        "type": "function",
                        "function": {
                            "name": str(name),
                            "arguments": json.dumps(parsed.get("arguments", parsed.get("parameters", {}))),
                        },
                    })
        except (json.JSONDecodeError, TypeError):
            pass

    return tool_calls[:MAX_TOOL_CALLS_PER_ITERATION]


def _decode_arguments(raw_args: Any) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    if isinstance(raw_args, dict):
        return raw_args, None
    if isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args)
        except json.JSONDecodeError as exc:
            return None, f"Tool-Argumente sind kein gültiges JSON: {exc.msg}"
        if not isinstance(parsed, dict):
            return None, "Tool-Argumente müssen ein JSON-Objekt sein."
        return parsed, None
    return None, "Tool-Argumente müssen ein JSON-Objekt sein."


def detect_direct_tool_intent(text: str, registry: Optional[ToolRegistry] = None) -> Optional[tuple[str, dict[str, Any]]]:
    """Detects direct tool calling intent from user query with high precision."""
    cleaned = text.strip()
    
    # 0. List Active MCP Modules & Tools
    if re.search(r"(?:welche\s+mcp|welche\s+tools|welche\s+module|aktive\s+tools|aktive\s+module|list\s+tools|available\s+tools|mcp\s+status|welche\s+funktionen\s+hast\s+du|was\s+kannst\s+du|welche\s+werkzeuge)", cleaned, re.IGNORECASE):
        return ("list_available_tools", {})

    # 0.1 Image Generation (Direct GPU AI RealVisXL synthesis)
    m_img = re.search(
        r"(?:generiere\s+(?:ein\s+)?bild\s+(?:von|mit)?\s*|erstelle\s+(?:ein\s+)?(?:bild|foto)\s+(?:von|mit)?\s*|zeichne\s+(?:ein\s+)?(?:bild|foto)?\s*(?:von|mit)?\s*|male\s+(?:ein\s+)?(?:bild|gemälde)?\s*(?:von|mit)?\s*|generate\s+(?:an?\s+)?image\s+(?:of|with)?\s*|create\s+(?:an?\s+)?image\s+(?:of|with)?\s*|draw\s+(?:an?\s+)?(?:image|picture)\s+(?:of|with)?\s*)(.+)",
        cleaned,
        re.IGNORECASE
    )
    if m_img:
        raw_prompt = m_img.group(1).strip().rstrip(".!?")
        if len(raw_prompt) >= 3:
            style = "photorealistic"
            if any(w in cleaned.lower() for w in ("gemälde", "painting", "artistic", "ölgemälde", "künstlerisch")):
                style = "artistic"
            elif any(w in cleaned.lower() for w in ("anime", "manga", "comic")):
                style = "anime"
            elif any(w in cleaned.lower() for w in ("cyberpunk", "sci-fi", "futuristisch", "neon")):
                style = "cyberpunk"
            elif any(w in cleaned.lower() for w in ("cinematic", "film", "kino", "movie")):
                style = "cinematic"
            return ("generate_ai_image", {"prompt": raw_prompt, "style": style})

    # 0.2 URL Security & SSRF Audit
    m_sec = re.search(r"(?:prüfe\s+(?:die\s+)?url\s+|check\s+url\s+|ist\s+(?:die\s+)?url\s+sicher\s+|url\s+sicherheit\s+|scan\s+url\s+)(https?://[^\s]+|[a-zA-Z0-9\.\-]+\.[a-zA-Z]{2,}[^\s]*)", cleaned, re.IGNORECASE)
    if m_sec:
        target_url = m_sec.group(1).strip()
        return ("check_url_safety", {"url": target_url})

    # 0.3 Code Interpreter & Python Sandbox Execution / Plotting
    m_py = re.search(
        r"(?:(?:führe|fuehre|starte|exec|execute|run)\s+(?:diesen\s+)?(?:python|code|skript|script)|(?:schreibe\s+(?:und\s+)?(?:führe|fuehre)\s+python)|(?:plotte|zeichne\s+diagramm|erstelle\s+diagramm|erstelle\s+plot|visualisiere\s+(?:die\s+)?daten|sinus\s+kurve\s+plotten|balkendiagramm))\s*(.*)",
        cleaned,
        re.IGNORECASE | re.DOTALL
    )
    if m_py:
        py_code = m_py.group(1).strip()
        m_block = re.search(r"```(?:python)?\s*(.*?)\s*```", cleaned, re.DOTALL)
        if m_block:
            py_code = m_block.group(1).strip()
        if py_code:
            return ("execute_python_code", {"code": py_code})

    # 0.4 Document RAG & Vector Knowledge Base
    m_rag = re.search(
        r"(?:suche\s+(?:in\s+den\s+|im\s+|in\s+der\s+)?(?:dokumenten?|vektor\s*datenbank|knowledge\s*base|wissensbasis|dateien?)|rag\s*suche\s+nach|forsche\s+in\s+dokumenten\s+nach)\s+(.+)",
        cleaned,
        re.IGNORECASE
    )
    if m_rag:
        rag_query = m_rag.group(1).strip().rstrip(".!?")
        if rag_query:
            return ("search_knowledge_base", {"query": rag_query})

    # 0.5 User Profile & Memory
    if re.search(r"(?:was\s+wei(?:ß|ss)t\s+du\s+über\s+mich|zeige\s+(?:mein\s+)?(?:profil|gedächtnis|memory)|wer\s+bin\s+ich\s+für\s+dich|meine\s+präferenzen|user\s+memory)", cleaned, re.IGNORECASE):
        return ("get_user_memory", {})

    m_mem = re.search(
        r"(?:merke\s+dir\s*:\s*|merke\s+dir\s+(?:dass\s+)?|speichere\s+(?:in\s+mein\s+profil\s*:\s*|in\s+meine\s+präferenzen\s*:\s*)|setze\s+meine\s+präferenz\s*:\s*)(.+)",
        cleaned,
        re.IGNORECASE
    )
    if m_mem:
        fact_or_pref = m_mem.group(1).strip().rstrip(".!?")
        if fact_or_pref:
            return ("update_user_memory", {"fact": fact_or_pref})

    # 0.6 GPU & System Hardware Telemetry
    if re.search(r"(?:gpu\s+auslastung|gpu\s+status|vram|wie\s+viel\s+vram|wieviel\s+vram|grafikkarte|gpu\s+telemetrie|cuda\s+status|nvidia\s+status|rocm\s+status)", cleaned, re.IGNORECASE):
        return ("get_gpu_telemetry", {})

    if re.search(r"(?:system\s+status|system\s+telemetrie|systemauslastung|festplattenspeicher|wieviel\s+ram|ram\s+auslastung|speicherauslastung|disk\s+usage|system\s+info)", cleaned, re.IGNORECASE):
        return ("get_system_info", {})

    # 0.7 Safe Workspace Filesystem
    m_files = re.search(r"(?:zeige\s+(?:alle\s+)?dateien(?:\s+in)?|list\s+files(?:\s+in)?|dateiliste(?:\s+von)?|welche\s+dateien\s+gibt\s+es(?:\s+in)?)\s*([a-zA-Z0-9\._\-\/]+)?", cleaned, re.IGNORECASE)
    if m_files:
        p = (m_files.group(1) or ".").strip()
        if p.lower() in ("im", "in", "dem", "ordner", "verzeichnis", "workspace"):
            p = "."
        return ("list_workspace_files", {"relative_path": p})

    m_read = re.search(r"(?:lies\s+(?:die\s+)?datei|zeige\s+(?:den\s+)?inhalt\s+von\s+(?:datei\s+)?|read\s+file)\s+([a-zA-Z0-9\._\-\/\\]+)", cleaned, re.IGNORECASE)
    if m_read:
        f_target = m_read.group(1).strip()
        if f_target and "." in f_target:
            return ("read_workspace_file", {"relative_path": f_target})

    # 0.8 Git Version Control & Workspace Diff
    if re.search(r"(?:git\s+status|zeige\s+git\s+status|git\s+zustand|arbeitsverzeichnis\s+status)", cleaned, re.IGNORECASE):
        return ("get_git_status", {})

    if re.search(r"(?:git\s+diff|zeige\s+git\s+diff|welche\s+änderungen\s+gibt\s+es|zeige\s+diff)", cleaned, re.IGNORECASE):
        return ("get_git_diff", {})

    if re.search(r"(?:git\s+log|zeige\s+git\s+commits|letzte\s+commits|commit\s+historie)", cleaned, re.IGNORECASE):
        return ("get_git_log", {})

    # 0.9 Code Search & Symbol Indexer
    m_grep = re.search(r"(?:suche\s+(?:im\s+code|nach\s+code|in\s+dateien)\s+nach|grep\s+search|code\s+suche)\s+(.+)", cleaned, re.IGNORECASE)
    if m_grep:
        q_code = m_grep.group(1).strip().rstrip(".!?")
        if q_code:
            return ("grep_search_code", {"query": q_code})

    m_sym = re.search(r"(?:zeige\s+symbole\s+in|extrahiere\s+symbole\s+aus|code\s+symbols\s+in)\s+([a-zA-Z0-9\._\-\/\\]+)", cleaned, re.IGNORECASE)
    if m_sym:
        f_sym = m_sym.group(1).strip()
        if f_sym and "." in f_sym:
            return ("extract_code_symbols", {"file_path": f_sym})

    # 0.10 Code Syntax & Automated Tests
    m_syntax = re.search(r"(?:prüfe\s+(?:die\s+)?syntax|syntax\s+check|validiere\s+code)\s*(.*)", cleaned, re.IGNORECASE)
    if m_syntax:
        c_syn = m_syntax.group(1).strip()
        if c_syn:
            return ("validate_code_syntax", {"code": c_syn})

    if re.search(r"(?:starte\s+tests|führe\s+tests\s+aus|run\s+tests|führe\s+pytest\s+aus|pytest\s+starten)", cleaned, re.IGNORECASE):
        return ("run_project_tests", {"framework": "pytest"})

    # 0.11 Terminal / Shell Runner
    m_term = re.search(r"^(?:terminal(?:\s+run)?|exec|bash|shell|führe\s+(?:den\s+)?befehl\s+aus|run\s+command)\s*:\s*(.+)", cleaned, re.IGNORECASE)
    if not m_term:
        m_term = re.search(r"^(?:terminal|bash|shell)\s+(.+)", cleaned, re.IGNORECASE)
    if m_term:
        cmd_str = m_term.group(1).strip()
        if cmd_str:
            return ("run_terminal_command", {"command": cmd_str})

    # 0.12 Universal HTTP API Client
    m_http = re.search(r"^(?:curl|http\s+get|http\s+post|http\s+request|api\s+request|api\s+call)\s+(https?://[^\s]+)(?:\s+(.+))?", cleaned, re.IGNORECASE)
    if m_http:
        target_url = m_http.group(1).strip()
        extra_body = m_http.group(2)
        method = "POST" if "post" in cleaned.lower()[:15] else "GET"
        args_dict = {"url": target_url, "method": method}
        if extra_body:
            args_dict["body"] = extra_body.strip()
        return ("execute_http_request", args_dict)

    # 0.13 GitHub Integration Suite
    # GitHub PR Diff: e.g. "github pr diff 42 von owner/repo" or "gh diff owner/repo 42"
    m_gh_diff = re.search(r"(?:github\s+pr\s+diff|gh\s+diff)\s+(?:#?(\d+)\s+(?:von\s+|in\s+)?([a-zA-Z0-9_\-\.]+)/([a-zA-Z0-9_\-\.]+)|([a-zA-Z0-9_\-\.]+)/([a-zA-Z0-9_\-\.]+)\s+#?(\d+))", cleaned, re.IGNORECASE)
    if m_gh_diff:
        if m_gh_diff.group(1):
            pr_num = int(m_gh_diff.group(1))
            gh_owner = m_gh_diff.group(2)
            gh_repo = m_gh_diff.group(3)
        else:
            gh_owner = m_gh_diff.group(4)
            gh_repo = m_gh_diff.group(5)
            pr_num = int(m_gh_diff.group(6))
        return ("github_get_pull_request_diff", {"owner": gh_owner, "repo": gh_repo, "pull_number": pr_num})

    # GitHub Issues: e.g. "github issues von owner/repo" or "gh issues owner/repo"
    m_gh_issues = re.search(r"(?:github\s+issues?\s+(?:von\s+|für\s+|in\s+)?|gh\s+issues?\s+)([a-zA-Z0-9_\-\.]+)/([a-zA-Z0-9_\-\.]+)(?:\s+#?(\d+))?", cleaned, re.IGNORECASE)
    if m_gh_issues:
        gh_owner = m_gh_issues.group(1)
        gh_repo = m_gh_issues.group(2)
        iss_num = m_gh_issues.group(3)
        if iss_num:
            return ("github_get_issue", {"owner": gh_owner, "repo": gh_repo, "issue_number": int(iss_num)})
        return ("github_list_issues", {"owner": gh_owner, "repo": gh_repo})

    # GitHub Pull Requests: e.g. "github prs von owner/repo" or "github pr #12 von owner/repo"
    m_gh_prs = re.search(r"(?:github\s+prs?\s+(?:von\s+|für\s+|in\s+)?|gh\s+prs?\s+|pull\s+requests?\s+(?:von\s+|für\s+|in\s+)?)([a-zA-Z0-9_\-\.]+)/([a-zA-Z0-9_\-\.]+)(?:\s+#?(\d+))?", cleaned, re.IGNORECASE)
    if m_gh_prs:
        gh_owner = m_gh_prs.group(1)
        gh_repo = m_gh_prs.group(2)
        pr_num = m_gh_prs.group(3)
        if pr_num:
            return ("github_get_pull_request", {"owner": gh_owner, "repo": gh_repo, "pull_number": int(pr_num)})
        return ("github_list_pull_requests", {"owner": gh_owner, "repo": gh_repo})

    # GitHub Releases: e.g. "github releases von owner/repo" or "latest release von owner/repo"
    m_gh_rel = re.search(r"(?:github\s+releases?\s+(?:von\s+|für\s+|in\s+)?|latest\s+release\s+(?:von\s+|für\s+|in\s+)?|gh\s+releases?\s+)([a-zA-Z0-9_\-\.]+)/([a-zA-Z0-9_\-\.]+)", cleaned, re.IGNORECASE)
    if m_gh_rel:
        return ("github_list_releases", {"owner": m_gh_rel.group(1), "repo": m_gh_rel.group(2)})

    # GitHub Actions / Workflows: e.g. "github actions von owner/repo" or "ci runs owner/repo"
    m_gh_ci = re.search(r"(?:github\s+(?:actions|workflows|ci(?:\/cd)?)\s+(?:von\s+|für\s+|in\s+)?|gh\s+actions\s+)([a-zA-Z0-9_\-\.]+)/([a-zA-Z0-9_\-\.]+)", cleaned, re.IGNORECASE)
    if m_gh_ci:
        return ("github_get_workflow_runs", {"owner": m_gh_ci.group(1), "repo": m_gh_ci.group(2)})

    # GitHub Repo info: e.g. "github repo owner/repo" or "zeige github repo owner/repo"
    m_gh_repo = re.search(r"(?:github\s+(?:repo(?:sitory)?|info)\s+(?:von\s+|über\s+|zu\s+)?|gh\s+repo\s+)([a-zA-Z0-9_\-\.]+)/([a-zA-Z0-9_\-\.]+)", cleaned, re.IGNORECASE)
    if m_gh_repo:
        return ("github_get_repo", {"owner": m_gh_repo.group(1), "repo": m_gh_repo.group(2)})

    # GitHub Repo Search: e.g. "suche github repos <query>"
    m_gh_search = re.search(r"(?:suche\s+github\s+repos?(?:itories)?\s+(?:nach\s+)?|search\s+github\s+repos?(?:itories)?\s+)(.+)", cleaned, re.IGNORECASE)
    if m_gh_search:
        q_gh = m_gh_search.group(1).strip().rstrip(".!?")
        if q_gh:
            return ("github_search_repositories", {"query": q_gh})

    # 0.14 System & Workspace Doctor
    if re.search(r"(?:^doctor\b|system\s+doctor|workspace\s+doctor|system\s+diagnose|diagnose\s+ausführen|prüfe\s+(?:mein\s+)?system|run\s+doctor)", cleaned, re.IGNORECASE):
        return ("run_doctor_diagnostics", {})

    # 0.15 Workspace Quarantine
    if re.search(r"(?:commit\s+quarantine|quarantäne\s+übernehmen|quarantäne\s+anwenden)\s*([a-zA-Z0-9_\-]+)?", cleaned, re.IGNORECASE):
        m_q_c = re.search(r"(?:commit\s+quarantine|quarantäne\s+übernehmen|quarantäne\s+anwenden)\s*([a-zA-Z0-9_\-]+)?", cleaned, re.IGNORECASE)
        t_id = m_q_c.group(1) if m_q_c and m_q_c.group(1) else "latest"
        return ("quarantine_commit", {"txn_id": t_id})

    if re.search(r"(?:rollback\s+quarantine|quarantäne\s+verwerfen|quarantäne\s+abbrechen)\s*([a-zA-Z0-9_\-]+)?", cleaned, re.IGNORECASE):
        m_q_r = re.search(r"(?:rollback\s+quarantine|quarantäne\s+verwerfen|quarantäne\s+abbrechen)\s*([a-zA-Z0-9_\-]+)?", cleaned, re.IGNORECASE)
        t_id = m_q_r.group(1) if m_q_r and m_q_r.group(1) else "latest"
        return ("quarantine_rollback", {"txn_id": t_id})

    # 0.16 Structured Mission Journal
    m_mission = re.search(r"(?:starte\s+mission\s*:\s*|start\s+mission\s*:\s*|neue\s+mission\s*:\s*)(.+)", cleaned, re.IGNORECASE)
    if m_mission:
        m_obj = m_mission.group(1).strip()
        if m_obj:
            return ("mission_start", {"objective": m_obj})

    m_mission_status = re.search(r"(?:mission\s+status|zeige\s+mission|mission\s+journal)\s*([a-zA-Z0-9_\-]+)?", cleaned, re.IGNORECASE)
    if m_mission_status:
        m_id = m_mission_status.group(1)
        if m_id:
            return ("mission_get_summary", {"mission_id": m_id})

    # 0.17 Tool Scanner & Installer
    if re.search(r"(?:prüfe\s+(?:fehlende\s+)?tools|check\s+tools|welche\s+tools\s+fehlen|missing\s+tools)", cleaned, re.IGNORECASE):
        return ("detect_missing_tools", {})

    m_install = re.search(r"(?:installiere\s+(?:das\s+)?tool|install\s+tool)\s+([a-zA-Z0-9_\-]+)", cleaned, re.IGNORECASE)
    if m_install:
        t_name = m_install.group(1).strip()
        if t_name:
            return ("install_dev_tool", {"tool_name": t_name})

    # 0.18 Android Edge Node & ADB Bridge
    if re.search(r"(?:adb\s+devices|zeige\s+android\s+geräte|verbundene\s+smartphones|connected\s+android\s+devices|adb\s+liste)", cleaned, re.IGNORECASE):
        return ("adb_list_devices", {})

    if re.search(r"(?:adb\s+screenshot|android\s+screenshot|mache\s+screenshot\s+vom\s+handy|capture\s+device\s+screen)", cleaned, re.IGNORECASE):
        return ("adb_capture_screenshot", {})

    if re.search(r"(?:adb\s+logcat|android\s+logcat|system\s+logcat)", cleaned, re.IGNORECASE):
        return ("adb_get_system_log", {})

    # 0.19 Deployed WebApps and Games
    if re.search(r"(?:welche\s+webapps|welche\s+apps\s+sind\s+gehostet|zeige\s+apps|list\s+webapps|gehostete\s+spiele|installierte\s+webapps)", cleaned, re.IGNORECASE):
        return ("list_deployed_webapps", {})

    # 1. Currency Conversion & Cryptocurrency Exchanges (e.g. "100 EUR in USD, GBP und JPY", "Wie viel sind 500 Dollar in Euro")
    m_curr = re.search(
        r"(?:(?:rechne|konvertiere|währungsumrechnung|wechselkurs)\s+(?:von\s+)?|wie\s+viel(?:e)?\s+sind\s+)?([\d.,]+)\s*([a-zA-ZäöüÄÖÜß\$\€\£\¥\s\-]{2,15})\s*(?:in|to|zu|nach)\s*([a-zA-ZäöüÄÖÜß\$\€\£\¥\s\-,&+]+)",
        cleaned,
        re.IGNORECASE
    )
    if m_curr:
        raw_amt = m_curr.group(1).replace(",", ".")
        raw_from = m_curr.group(2).strip()
        raw_to = m_curr.group(3).strip()
        # Avoid matching distance queries like "100 km in Meilen" if not currency
        non_curr_words = {"km", "kilometer", "m", "meter", "cm", "kg", "gramm", "stunden", "minuten", "sekunden", "grad", "celsius", "fahrenheit"}
        if raw_from.lower() not in non_curr_words and raw_to.lower() not in non_curr_words:
            try:
                amt_val = float(raw_amt)
                return ("convert_currency", {"amount": amt_val, "from_currency": raw_from, "to_currency": raw_to, "query": cleaned})
            except ValueError:
                pass

    # 2. Geographic Distance, Route & Travel Time (e.g. "Entfernung von Berlin nach München", "Wie weit ist es von Köln nach Hamburg")
    m_dist = re.search(
        r"(?:(?:wie\s+weit\s+ist\s+es|entfernung|distanz|strecke|route|fahrzeit|reisezeit)\s+(?:von|zwischen)?\s*|fahrtstrecke\s+(?:von\s+)?)([a-zA-ZäöüÄÖÜß\s\-]+?)\s*(?:nach|und|bis|zu|->)\s*([a-zA-ZäöüÄÖÜß\s\-]+)",
        cleaned,
        re.IGNORECASE
    )
    if m_dist:
        orig = m_dist.group(1).strip()
        dest = m_dist.group(2).strip().rstrip("?.!")
        orig = re.sub(r"^(?:von|ab|start)\s+", "", orig, flags=re.IGNORECASE).strip()
        if orig and dest and len(orig) >= 2 and len(dest) >= 2:
            return ("get_distance_route", {"origin": orig, "destination": dest, "query": cleaned})

    # 3. World Bank Macroeconomic Data (e.g. "BIP von Deutschland, Frankreich und USA", "Inflation in Japan", "Wirtschaftsdaten von Brasilien")
    m_econ = re.search(
        r"(?:(?:bip|gdp|bruttoinlandsprodukt|bip\s+pro\s+kopf|inflation|inflationsrate|teuerung|wirtschaftsleistung|lebenserwartung|co2\s+emissionen)\s+(?:von|in|für|fuer)\s+|weltbank\s+daten\s+(?:zu|für|von)\s+)([a-zA-ZäöüÄÖÜß\s\-,&+]+)",
        cleaned,
        re.IGNORECASE
    )
    if m_econ:
        c_target = m_econ.group(1).strip().rstrip("?.!")
        if len(c_target) >= 2:
            return ("get_world_bank_stats", {"country": c_target, "query": cleaned})

    # 4. Country Demographics & Geographic Facts (e.g. "Fakten über Deutschland und Frankreich", "Hauptstadt von Australien", "Einwohnerzahl von Japan")
    m_country = re.search(
        r"(?:(?:fakten\s+über|fakten\s+zu|länderdaten\s+(?:von|zu)|länderinfo\s+(?:von|zu)|landesinfo\s+(?:von|zu)|infos\s+über|daten\s+zu|hauptstadt\s+von|wie\s+viele\s+einwohner\s+hat|einwohnerzahl\s+von)\s+)([a-zA-ZäöüÄÖÜß\s\-,&+]+)",
        cleaned,
        re.IGNORECASE
    )
    if m_country:
        c_target = m_country.group(1).strip().rstrip("?.!")
        if len(c_target) >= 2:
            return ("lookup_country_data", {"country": c_target})

    # 5. World Clocks & Timezone Conversions (e.g. "Wie spät ist es in New York, Tokio und Berlin?", "Uhrzeit in London und Sydney")
    m_world_time = re.search(
        r"(?:(?:wie\s+spät\s+ist\s+es\s+in|wieviel\s+uhr\s+ist\s+es\s+in|aktuelle\s+uhrzeit\s+in|uhrzeit\s+in|zeit\s+in|lokalzeit\s+in)\s+)([a-zA-ZäöüÄÖÜß\s\-,&+]+)",
        cleaned,
        re.IGNORECASE
    )
    if m_world_time:
        loc_target = m_world_time.group(1).strip().rstrip("?.!")
        if len(loc_target) >= 2:
            return ("get_current_time_calendar", {"city": loc_target})

    # 6. Live Weather & Multi-City Forecast (e.g. "Wie ist das Wetter in Berlin, Hamburg und München?")
    m_weather = re.search(
        r"(?:(?:wie\s+(?:ist|wird|ist\s+denn|wird\s+denn)\s+)?(?:das\s+)?wetter\s+(?:heute\s+|morgen\s+|aktuell\s+)?(?:in|für|fuer|von|bei|im|am)\s+|weather\s+(?:in|for)?\s*|temperatur\s+(?:in|von|bei)?\s*|regnet\s+es\s+in\s*)([a-zA-ZäöüÄÖÜß\s\-,\+&]+?)(?:\s+wird|\s+ist|\?|\.|$|\s+heute|\s+morgen|\s+aktuell|\s+am\s+wochenende)",
        cleaned,
        re.IGNORECASE
    )
    if m_weather:
        loc = m_weather.group(1).strip()
        loc = re.sub(r"^(?:den|dem|der|die|das|in|für|fuer|von|bei)\s+", "", loc, flags=re.IGNORECASE).strip()
        loc = re.sub(r"\s+(?:wird|ist|heute|morgen|aktuell)$", "", loc, flags=re.IGNORECASE).strip()
        if loc and len(loc) >= 2:
            return ("get_current_weather", {"location": loc})

    m_city = re.search(r"(?:wetter|weather|temperatur|regen|sonnig|klima).+?(?:in|für|fuer|bei|nach)\s+([a-zA-ZäöüÄÖÜß\-,\+&\s]+)", cleaned, re.IGNORECASE)
    if m_city:
        loc = m_city.group(1).strip().rstrip("?.!")
        if loc and len(loc) >= 2 and loc.lower() not in {"heute", "morgen", "deutschland", "bayern", "wird", "ist"}:
            return ("get_current_weather", {"location": loc})

    if re.search(r"(?:wie\s+(?:ist|wird)\s+das\s+wetter|wetterbericht|aktuelles\s+wetter|wetter\s+heute|wetter\s+morgen|wie\s+warm\s+ist\s+es|weather\s+today|wetter\?|\bwetter\b)", cleaned, re.IGNORECASE):
        return ("get_current_weather", {"location": "Veitshöchheim"})

    # 7. Market / Stock / Crypto Quotes (e.g. "BTC, ETH und SOL", "Aktienkurs von NVIDIA, Apple und Microsoft")
    found_symbols = []
    if re.search(r"\b(?:bitcoin|btc)\b", cleaned, re.IGNORECASE):
        found_symbols.append("BTC")
    if re.search(r"\b(?:ethereum|eth)\b", cleaned, re.IGNORECASE):
        found_symbols.append("ETH")
    if re.search(r"\b(?:solana|sol)\b", cleaned, re.IGNORECASE):
        found_symbols.append("SOL")
    if re.search(r"\b(?:ripple|xrp)\b", cleaned, re.IGNORECASE):
        found_symbols.append("XRP")
    if re.search(r"\b(?:cardano|ada)\b", cleaned, re.IGNORECASE):
        found_symbols.append("ADA")
    if re.search(r"\b(?:nvidia|nvda)\b", cleaned, re.IGNORECASE):
        found_symbols.append("NVDA")
    if re.search(r"\b(?:apple|aapl)\b", cleaned, re.IGNORECASE):
        found_symbols.append("AAPL")
    if re.search(r"\b(?:microsoft|msft)\b", cleaned, re.IGNORECASE):
        found_symbols.append("MSFT")

    if len(found_symbols) > 1:
        return ("get_market_quote", {"symbol": " und ".join(found_symbols)})
    elif len(found_symbols) == 1:
        return ("get_market_quote", {"symbol": found_symbols[0]})

    m_market = re.search(
        r"(?:aktienkurs\s+von\s+|aktienkurs\s+|aktie\s+|kurs\s+von\s+|preis\s+von\s+|wie\s+steht\s+(?:die\s+aktie\s+)?|stock\s+price\s+(?:of\s+)?|crypto\s+price\s+(?:of\s+)?)([a-zA-Z0-9\.\-\s,\+&]+?)(?:\?|\.|$|\s+aktuell)",
        cleaned,
        re.IGNORECASE
    )
    if m_market:
        sym = m_market.group(1).strip().rstrip("?.!")
        if sym:
            return ("get_market_quote", {"symbol": sym})

    # 8. Time / Calendar / Holidays (General)
    if re.search(r"(?:wie\s+spät\s+ist\s+es|wieviel\s+uhr\s+ist\s+es|aktuelle\s+uhrzeit|welcher\s+tag\s+ist\s+heute|welches\s+datum|wann\s+ist\s+ostern|feiertage\s+in|feiertage\s+\d{4}|current\s+time|what\s+time\s+is\s+it)", cleaned, re.IGNORECASE):
        return ("get_current_time_calendar", {})

    # 9. Math / Calculation
    m_calc = re.search(r"(?:berechne\s+|was\s+ist\s+)(\d+[\d\s\+\-\*\/\^\(\)\.\,\%]+)(?:\?|\.|$)", cleaned, re.IGNORECASE)
    if m_calc:
        expr = m_calc.group(1).strip()
        if any(op in expr for op in ("+", "-", "*", "/", "^", "%")):
            return ("calculate_math", {"expression": expr})

    # 10. News Feed & Headlines from Portals (Spiegel, Tagesschau, Heise, General News with Typo Tolerance)
    m_portal_news = re.search(
        r"(?:(?:die\s+|die\s+aktuellen\s+|aktuelle\s+)?(?:headlines|schlagzeilen|nachrichten|news|top\s+news|artikel)\s+(?:von\s+|aus\s+|auf\s+|bei\s+)?|was\s+gibt\s+es\s+neues\s+(?:bei\s+|auf\s+)?)\s*([a-zA-ZäöüÄÖÜß\s\-,\+&]+)",
        cleaned,
        re.IGNORECASE
    )
    if m_portal_news:
        portal = m_portal_news.group(1).strip().rstrip("?.!")
        if any(p in portal.lower() for p in ("spiegel", "tagesschau", "heise", "golem", "zeit", "faz", "welt", "focus", "sueddeutsche", "krypto", "crypto", "tech", "wirtschaft")):
            return ("get_live_news", {"topic": portal})

    if any(re.search(rf"\b{p}\b", cleaned, re.IGNORECASE) for p in ("spiegel", "tagesschau", "heise", "zeit", "faz", "welt", "focus", "sueddeutsche")) and any(w in cleaned.lower() for w in ("headline", "schlagzeil", "nachricht", "news", "aktuell", "heute", "artikel", "titel")):
        matched_portals = [p_name for p_name in ("spiegel", "tagesschau", "heise", "zeit", "faz", "welt", "focus", "sueddeutsche") if re.search(rf"\b{p_name}\b", cleaned, re.IGNORECASE)]
        if matched_portals:
            return ("get_live_news", {"topic": " und ".join(matched_portals)})
        return ("get_live_news", {"topic": "tagesschau"})

    # General News / Typo-Tolerant News Queries (e.g. "Was bits neues jn den Nachrichten", "Was gibt es Neues", "Aktuelle News")
    m_general_news = re.search(
        r"(?:was\s+(?:gibt'?s?|gibts|bits?|bit'?s?|geht|gehts|is|ist|steht)(?:\s+es)?\s+neu(?:es)?|aktuelle\s+(?:nachrichten|news|schlagzeilen|meldungen|berichte)|nachrichten\s+(?:von\s+|aus\s+|in\s+|für\s+|fuer\s+)?heute|news\s+(?:von\s+|aus\s+|in\s+|für\s+|fuer\s+)?heute|schlagzeilen(?:\s+von)?\s+heute|top\s+news|breaking\s+news|what'?s\s+new(?:\s+in\s+the\s+news)?|latest\s+news)",
        cleaned,
        re.IGNORECASE
    )
    if m_general_news or ("nachricht" in cleaned.lower() and any(w in cleaned.lower() for w in ("neu", "aktuell", "heute", "was", "gibt", "bit", "schlagzeil", "world", "deutschland", "jn", "in"))):
        return ("get_live_news", {"topic": "tagesschau"})


    # 11. Events, Concerts, Subculture & Regional Discovery (Worldwide & Europe with typo tolerance)
    if re.search(r"(?:kon[tz]+ert[a-z]*|con[cz]i?ert[a-z]*|veranstalt[a-z]*|verantstalt[a-z]*|events?|part[yi]e?s?|gigs?|festivals?|live[\s\-_]?musik|live[\s\-_]?music|was\s+geht|things\s+to\s+do|what\s+to\s+do|what'?s\s+(?:on|happening|going\s+on)|what\s+is\s+on|live[\s\-_]?bands?|bands\s+live|ausgehen|kulturprogramm|spielplan|clubbing|disco|disko|nightlife|klapperfeld|subkultur|kulturzentrum|off-space|b\u00fcrgerhaus|scheune|dorfgemeinschaftshaus|kleinkunst|freiraum|autonomes?\s+zentrum|tiers-lieux|friche|squat|grassroots)", cleaned, re.IGNORECASE):
        city_aliases = {
            "wue": "Würzburg",
            "wü": "Würzburg",
            "wuerzburg": "Würzburg",
            "würzburg": "Würzburg",
            "würzburger": "Würzburg",
            "münchen": "München",
            "munich": "München",
            "muc": "München",
            "münchner": "München",
            "nürnberg": "Nürnberg",
            "nuernberg": "Nürnberg",
            "nürnberger": "Nürnberg",
            "schweinfurt": "Schweinfurt",
            "veitshöchheim": "Veitshöchheim",
            "veitshoechheim": "Veitshöchheim",
            "frankfurt": "Frankfurt am Main",
            "ffm": "Frankfurt am Main",
            "berlin": "Berlin",
            "hamburg": "Hamburg",
            "stuttgart": "Stuttgart",
            "köln": "Köln",
            "koeln": "Köln",
            "cologne": "Köln",
            "dresden": "Dresden",
            "leipzig": "Leipzig",
            "augsburg": "Augsburg",
            "regensburg": "Regensburg",
            "bamberg": "Bamberg",
            "erlangen": "Erlangen",
            "kitzingen": "Kitzingen",
            "aschaffenburg": "Aschaffenburg",
            "lohr": "Lohr",
            "karlstadt": "Karlstadt",
            "ochsenfurt": "Ochsenfurt",
            "marktheidenfeld": "Marktheidenfeld",
            "bad-kissingen": "Bad Kissingen",
            "düsseldorf": "Düsseldorf",
            "duesseldorf": "Düsseldorf",
            "dortmund": "Dortmund",
            "essen": "Essen",
            "bremen": "Bremen",
            "hannover": "Hannover",
            "duisburg": "Duisburg",
            "bochum": "Bochum",
            "wuppertal": "Wuppertal",
            "bielefeld": "Bielefeld",
            "bonn": "Bonn",
            "münster": "Münster",
            "karlsruhe": "Karlsruhe",
            "mannheim": "Mannheim",
            "wiesbaden": "Wiesbaden",
            "gelsenkirchen": "Gelsenkirchen",
            "mönchengladbach": "Mönchengladbach",
            "braunschweig": "Braunschweig",
            "chemnitz": "Chemnitz",
            "kiel": "Kiel",
            "aachen": "Aachen",
            "halle": "Halle (Saale)",
            "magdeburg": "Magdeburg",
            "freiburg": "Freiburg im Breisgau",
            "krefeld": "Krefeld",
            "mainz": "Mainz",
            "lübeck": "Lübeck",
            "erfurt": "Erfurt",
            "oberhausen": "Oberhausen",
            "rostock": "Rostock",
            "kassel": "Kassel",
            "potsdam": "Potsdam",
            "saarbrücken": "Saarbrücken",
            "heidelberg": "Heidelberg",
            "darmstadt": "Darmstadt",
            "ulm": "Ulm",
            "wien": "Wien",
            "vienna": "Wien",
            "zürich": "Zürich",
            "zurich": "Zürich",
            "zuerich": "Zürich",
            "salzburg": "Salzburg",
            "innsbruck": "Innsbruck",
            "graz": "Graz",
            "linz": "Linz",
            "basel": "Basel",
            "bern": "Bern",
            "genf": "Genf",
            "geneva": "Genf",
            "lausanne": "Lausanne",
            "london": "London",
            "manchester": "Manchester",
            "birmingham": "Birmingham",
            "liverpool": "Liverpool",
            "leeds": "Leeds",
            "glasgow": "Glasgow",
            "edinburgh": "Edinburgh",
            "bristol": "Bristol",
            "cardiff": "Cardiff",
            "belfast": "Belfast",
            "paris": "Paris",
            "lyon": "Lyon",
            "marseille": "Marseille",
            "bordeaux": "Bordeaux",
            "toulouse": "Toulouse",
            "nice": "Nizza",
            "nizza": "Nizza",
            "nantes": "Nantes",
            "strasbourg": "Straßburg",
            "straßburg": "Straßburg",
            "lille": "Lille",
            "madrid": "Madrid",
            "barcelona": "Barcelona",
            "valencia": "Valencia",
            "sevilla": "Sevilla",
            "seville": "Sevilla",
            "bilbao": "Bilbao",
            "malaga": "Málaga",
            "zaragoza": "Zaragoza",
            "rom": "Rom",
            "rome": "Rom",
            "roma": "Rom",
            "milan": "Mailand",
            "mailand": "Mailand",
            "milano": "Mailand",
            "napoli": "Neapel",
            "neapel": "Neapel",
            "torino": "Turin",
            "turin": "Turin",
            "bologna": "Bologna",
            "firenze": "Florenz",
            "florenz": "Florenz",
            "venezia": "Venedig",
            "venedig": "Venedig",
            "amsterdam": "Amsterdam",
            "rotterdam": "Rotterdam",
            "den-haag": "Den Haag",
            "utrecht": "Utrecht",
            "eindhoven": "Eindhoven",
            "brüssel": "Brüssel",
            "brussels": "Brüssel",
            "bruxelles": "Brüssel",
            "antwerpen": "Antwerpen",
            "gent": "Gent",
            "lüttich": "Lüttich",
            "liege": "Lüttich",
            "dublin": "Dublin",
            "prag": "Prag",
            "prague": "Prag",
            "praha": "Prag",
            "brno": "Brünn",
            "warschau": "Warschau",
            "warsaw": "Warschau",
            "warszawa": "Warschau",
            "krakow": "Krakau",
            "krakau": "Krakau",
            "wroclaw": "Breslau",
            "breslau": "Breslau",
            "poznan": "Posen",
            "gdansk": "Danzig",
            "budapest": "Budapest",
            "lissabon": "Lissabon",
            "lisbon": "Lissabon",
            "lisboa": "Lissabon",
            "porto": "Porto",
            "athen": "Athen",
            "athens": "Athen",
            "thessaloniki": "Thessaloniki",
            "stockholm": "Stockholm",
            "gothenburg": "Göteborg",
            "göteborg": "Göteborg",
            "malmo": "Malmö",
            "malmö": "Malmö",
            "oslo": "Oslo",
            "bergen": "Bergen",
            "kopenhagen": "Kopenhagen",
            "copenhagen": "Kopenhagen",
            "aarhus": "Aarhus",
            "helsinki": "Helsinki",
            "tallinn": "Tallinn",
            "riga": "Riga",
            "vilnius": "Vilnius",
            "zagreb": "Zagreb",
            "split": "Split",
            "belgrad": "Belgrad",
            "belgrade": "Belgrad",
            "bukarest": "Bukarest",
            "bucharest": "Bukarest",
            "sofia": "Sofia",
            "tokio": "Tokio",
            "tokyo": "Tokio",
            "osaka": "Osaka",
            "kyoto": "Kyoto",
            "seoul": "Seoul",
            "peking": "Peking",
            "beijing": "Peking",
            "shanghai": "Shanghai",
            "hongkong": "Hongkong",
            "singapur": "Singapur",
            "singapore": "Singapur",
            "bangkok": "Bangkok",
            "mumbai": "Mumbai",
            "delhi": "Delhi",
            "new-delhi": "Neu-Delhi",
            "sydney": "Sydney",
            "melbourne": "Melbourne",
            "brisbane": "Brisbane",
            "auckland": "Auckland",
            "new-york": "New York",
            "new york": "New York",
            "nyc": "New York",
            "los-angeles": "Los Angeles",
            "los angeles": "Los Angeles",
            "chicago": "Chicago",
            "san-francisco": "San Francisco",
            "san francisco": "San Francisco",
            "toronto": "Toronto",
            "montreal": "Montreal",
            "vancouver": "Vancouver",
            "mexiko-stadt": "Mexiko-Stadt",
            "mexico-city": "Mexiko-Stadt",
            "buenos-aires": "Buenos Aires",
            "sao-paulo": "São Paulo",
            "rio": "Rio de Janeiro",
            "rio-de-janeiro": "Rio de Janeiro",
            "kairo": "Kairo",
            "cairo": "Kairo",
            "kapstadt": "Kapstadt",
            "cape-town": "Kapstadt",
            "johannesburg": "Johannesburg",
            "istanbul": "Istanbul",
            "dubai": "Dubai",
        }

        city = "Würzburg"
        found_city = None
        for token in re.findall(r"[a-zA-ZäöüÄÖÜß\-]+", cleaned.lower()):
            if token in city_aliases:
                found_city = city_aliases[token]
                break

        if found_city:
            city = found_city
        else:
            m_city_ev = re.search(
                r"(?:in|at|near|around|à|a|en|para|für|fuer|im\s+raum|bei|aus)\s+([a-zA-ZäöüÄÖÜß\s\-]+?)(?:\?|\.|$|\s+heute|\s+morgen|\s+am\s+wochenende|\s+dieses\s+wochenende|\s+today|\s+tonight|\s+this\s+weekend)",
                cleaned,
                re.IGNORECASE
            )
            if m_city_ev:
                extracted = m_city_ev.group(1).strip()
                extracted = re.sub(r"^(?:den|dem|der|die|das|the|le|la|les|el|los|las)\s+", "", extracted, flags=re.IGNORECASE).strip()
                if extracted and len(extracted) >= 2 and extracted.lower() not in ("wochenende", "samstag", "sonntag", "freitag", "diesem", "dieser", "der", "dem", "einem", "weekend", "today", "tonight"):
                    city = extracted

        categories = []
        if re.search(r"(?:kon[tz]+ert|con[cz]i?ert|live[\s\-_]?musik|live[\s\-_]?music|live[\s\-_]?band|gigs?|band)", cleaned, re.IGNORECASE):
            categories.append("concert")
        elif re.search(r"(?:part[yi]e?s?|club|feiern|disko|disco|clubbing|nightlife)", cleaned, re.IGNORECASE):
            categories.append("party_club")
        elif re.search(r"(?:theater|schauspiel|bühne|stage|comedy|kabarett)", cleaned, re.IGNORECASE):
            categories.append("theater_stage")

        day_scope = "today_tomorrow"
        if re.search(r"\b(?:heute|today|heutige|tonight)\b", cleaned, re.IGNORECASE):
            day_scope = "today"

        radius_km = 50.0
        m_rad = re.search(r"(?:umkreis\s+(?:von\s+)?|radius\s+(?:von\s+)?|in\s+(\d+)\s*km)(\d+)?\s*km?", cleaned, re.IGNORECASE)
        if m_rad:
            try:
                rad_val = float(m_rad.group(1) or m_rad.group(2) or 50.0)
                if 1 <= rad_val <= 300:
                    radius_km = rad_val
            except (ValueError, TypeError):
                pass

        return ("search_events", {
            "city": city,
            "radius_km": radius_km,
            "categories": categories,
            "day_scope": day_scope,
        })

    # 12. Wikipedia & Encyclopedia (e.g. "Wer war Albert Einstein?", "Wer waren Einstein und Newton?", "Was ist Quantenphysik?")
    m_wiki = re.search(r"(?:wer\s+war\s+|wer\s+waren\s+|wer\s+ist\s+|wer\s+sind\s+|was\s+ist\s+(?:ein\s+|eine\s+|der\s+|die\s+|das\s+)?|was\s+sind\s+|wikipedia\s+(?:zu\s+|über\s+)?)([a-zA-Z0-9äöüÄÖÜß\s\-,\+&]+?)(?:\?|\.|$|\s+auf\s+wikipedia)", cleaned, re.IGNORECASE)
    if m_wiki:
        topic = m_wiki.group(1).strip().rstrip("?.!")
        visual_words = ("bild", "foto", "screenshot", "grafik", "steht da", "erkenn", "lies", "dokument", "pdf", "sehen")
        is_visual = any(w in cleaned.lower() for w in visual_words)
        stop_words = {
            "da", "dort", "hier", "das", "es", "dies", "dieses", "jenes", "darin", "daraus",
            "los", "passiert", "geschehen", "neu", "neues", "jetzt", "gerade", "zuletzt",
            "als letztes", "als naechstes", "als nächstes", "denn", "eigentlich", "losgewesen",
            "ueberhaupt", "überhaupt", "vorgefallen", "los gewesen", "losgeworden", "los ist"
        }
        topic_lower = topic.lower().strip()
        has_stop = any(topic_lower == sw or topic_lower.startswith(f"{sw} ") or f" {sw} " in f" {topic_lower} " for sw in stop_words)
        if len(topic) >= 3 and not is_visual and not has_stop and not topic.lower().startswith("das wetter") and not any(op in topic for op in ("+", "*", "/")):
            return ("get_wikipedia_summary", {"query": topic})

    # 13. Web Search & Google Queries
    m_search = re.search(
        r"(?:google\s+(?:nach\s+|mal\s+)?|suche\s+(?:im\s+web\s+)?(?:nach\s+)?|search\s+(?:web\s+)?(?:for\s+)?|finde\s+(?:im\s+web\s+)?|web\s*suche\s+(?:nach\s+)?)(.+?)(?:\?|\.|$)",
        cleaned,
        re.IGNORECASE
    )
    if m_search:
        q = m_search.group(1).strip()
        if q:
            return ("search_web", {"query": q})

    # 14. Deep Multi-Source Knowledge Research
    m_deep = re.search(
        r"(?:recherchier(?:e|en|t)?\s+(?:mal\s+|über\s+|ueber\s+|zu\s+)?|tiefenrecherche\s+(?:zu\s+|über\s+|ueber\s+)?|forsche\s+(?:nach\s+|über\s+|ueber\s+)?|deep\s+research\s+(?:on|about|for)?|hintergründe\s+zu\s+|aktueller\s+stand\s+(?:zu|in|bei)\s+|was\s+ist\s+der\s+aktuelle\s+stand\s+(?:zu|in|bei)\s+)(.+?)(?:\?|\.|$)",
        cleaned,
        re.IGNORECASE
    )
    if m_deep:
        topic_target = m_deep.group(1).strip()
        if topic_target and len(topic_target) >= 2:
            return ("cross_source_knowledge_search", {"query": topic_target})

    # 15. Chronological Timeline & History of Events
    m_time_ev = re.search(
        r"(?:zeitleiste\s+(?:zu\s+|von\s+)?|chronologie\s+(?:zu\s+|von\s+)?|timeline\s+(?:of|for)?|verlauf\s+von\s+|ereignisse\s+in\s+)(.+?)(?:\?|\.|$)",
        cleaned,
        re.IGNORECASE
    )
    if m_time_ev:
        tl_target = m_time_ev.group(1).strip()
        if tl_target:
            return ("fetch_recent_timeline", {"topic": tl_target})

    # 16. Multi-Source Fact Check
    m_fact = re.search(
        r"(?:stimmt\s+es\s+dass\s+|ist\s+es\s+wahr\s+dass\s+|überprüfe\s+(?:die\s+aussage\s+|den\s+fakt\s+)?|faktenprüfung\s+(?:zu\s+)?|fact\s*check\s*)(.+?)(?:\?|\.|$)",
        cleaned,
        re.IGNORECASE
    )
    if m_fact:
        claim_target = m_fact.group(1).strip()
        if claim_target:
            return ("verify_fact_multi_source", {"claim": claim_target})

    # 17. Chemical Compound & Molecular Properties (PubChem)
    m_chem = re.search(
        r"(?:(?:chemische\s+(?:formel|eigenschaften|struktur)|summenformel|molekulargewicht|iupac[\s\-_]name|pubchem)\s+(?:von|fuer|für|zu)\s+|molekül\s+)([a-zA-Z0-9äöüÄÖÜß\s\-,\+&]+?)(?:\?|\.|$)",
        cleaned,
        re.IGNORECASE
    )
    if m_chem:
        chem_target = m_chem.group(1).strip()
        if chem_target and len(chem_target) >= 2:
            return ("lookup_chemical_compound", {"compound_name": chem_target})

    # 18. Software Package Registry & Vulnerabilities (PyPI, NPM, OSV.dev)
    m_pkg = re.search(
        r"(?:(?:paketinfo|package\s+info|python\s+paket|pip\s+paket|npm\s+paket|node\s+paket|sicherheitslücken\s+in|cve\s+(?:in|zu))\s+(?:zu|von|über|fuer|für)\s+|welche\s+version\s+hat\s+(?:das\s+paket\s+)?)([a-zA-Z0-9_\-\.\@\/\s,\+&]+?)(?:\?|\.|$|\s+auf\s+pypi|\s+auf\s+npm)",
        cleaned,
        re.IGNORECASE
    )
    if m_pkg:
        pkg_target = m_pkg.group(1).strip()
        if pkg_target and len(pkg_target) >= 2:
            eco_val = "npm" if any(w in cleaned.lower() for w in ("npm", "node", "javascript", "js", "typescript", "ts")) else "pypi"
            return ("lookup_software_package", {"package_name": pkg_target, "ecosystem": eco_val})

    # 19. Dictionary & Word Definitions (Free Dictionary API)
    m_dict = re.search(
        r"(?:(?:was\s+bedeutet|definition\s+(?:von|fuer|für)|bedeutung\s+(?:von|des\s+wortes)|synonyme\s+(?:fuer|für|zu)|übersetze\s+(?:das\s+wort\s+)?)\s+)(['\"`]?)([a-zA-ZäöüÄÖÜß\s\-,\+&]+?)\1(?:\?|\.|$|\s+im\s+wörterbuch|\s+auf\s+deutsch|\s+auf\s+englisch)",
        cleaned,
        re.IGNORECASE
    )
    if m_dict:
        w_target = m_dict.group(2).strip()
        if w_target and len(w_target) >= 2 and not any(w_target.lower().startswith(x) for x in ("das ", "die ", "der ", "ein ", "eine ")):
            return ("lookup_word_definition", {"word": w_target})

    # 20. Food Nutrition, Allergens & Ingredients (Open Food Facts)
    m_food = re.search(
        r"(?:(?:nährwerte|inhaltsstoffe|zutaten|wie\s+viel\s+kalorien\s+hat|kalorien\s+(?:in|von)|nutri[\s\-_]score\s+(?:von|für)|allergene\s+in)\s+(?:von|fuer|für|in)\s+)([a-zA-Z0-9äöüÄÖÜß\s\-,\+&]+?)(?:\?|\.|$)",
        cleaned,
        re.IGNORECASE
    )
    if m_food:
        food_target = m_food.group(1).strip()
        if food_target and len(food_target) >= 2:
            return ("lookup_food_product", {"product_name": food_target})

    # 21. Rail Transit & Train Departures (Deutsche Bahn / HAFAS)
    m_train = re.search(
        r"(?:(?:fahrplan\s+(?:fuer|für|von|ab|in)|abfahrten\s+(?:fuer|für|von|ab|in)|nächste\s+züge\s+(?:ab|von)|abfahrtstafel\s+(?:von|für)|bahn\s+abfahrten\s+(?:ab|in))\s+)([a-zA-Z0-9äöüÄÖÜß\s\-\(\)\/,\+&]+?)(?:\?|\.|$|\s+heute|\s+jetzt|\s+aktuell)",
        cleaned,
        re.IGNORECASE
    )
    if m_train:
        st_target = m_train.group(1).strip()
        if st_target and len(st_target) >= 2:
            return ("lookup_train_schedule", {"station": st_target})

    # 22. Real-time Global Earthquakes (USGS)
    if re.search(r"(?:aktuelle\s+erdbeben|erdbeben\s+weltweit|gab\s+es\s+(?:heute\s+)?erdbeben|seismische\s+aktivität|recent\s+earthquakes|latest\s+earthquakes)", cleaned, re.IGNORECASE):
        return ("get_recent_earthquakes", {})

    # 23. Scientific arXiv Papers & Academic Preprints (arXiv.org)
    m_arxiv = re.search(
        r"(?:(?:arxiv\s+(?:paper|studien|artikel|forschung|preprints?)\s+(?:zu|über|fuer|für|nach)\s+|wissenschaftliche\s+(?:paper|studien|arbeiten)\s+(?:zu|über|fuer|für)\s+|paper\s+auf\s+arxiv\s+(?:zu|über)\s+))([a-zA-Z0-9äöüÄÖÜß\s\-,\+&]+?)(?:\?|\.|$)",
        cleaned,
        re.IGNORECASE
    )
    if m_arxiv:
        arxiv_target = m_arxiv.group(1).strip()
        if arxiv_target and len(arxiv_target) >= 2:
            return ("search_arxiv_papers", {"query": arxiv_target})

    # 24. Sports Schedules, Fixtures & Teams (TheSportsDB)
    m_sports = re.search(
        r"(?:(?:spielplan\s+(?:von|für|der)|nächste\s+spiele\s+(?:von|der)|wann\s+spielt|ergebnisse\s+von)\s+)([a-zA-Z0-9äöüÄÖÜß\s\-]+?)(?:\?|\.|$)",
        cleaned,
        re.IGNORECASE
    )
    if m_sports:
        sp_target = m_sports.group(1).strip()
        if sp_target and len(sp_target) >= 2 and not any(w in sp_target.lower() for w in ("wetter", "uhr", "tag", "heute")):
            return ("get_sports_data", {"query": sp_target, "mode": "teams"})

    return None


REFUSAL_KEYWORDS = [
    "keine aktuellen",
    "keine echtzeitdaten",
    "kein echtzeitzugriff",
    "keine live-informationen",
    "kann nicht auf echtzeit",
    "kann nicht auf live",
    "habe keinen echtzeit",
    "keinen echtzeit-zugriff",
    "keine wetterdaten",
    "cannot provide real-time",
    "don't have access to real-time",
    "as an ai, i do not have access to live",
    "connection refused",
    "errno 111",
    "urlopen error",
    "standby",
    "offline",
    "failed to connect",
]


class AgentLoop:
    def __init__(self, registry: Optional[ToolRegistry] = None, config: Optional[MCPConfig] = None):
        self.config = config or get_mcp_config()
        self.registry = registry or ToolRegistry(self.config)

    def run(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        llm_caller: Callable[[List[Dict[str, Any]], List[Dict[str, Any]]], Dict[str, Any]],
        is_owner: bool = True,
        max_iterations: Optional[int] = None,
        disabled_tools: Optional[List[str]] = None,
    ) -> AgentExecutionResult:
        try:
            requested_iterations = int(self.config.max_agent_iterations if max_iterations is None else max_iterations)
        except (TypeError, ValueError):
            requested_iterations = self.config.max_agent_iterations
        max_iter = max(1, min(MAX_AGENT_ITERATIONS, requested_iterations))

        curr_messages = [dict(message) for message in messages]
        disabled_set = {
            _canonical_name(self.registry, str(name).strip())
            for name in (disabled_tools or [])
            if str(name).strip()
        }
        all_tools = self.registry.get_openai_tools(is_owner=is_owner)
        tools = [
            tool for tool in all_tools
            if _canonical_name(self.registry, tool.get("function", {}).get("name", "")) not in disabled_set
        ]

        # Ensure tools guidance & persistent user memory are present in system instructions
        mem_info = ""
        try:
            from ..memory import get_user_memory_store
            mem_summary = get_user_memory_store().get_memory_summary()
            if mem_summary and "Keine gespeicherten" not in mem_summary:
                mem_info = f"\n\n[Persistentes Benutzer-Gedächtnis & Fakten]:\n{mem_summary}"
        except Exception:
            pass

        if tools or mem_info:
            has_system = any(m.get("role") == "system" for m in curr_messages)
            sys_guidance = (
                "Du bist ComputeMesh AI. Du verfügst über volle OpenAI-Parität mit integrierten Live-Tools "
                "(Code Interpreter / Python Sandbox `execute_python_code`, Terminal Runner `run_terminal_command`, "
                "GitHub Integration Suite `github_get_repo`, `github_list_issues`, `github_get_pull_request`, `github_search_code`, "
                "HTTP API Client `execute_http_request`, Vektordatenbank / Document RAG `search_knowledge_base`, "
                "Echtzeit-Wetter `get_current_weather`, Börsen- und Kryptokurse `get_market_quote`, Web-Recherche `search_web`, "
                "Multi-Source Tiefenrecherche & Cross-Linguale Wikipedia `cross_source_knowledge_search`, `fetch_multilingual_wikipedia`, "
                "Ereignis-Zeitleisten `fetch_recent_timeline`, Faktenprüfung `verify_fact_multi_source`, Deep Cultural & Event Recherche `search_events`, "
                "Mathe `calculate_math` und Gedächtnis `update_user_memory`). "
                "Nutze diese Werkzeuge aktiv für präzise, topaktuelle und fundierte Antworten."
                f"{mem_info}"
            )
            if not has_system:
                curr_messages.insert(0, {"role": "system", "content": sys_guidance})
            elif mem_info:
                for m in curr_messages:
                    if m.get("role") == "system":
                        if "[Persistentes Benutzer-Gedächtnis" not in str(m.get("content", "")):
                            m["content"] = str(m.get("content", "")) + mem_info
                        break

        executed_records: List[ToolCallRecord] = []
        total_prompt_tok = 0
        total_comp_tok = 0
        last_assistant_content = ""

        # Find latest user prompt and check for images
        last_user_text = ""
        has_images = False
        for m in reversed(curr_messages):
            if bool(m.get("images")) or bool(m.get("_processed_images")):
                has_images = True
            c = m.get("content")
            if isinstance(c, list) and any(isinstance(p, dict) and p.get("type") in ("image_url", "image") for p in c):
                has_images = True
            if m.get("role") == "user" and not last_user_text:
                last_user_text = str(m.get("content") or "")

        # Check proactive pre-flight intent only for pure text queries without images
        direct_intent = detect_direct_tool_intent(last_user_text, self.registry) if (last_user_text and not has_images) else None

        # If no direct intent matched, check if resolving conversational references yields a research topic
        if not direct_intent and last_user_text and not has_images and len(curr_messages) > 1:
            try:
                from .builtin.context_resolver import resolve_contextual_query
                resolved_q, resolved_entity, was_resolved = resolve_contextual_query(last_user_text, curr_messages)
                if was_resolved and resolved_entity:
                    direct_intent = ("cross_source_knowledge_search", {"query": resolved_q})
            except Exception:
                pass
        if direct_intent and not any(m.get("role") == "tool" for m in curr_messages):
            fn_name, fn_args = direct_intent
            if fn_name not in disabled_set and self.registry.get_tool(fn_name):
                call_id = "call_direct_preflight_1"
                tool_res = self.registry.execute_tool(fn_name, fn_args, is_owner=is_owner)
                executed_records.append(ToolCallRecord(id=call_id, name=fn_name, arguments=fn_args, result=tool_res))
                output_str = tool_res if isinstance(tool_res, str) else json.dumps(tool_res, ensure_ascii=False)
                if len(output_str) > MAX_TOOL_MESSAGE_CHARS:
                    output_str = output_str[:MAX_TOOL_MESSAGE_CHARS] + "\n[Tool-Ausgabe gekürzt]"

                curr_messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": fn_name,
                            "arguments": json.dumps(fn_args, ensure_ascii=False),
                        }
                    }]
                })
                curr_messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": fn_name,
                    "content": output_str,
                })

        for iteration in range(1, max_iter + 1):
            response = llm_caller(curr_messages, tools if tools else [])
            if not isinstance(response, dict):
                break
            usage = response.get("usage", {})
            if isinstance(usage, dict):
                total_prompt_tok += int(usage.get("prompt_tokens", 0) or 0)
                total_comp_tok += int(usage.get("completion_tokens", 0) or 0)

            choices = response.get("choices", [])
            if not isinstance(choices, list) or not choices:
                break
            choice = choices[0] if isinstance(choices[0], dict) else {}
            message = choice.get("message", {}) if isinstance(choice, dict) else {}
            message = message if isinstance(message, dict) else {}
            content = str(message.get("content") or "")
            last_assistant_content = content or last_assistant_content
            raw_tool_calls = message.get("tool_calls") or []
            tool_calls = list(raw_tool_calls) if isinstance(raw_tool_calls, list) else []
            if not tool_calls:
                tool_calls = _fallback_tool_calls(content, self.registry)
            else:
                tool_calls = tool_calls[:MAX_TOOL_CALLS_PER_ITERATION]

            # Check if model emitted refusal or no tool call despite clear user tool intent
            is_refusal = any(kw in content.lower() for kw in REFUSAL_KEYWORDS)
            if (not tool_calls or is_refusal) and direct_intent and iteration == 1 and not executed_records:
                fn_name, fn_args = direct_intent
                if fn_name not in disabled_set and self.registry.get_tool(fn_name):
                    tool_calls = [{
                        "id": f"call_auto_{len(executed_records)+1}",
                        "type": "function",
                        "function": {
                            "name": fn_name,
                            "arguments": json.dumps(fn_args, ensure_ascii=False),
                        },
                    }]

            # If no tools were called, this is the final answer
            if not tool_calls:
                final = format_tool_content_if_json(content)
                if not final and executed_records:
                    final = format_tool_content_if_json(
                        executed_records[-1].result if isinstance(executed_records[-1].result, str) else json.dumps(executed_records[-1].result, ensure_ascii=False)
                    )
                curr_messages.append({"role": "assistant", "content": final})
                return AgentExecutionResult(
                    final_content=final,
                    messages=curr_messages,
                    tool_calls_executed=executed_records,
                    iterations=iteration,
                    model=model,
                    prompt_tokens=total_prompt_tok,
                    completion_tokens=total_comp_tok,
                    total_tokens=total_prompt_tok + total_comp_tok,
                )

            assistant_msg: Dict[str, Any] = {"role": "assistant", "tool_calls": tool_calls}
            if content:
                assistant_msg["content"] = content
            curr_messages.append(assistant_msg)

            # Execute tool calls in parallel with automatic concurrency and TTL caching
            batch_results = self.registry.execute_tools_batch(tool_calls, is_owner=is_owner)
            for res_item in batch_results:
                call_id = res_item["id"]
                fn_name = res_item["name"]
                record_args = res_item["arguments"]
                tool_output = res_item["result"]

                canonical = _canonical_name(self.registry, fn_name)
                if canonical in disabled_set:
                    tool_output = {"error": f"Tool '{canonical}' ist für diese Flotte deaktiviert."}

                executed_records.append(ToolCallRecord(
                    id=call_id,
                    name=fn_name,
                    arguments=record_args,
                    result=tool_output,
                ))
                output_str = tool_output if isinstance(tool_output, str) else json.dumps(tool_output, ensure_ascii=False)
                if len(output_str) > MAX_TOOL_MESSAGE_CHARS:
                    output_str = output_str[:MAX_TOOL_MESSAGE_CHARS] + "\n[Tool-Ausgabe gekürzt]"
                curr_messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": fn_name,
                    "content": output_str,
                })


        final = format_tool_content_if_json(last_assistant_content)
        if not final and executed_records:
            final = format_tool_content_if_json(
                executed_records[-1].result if isinstance(executed_records[-1].result, str) else json.dumps(executed_records[-1].result, ensure_ascii=False)
            )
        return AgentExecutionResult(
            final_content=final,
            messages=curr_messages,
            tool_calls_executed=executed_records,
            iterations=max_iter,
            model=model,
            prompt_tokens=total_prompt_tok,
            completion_tokens=total_comp_tok,
            total_tokens=total_prompt_tok + total_comp_tok,
        )
