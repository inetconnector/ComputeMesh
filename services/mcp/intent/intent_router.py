# SPDX-License-Identifier: Apache-2.0
"""High-precision direct tool intent router."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from ..tool_registry import ToolRegistry

from .entity_tokenizer import split_multi_entities, clean_entity_token

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

    # GitHub Repo info: e.g. "https://github.com/owner/repo", "checke repo https://github.com/owner/repo", "github repo owner/repo"
    m_gh_url = re.search(
        r"(?:https?://(?:www\.)?github\.com/([a-zA-Z0-9_\-\.]+)/([a-zA-Z0-9_\-\.]+)|(?:checke|analysiere|untersuche|inspect|clone|klone|lade|zeige|öffne|prüfe)\s+(?:das\s+)?(?:github\s+)?repo(?:sitory)?\s+(?:https?://(?:www\.)?github\.com/)?([a-zA-Z0-9_\-\.]+)/([a-zA-Z0-9_\-\.]+)|(?:github\s+(?:repo(?:sitory)?|info)\s+(?:von\s+|über\s+|zu\s+)?|gh\s+repo\s+)([a-zA-Z0-9_\-\.]+)/([a-zA-Z0-9_\-\.]+))",
        cleaned,
        re.IGNORECASE
    )
    if m_gh_url:
        g_owner = m_gh_url.group(1) or m_gh_url.group(3) or m_gh_url.group(5)
        g_repo = m_gh_url.group(2) or m_gh_url.group(4) or m_gh_url.group(6)
        if g_owner and g_repo:
            g_repo = g_repo.rstrip(".git").rstrip("/.!?")
            return ("github_get_repo", {"owner": g_owner, "repo": g_repo})

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
        r"(?:(?:fakten\s+über\s+(?:das\s+land\s+)?|fakten\s+zum?\s+land\s+|länderdaten\s+(?:von|zu)|landesdaten\s+(?:von|zu)|länderinfo\s+(?:von|zu)|landesinfo\s+(?:von|zu)|hauptstadt\s+von|wie\s+viele\s+einwohner\s+hat|einwohnerzahl\s+von)\s+)([a-zA-ZäöüÄÖÜß\s\-,&+]+)",
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
    has_market_context = bool(re.search(
        r"(?:aktie|aktien|aktienkurs|kurs|kursziel|börse|boerse|market|stock|quote|preis|wert|krypto|crypto|kryptowährung|ticker|\$|usd|eur|\bbtc\b|\beth\b|\bsol\b|\bxrp\b)",
        cleaned,
        re.IGNORECASE
    ))

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

    if has_market_context:
        if re.search(r"\b(?:nvidia|nvda)\b", cleaned, re.IGNORECASE):
            found_symbols.append("NVDA")
        if re.search(r"\b(?:apple|aapl)\b", cleaned, re.IGNORECASE):
            found_symbols.append("AAPL")
        if re.search(r"\b(?:microsoft|msft)\b", cleaned, re.IGNORECASE):
            found_symbols.append("MSFT")

    if len(found_symbols) > 1:
        return ("get_market_quote", {"symbol": " und ".join(found_symbols)})
    elif len(found_symbols) == 1 and (has_market_context or found_symbols[0] in {"BTC", "ETH", "SOL", "XRP", "ADA"}):
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


