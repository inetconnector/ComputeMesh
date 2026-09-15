# SPDX-License-Identifier: Apache-2.0
"""Central Tool Registry for the ComputeMesh MCP subsystem.

The registry exposes built-in live-data tools in OpenAI function-calling format,
resolves backwards-compatible aliases, enforces owner-only tools, and performs a
small fail-closed validation pass for schemas that set ``additionalProperties``
to ``False``.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from .config import MCPConfig, get_mcp_config
from .builtin.adb_bridge_tools import adb_list_devices, adb_capture_screenshot, adb_install_app, adb_get_system_log
from .builtin.arxiv_research import search_arxiv_papers
from .builtin.audio_tools import transcribe_audio_data, synthesize_speech_audio
from .builtin.chemical_data import lookup_chemical_compound
from .builtin.code_lint_and_syntax import validate_code_syntax, check_code_quality
from .builtin.code_patch_engine import replace_file_content, multi_replace_file_content
from .builtin.code_search_indexer import grep_search_code, extract_code_symbols
from .builtin.company_lookup import lookup_company
from .builtin.country_data import lookup_country_data
from .builtin.currency import convert_currency
from .builtin.data_table_tools import analyze_data_table
from .builtin.dictionary_lookup import lookup_word_definition
from .builtin.document_reader import extract_document_content
from .builtin.earthquake_feed import get_recent_earthquakes
from .builtin.events import search_events
from .builtin.fact_triangulation import verify_fact_multi_source
from .builtin.file_system_tools import list_workspace_files, read_workspace_file
from .builtin.finance_market import execute_finance_quote
from .builtin.food_products import lookup_food_product
from .builtin.generate_image import generate_ai_image
from .builtin.geo_routing import get_distance_route
from .builtin.git_tools import get_git_status, get_git_diff, get_git_log
from .builtin.github_ci_tools import github_list_releases, github_get_latest_release, github_list_commits, github_get_workflow_runs
from .builtin.github_issue_tools import github_list_issues, github_get_issue, github_create_issue, github_add_issue_comment
from .builtin.github_pr_tools import github_list_pull_requests, github_get_pull_request, github_get_pull_request_diff, github_get_pull_request_files
from .builtin.github_repo_tools import github_get_repo, github_search_repositories, github_get_file_contents, github_list_repo_tree, github_search_code
from .builtin.http_api_client import execute_http_request
from .builtin.knowledge_fusion import cross_source_knowledge_search
from .builtin.mission_journal import mission_start, mission_log_step, mission_verify_postconditions, mission_get_summary
from .builtin.multilingual_wiki import fetch_multilingual_wikipedia
from .builtin.network_tools import lookup_network_host
from .builtin.news_feed import execute_get_news, get_live_news
from .builtin.office_suite import generate_office_document, parse_office_document, convert_data_to_markdown_table
from .builtin.package_registry import lookup_software_package
from .builtin.places import search_places
from .builtin.python_calc import run_python_calc
from .builtin.python_sandbox import execute_python_code
from .builtin.rag_tool import search_knowledge_base, index_document_text, list_indexed_documents
from .builtin.sports_data import get_sports_data
from .builtin.system_tools import execute_system_info, execute_gpu_telemetry, execute_process_summary
from .builtin.terminal_runner import run_terminal_command
from .builtin.test_runner_tools import run_project_tests
from .builtin.time_calendar import get_time_and_calendar
from .builtin.timeline_builder import fetch_recent_timeline
from .builtin.tool_installer import detect_missing_tools, install_dev_tool
from .builtin.train_transit import lookup_train_schedule
from .builtin.url_security import check_url_safety
from .builtin.weather import execute_get_weather
from .builtin.weather_forecast import get_weather_forecast
from .builtin.web_fetch import execute_web_fetch
from .builtin.web_search import execute_web_search
from .builtin.webapp_deployer import deploy_local_webapp, list_deployed_webapps, remove_deployed_webapp, launch_deployed_webapp
from .builtin.wikipedia import get_wikipedia_summary
from .builtin.world_bank import get_world_bank_stats
from .builtin.workspace_doctor import run_doctor_diagnostics
from .builtin.workspace_quarantine import quarantine_stage_files, quarantine_validate, quarantine_commit, quarantine_rollback
from services.memory.user_memory import get_user_memory, update_user_memory, delete_user_memory

DEFAULT_TOOL_TTL: Dict[str, float] = {
    "list_deployed_webapps": 5.0,
    "run_doctor_diagnostics": 10.0,
    "quarantine_validate": 5.0,
    "mission_get_summary": 5.0,
    "detect_missing_tools": 30.0,
    "adb_list_devices": 5.0,
    "calculate_math": 3600.0,
    "get_wikipedia_summary": 3600.0,
    "fetch_multilingual_wikipedia": 3600.0,
    "cross_source_knowledge_search": 120.0,
    "fetch_recent_timeline": 120.0,
    "verify_fact_multi_source": 180.0,
    "get_gpu_telemetry": 10.0,
    "get_system_info": 10.0,
    "list_workspace_files": 30.0,
    "read_workspace_file": 30.0,
    "grep_search_code": 10.0,
    "extract_code_symbols": 30.0,
    "validate_code_syntax": 30.0,
    "check_code_quality": 30.0,
    "get_git_status": 5.0,
    "get_git_diff": 5.0,
    "get_git_log": 30.0,
    "github_get_repo": 120.0,
    "github_search_repositories": 120.0,
    "github_get_file_contents": 60.0,
    "github_list_repo_tree": 60.0,
    "github_search_code": 60.0,
    "github_list_issues": 60.0,
    "github_get_issue": 60.0,
    "github_list_pull_requests": 60.0,
    "github_get_pull_request": 60.0,
    "github_get_pull_request_diff": 60.0,
    "github_get_pull_request_files": 60.0,
    "github_list_releases": 180.0,
    "github_get_latest_release": 180.0,
    "github_list_commits": 60.0,
    "github_get_workflow_runs": 60.0,
    "analyze_data_table": 120.0,
    "extract_document_content": 120.0,
    "transcribe_audio_data": 300.0,
    "synthesize_speech_audio": 300.0,
    "lookup_chemical_compound": 3600.0,
    "lookup_country_data": 3600.0,
    "lookup_word_definition": 3600.0,
    "get_world_bank_stats": 1800.0,
    "lookup_food_product": 1800.0,
    "lookup_software_package": 600.0,
    "search_arxiv_papers": 600.0,
    "get_distance_route": 600.0,
    "get_weather_forecast": 300.0,
    "get_current_weather": 180.0,
    "search_events": 180.0,
    "search_places": 300.0,
    "lookup_company": 600.0,
    "check_url_safety": 300.0,
    "get_market_quote": 60.0,
    "convert_currency": 60.0,
    "get_live_news": 60.0,
    "get_sports_data": 60.0,
    "lookup_train_schedule": 60.0,
    "get_recent_earthquakes": 60.0,
    "search_web": 120.0,
    "fetch_web_content": 120.0,
    "get_time_and_calendar": 10.0,
}



class ToolCache:
    """Thread-safe in-memory cache with per-tool TTL to eliminate duplicate round-trips."""

    def __init__(self, max_size: int = 1000):
        self._cache: Dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._max_size = max_size

    def _make_key(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        try:
            serialized_args = json.dumps(arguments, sort_keys=True, ensure_ascii=False)
        except Exception:
            serialized_args = str(sorted(arguments.items()))
        return f"{tool_name}:{serialized_args}"

    def get(self, tool_name: str, arguments: Dict[str, Any]) -> tuple[bool, Any]:
        ttl = DEFAULT_TOOL_TTL.get(tool_name, 0.0)
        if ttl <= 0:
            return False, None
        key = self._make_key(tool_name, arguments)
        now = time.time()
        with self._lock:
            if key in self._cache:
                expires_at, val = self._cache[key]
                if now < expires_at:
                    return True, val
                del self._cache[key]
        return False, None

    def set(self, tool_name: str, arguments: Dict[str, Any], result: Any) -> None:
        ttl = DEFAULT_TOOL_TTL.get(tool_name, 0.0)
        if ttl <= 0:
            return
        if isinstance(result, dict) and result.get("error"):
            return  # Do not cache error responses
        key = self._make_key(tool_name, arguments)
        now = time.time()
        with self._lock:
            if len(self._cache) >= self._max_size:
                oldest_keys = sorted(self._cache.keys(), key=lambda k: self._cache[k][0])[:100]
                for ok in oldest_keys:
                    self._cache.pop(ok, None)
            self._cache[key] = (now + ttl, result)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable[..., Any]
    owner_only: bool = False
    source: str = "builtin"

    def to_openai_dict(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


TOOL_ALIASES: Dict[str, str] = {
    "get_weather": "get_current_weather",
    "weather": "get_current_weather",
    "current_weather": "get_current_weather",
    "weather_forecast": "get_weather_forecast",
    "forecast": "get_weather_forecast",
    "web_search": "search_web",
    "generate_image": "generate_ai_image",
    "generate_ai_image": "generate_ai_image",
    "create_image": "generate_ai_image",
    "draw_image": "generate_ai_image",
    "paint_image": "generate_ai_image",
    "bild_generieren": "generate_ai_image",
    "image_generator": "generate_ai_image",
    "ai_image": "generate_ai_image",
    "code_interpreter": "execute_python_code",
    "python": "execute_python_code",
    "run_python": "execute_python_code",
    "python_code": "execute_python_code",
    "execute_code": "execute_python_code",
    "search_documents": "search_knowledge_base",
    "search_rag": "search_knowledge_base",
    "rag_search": "search_knowledge_base",
    "file_search": "search_knowledge_base",
    "knowledge_base": "search_knowledge_base",
    "user_memory": "get_user_memory",
    "memory": "get_user_memory",
    "remember": "update_user_memory",
    "check_url": "check_url_safety",
    "check_url_safety": "check_url_safety",
    "url_safety": "check_url_safety",
    "url_security": "check_url_safety",
    "scan_url": "check_url_safety",
    "brave_web_search": "search_web",
    "search": "search_web",
    "web_search_query": "search_web",
    "stock_quote": "get_market_quote",
    "get_stock_quote": "get_market_quote",
    "crypto_price": "get_market_quote",
    "market_quote": "get_market_quote",
    "calculator": "calculate_math",
    "calc": "calculate_math",
    "math": "calculate_math",
    "calculate": "calculate_math",
    "timeline": "fetch_recent_timeline",
    "event_timeline": "fetch_recent_timeline",
    "zeitleiste": "fetch_recent_timeline",
    "chronologie": "fetch_recent_timeline",
    "verify_fact": "verify_fact_multi_source",
    "fact_check": "verify_fact_multi_source",
    "faktenpruefung": "verify_fact_multi_source",
    "fakten_check": "verify_fact_multi_source",
    "deep_research": "cross_source_knowledge_search",
    "deep_research_topic": "cross_source_knowledge_search",
    "research_topic": "cross_source_knowledge_search",
    "knowledge_fusion": "cross_source_knowledge_search",
    "recherche": "cross_source_knowledge_search",
    "tiefenrecherche": "cross_source_knowledge_search",
    "multilingual_wiki": "fetch_multilingual_wikipedia",
    "get_wikipedia_multilingual": "fetch_multilingual_wikipedia",
    "wikipedia_de_en": "fetch_multilingual_wikipedia",
    "wikipedia": "get_wikipedia_summary",
    "get_wikipedia": "get_wikipedia_summary",
    "dns": "lookup_network_host",
    "dns_lookup": "lookup_network_host",
    "get_top_news": "get_live_news",
    "get_news": "get_live_news",
    "get_news_feed": "get_live_news",
    "news": "get_live_news",
    "news_feed": "get_live_news",
    "events": "search_events",
    "event_search": "search_events",
    "konzerte": "search_events",
    "konzertsuche": "search_events",
    "veranstaltungen": "search_events",
    "live_events": "search_events",
    "research_events": "search_events",
    "research_concerts": "search_events",
    "places": "search_places",
    "place_search": "search_places",
    "sports": "get_sports_data",
    "company": "lookup_company",
    "company_lookup": "lookup_company",
    "get_current_time_calendar": "get_time_and_calendar",
    "get_current_time": "get_time_and_calendar",
    "get_time": "get_time_and_calendar",
    "current_time": "get_time_and_calendar",
    "time": "get_time_and_calendar",
    "bitcoin_price": "get_market_quote",
    "btc_price": "get_market_quote",
    "list_tools": "list_available_tools",
    "get_tools": "list_available_tools",
    "mcp_tools": "list_available_tools",
    "mcp_modules": "list_available_tools",
    "available_tools": "list_available_tools",
    "gpu": "get_gpu_telemetry",
    "gpu_status": "get_gpu_telemetry",
    "gpu_info": "get_gpu_telemetry",
    "gpu_telemetry": "get_gpu_telemetry",
    "vram": "get_gpu_telemetry",
    "system": "get_system_info",
    "system_status": "get_system_info",
    "system_telemetry": "get_system_info",
    "disk_usage": "get_system_info",
    "list_files": "list_workspace_files",
    "ls": "list_workspace_files",
    "dir": "list_workspace_files",
    "read_file": "read_workspace_file",
    "cat": "read_workspace_file",
    "view_file": "read_workspace_file",
    "analyze_table": "analyze_data_table",
    "analyze_csv": "analyze_data_table",
    "table_summary": "analyze_data_table",
    "extract_document": "extract_document_content",
    "read_document": "extract_document_content",
    "transcribe_audio": "transcribe_audio_data",
    "transcribe": "transcribe_audio_data",
    "synthesize_speech": "synthesize_speech_audio",
    "text_to_speech": "synthesize_speech_audio",
    "tts": "synthesize_speech_audio",
    "replace_code": "replace_file_content",
    "patch_code": "replace_file_content",
    "patch_file": "replace_file_content",
    "grep_code": "grep_search_code",
    "code_search": "grep_search_code",
    "code_symbols": "extract_code_symbols",
    "extract_symbols": "extract_code_symbols",
    "syntax_check": "validate_code_syntax",
    "validate_syntax": "validate_code_syntax",
    "lint_code": "check_code_quality",
    "code_quality": "check_code_quality",
    "run_tests": "run_project_tests",
    "test_suite": "run_project_tests",
    "git_status": "get_git_status",
    "git_diff": "get_git_diff",
    "git_log": "get_git_log",
    "gh_repo": "github_get_repo",
    "github_repo": "github_get_repo",
    "gh_search": "github_search_repositories",
    "github_search": "github_search_repositories",
    "gh_file": "github_get_file_contents",
    "gh_tree": "github_list_repo_tree",
    "gh_code": "github_search_code",
    "gh_issues": "github_list_issues",
    "github_issues": "github_list_issues",
    "gh_issue": "github_get_issue",
    "create_issue": "github_create_issue",
    "gh_prs": "github_list_pull_requests",
    "github_prs": "github_list_pull_requests",
    "gh_pr": "github_get_pull_request",
    "github_pr": "github_get_pull_request",
    "gh_diff": "github_get_pull_request_diff",
    "gh_release": "github_get_latest_release",
    "gh_releases": "github_list_releases",
    "gh_commits": "github_list_commits",
    "gh_actions": "github_get_workflow_runs",
    "gh_workflows": "github_get_workflow_runs",
    "terminal": "run_terminal_command",
    "bash": "run_terminal_command",
    "shell": "run_terminal_command",
    "http_request": "execute_http_request",
    "api_request": "execute_http_request",
    "api_call": "execute_http_request",
    "curl": "execute_http_request",
    "doctor": "run_doctor_diagnostics",
    "run_doctor": "run_doctor_diagnostics",
    "system_doctor": "run_doctor_diagnostics",
    "system_health": "run_doctor_diagnostics",
    "quarantine": "quarantine_stage_files",
    "stage_files": "quarantine_stage_files",
    "stage_code": "quarantine_stage_files",
    "commit_quarantine": "quarantine_commit",
    "rollback_quarantine": "quarantine_rollback",
    "mission": "mission_start",
    "start_mission": "mission_start",
    "mission_status": "mission_get_summary",
    "check_tools": "detect_missing_tools",
    "install_tool": "install_dev_tool",
    "adb": "adb_list_devices",
    "adb_devices": "adb_list_devices",
    "adb_screenshot": "adb_capture_screenshot",
    "screenshot_device": "adb_capture_screenshot",
    "adb_logcat": "adb_get_system_log",
    "deploy_webapp": "deploy_local_webapp",
    "create_webapp": "deploy_local_webapp",
    "build_webapp": "deploy_local_webapp",
    "list_webapps": "list_deployed_webapps",
    "get_webapps": "list_deployed_webapps",
    "remove_webapp": "remove_deployed_webapp",
    "delete_webapp": "remove_deployed_webapp",
    "launch_webapp": "launch_deployed_webapp",
    "open_webapp": "launch_deployed_webapp",
    "open_pacman": "launch_deployed_webapp",
    "play_pacman": "launch_deployed_webapp",
    "pacman": "launch_deployed_webapp",
    "start_pacman": "launch_deployed_webapp",
    "spiele_pacman": "launch_deployed_webapp",
}


def _matches_type(value: Any, expected: Any) -> bool:
    expected_types = expected if isinstance(expected, list) else [expected]
    for item in expected_types:
        if item == "null" and value is None:
            return True
        if item == "string" and isinstance(value, str):
            return True
        if item == "boolean" and isinstance(value, bool):
            return True
        if item == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if item == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
        if item == "array" and isinstance(value, list):
            return True
        if item == "object" and isinstance(value, dict):
            return True
    return False


def _validate_strict_arguments(schema: Dict[str, Any], arguments: Any) -> Optional[str]:
    """Validate the subset needed by strict built-in schemas without a dependency."""
    if not isinstance(arguments, dict):
        return "Tool-Parameter müssen ein JSON-Objekt sein."
    if schema.get("additionalProperties") is not False:
        return None

    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    unknown = sorted(set(arguments) - set(properties))
    if unknown:
        return f"Unbekannte Tool-Parameter: {', '.join(unknown)}"

    missing = [name for name in schema.get("required", []) if name not in arguments]
    if missing:
        return f"Fehlende Pflichtparameter: {', '.join(missing)}"

    for name, value in arguments.items():
        spec = properties.get(name)
        if not isinstance(spec, dict):
            continue
        expected = spec.get("type")
        if expected is not None and not _matches_type(value, expected):
            return f"Parameter '{name}' hat einen ungültigen Typ."
        if "enum" in spec and value not in spec["enum"]:
            return f"Parameter '{name}' hat einen ungültigen Wert."
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in spec and value < spec["minimum"]:
                return f"Parameter '{name}' liegt unter dem Minimum {spec['minimum']}."
            if "maximum" in spec and value > spec["maximum"]:
                return f"Parameter '{name}' liegt über dem Maximum {spec['maximum']}."
    return None


class ToolRegistry:
    def __init__(self, config: Optional[MCPConfig] = None):
        self.config = config or get_mcp_config()
        self._tools: Dict[str, ToolDefinition] = {}
        self._cache = ToolCache()
        self._register_default_tools()
        try:
            from .dynamic.custom_tool_store import get_custom_tool_store
            get_custom_tool_store().load_into_registry(self)
        except Exception:
            pass

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Callable[..., Any],
        owner_only: bool = False,
        source: str = "builtin",
    ) -> None:
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
            owner_only=owner_only,
            source=source,
        )

    def unregister_tool(self, name: str) -> None:
        self._tools.pop(name, None)

    def _resolve_tool_name(self, name: str) -> str:
        if not name:
            return ""
        if name in self._tools:
            return name
        if name in TOOL_ALIASES:
            return TOOL_ALIASES[name]

        lower_name = name.lower().replace("-", "_")
        if lower_name in self._tools:
            return lower_name
        if lower_name in TOOL_ALIASES:
            return TOOL_ALIASES[lower_name]

        if "forecast" in lower_name or "vorhersage" in lower_name:
            return "get_weather_forecast"
        if any(k in lower_name for k in ("weather", "wetter", "temperature", "klima", "regen", "sonne")):
            return "get_current_weather"
        if any(k in lower_name for k in ("event", "veranstaltung", "concert", "konzert")):
            return "search_events"
        if any(k in lower_name for k in ("place", "poi", "restaurant", "hotel", "geschäft", "business_near")):
            return "search_places"
        if any(k in lower_name for k in ("sport", "score", "spielplan", "fixture", "league")):
            return "get_sports_data"
        if any(k in lower_name for k in ("company", "unternehmen", "firma", "legal_entity", "lei")):
            return "lookup_company"
        if any(k in lower_name for k in ("search", "google", "bing", "brave", "find", "suchen", "web_query")):
            return "search_web"
        if any(k in lower_name for k in ("image", "bild", "draw", "paint", "zeichnen", "malen", "generiere_bild", "photo_gen")):
            return "generate_ai_image"
        if any(k in lower_name for k in ("url_sec", "check_url", "url_safe", "ssrf")):
            return "check_url_safety"
        if any(k in lower_name for k in ("stock", "crypto", "quote", "aktie", "kurs", "krypto", "bitcoin", "eth", "market", "ticker")):
            return "get_market_quote"
        if any(k in lower_name for k in ("calc", "math", "rechen", "eval", "berechne", "formel")):
            return "calculate_math"
        if any(k in lower_name for k in ("wiki", "wikipedia", "lexikon", "enzyklop", "biografie", "definition")):
            return "get_wikipedia_summary"
        if any(k in lower_name for k in ("dns", "nslookup", "domain", "resolve", "ip_lookup")):
            return "lookup_network_host"
        if any(k in lower_name for k in ("news", "nachricht", "schlagzeile", "zeitung")):
            return "get_live_news"
        return name

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        resolved = self._resolve_tool_name(name)
        return self._tools.get(resolved) or self._tools.get(name)

    def list_tools(self, is_owner: bool = True) -> List[ToolDefinition]:
        if is_owner:
            return list(self._tools.values())
        return [tool for tool in self._tools.values() if not tool.owner_only]

    def get_openai_tools(self, is_owner: bool = True) -> List[Dict[str, Any]]:
        return [tool.to_openai_dict() for tool in self.list_tools(is_owner=is_owner)]

    def execute_tool(self, name: str, arguments: Dict[str, Any], is_owner: bool = True, owner_id: str | None = None) -> Any:
        resolved = self._resolve_tool_name(name)
        tool = self._tools.get(resolved) or self._tools.get(name)
        if not tool:
            return {"error": f"Tool '{name}' nicht gefunden"}
        if tool.owner_only and not is_owner:
            return {"error": f"Tool '{name}' erfordert Authentifizierung mit Owner Key"}

        validation_error = _validate_strict_arguments(tool.parameters, arguments)
        if validation_error:
            return {"error": f"Ungültige Tool-Parameter für '{name}': {validation_error}"}
        if not isinstance(arguments, dict):
            return {"error": f"Ungültige Tool-Parameter für '{name}': JSON-Objekt erwartet"}

        # Positive Authorization & Emergency Kill Switch Check (Global & Fleet-Scoped)
        try:
            from runtime.safety.dead_mans_switch import get_lease_guard
            guard = get_lease_guard()
            if guard.is_tripped:
                return {"error": f"Tool-Ausführung blockiert: Globaler Emergency Kill Switch ist aktiv ({guard.trip_reason})"}
            if owner_id and guard.is_fleet_tripped(owner_id):
                return {"error": f"Tool-Ausführung blockiert: Flotte '{owner_id}' ist gestoppt ({guard.get_fleet_trip_reason(owner_id)})"}
        except Exception:
            pass

        # Check in-memory TTL cache
        cache_hit, cached_val = self._cache.get(resolved, arguments)
        if cache_hit:
            return cached_val

        try:
            res = tool.handler(**arguments)
            self._cache.set(resolved, arguments, res)
            return res
        except TypeError as exc:
            return {"error": f"Ungültige Tool-Parameter für '{name}': {exc}"}
        except Exception as exc:
            return {"error": f"Fehler bei Ausführung von Tool '{name}': {exc}"}

    def execute_tools_batch(
        self,
        tool_calls: List[Dict[str, Any]],
        is_owner: bool = True,
        owner_id: str | None = None,
        max_workers: int = 8,
    ) -> List[Dict[str, Any]]:
        """Executes multiple tool calls concurrently using a thread pool."""
        if not tool_calls:
            return []

        def _process_single(tc: Dict[str, Any], index: int) -> Dict[str, Any]:
            cid = str(tc.get("id") or f"call_{index+1}")
            fn = tc.get("function", {}) if isinstance(tc.get("function"), dict) else {}
            fn_name = str(fn.get("name") or "")
            if not fn_name:
                return {"id": cid, "name": "", "arguments": {}, "result": {"error": "Tool-Aufruf enthält keinen Funktionsnamen."}}

            raw_args = fn.get("arguments", {})
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError as exc:
                    return {"id": cid, "name": fn_name, "arguments": {}, "result": {"error": f"Tool-Argumente sind kein gültiges JSON: {exc.msg}"}}
                if not isinstance(args, dict):
                    return {"id": cid, "name": fn_name, "arguments": {}, "result": {"error": "Tool-Argumente müssen ein JSON-Objekt sein."}}
            elif isinstance(raw_args, dict):
                args = raw_args
            else:
                return {"id": cid, "name": fn_name, "arguments": {}, "result": {"error": "Tool-Argumente müssen ein JSON-Objekt sein."}}

            res = self.execute_tool(fn_name, args, is_owner=is_owner, owner_id=owner_id)
            return {"id": cid, "name": fn_name, "arguments": args, "result": res}

        if len(tool_calls) == 1:
            return [_process_single(tool_calls[0], 0)]

        results: List[Optional[Dict[str, Any]]] = [None] * len(tool_calls)

        def _worker(index: int, tc: Dict[str, Any]) -> None:
            results[index] = _process_single(tc, index)

        worker_count = min(max_workers, len(tool_calls))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(_worker, idx, tc) for idx, tc in enumerate(tool_calls)]
            for f in futures:
                try:
                    f.result()
                except Exception:
                    pass

        return [r for r in results if r is not None]


    def _register_default_tools(self) -> None:
        def schema(properties: Dict[str, Any], required: List[str] | None = None, *, strict: bool = False) -> Dict[str, Any]:
            value: Dict[str, Any] = {"type": "object", "properties": properties}
            if required:
                value["required"] = required
            if strict:
                value["additionalProperties"] = False
            return value

        def _execute_list_tools(**kwargs: Any) -> Dict[str, Any]:
            return {
                "available_tools": [
                    {"name": t.name, "description": t.description}
                    for t in self.list_tools(is_owner=True)
                ]
            }

        self.register_tool(
            "list_available_tools",
            "Listet alle aktuell aktiven ComputeMesh MCP-Module und Live-Werkzeuge auf.",
            schema({}),
            _execute_list_tools,
            source="builtin_system",
        )

        if self.config.web_search_enabled:
            self.register_tool(
                "search_web",
                "Sucht live im Web nach aktuellen Informationen, Nachrichten, Dokumentationen oder Fakten.",
                schema({
                    "query": {"type": "string", "description": "Suchanfrage."},
                    "max_results": {"type": "integer", "description": "Maximal 1-10 Ergebnisse.", "default": 5},
                }, ["query"]),
                execute_web_search,
                source="builtin_web",
            )

        if self.config.finance_enabled:
            self.register_tool(
                "get_market_quote",
                "Liefert aktuelle Kurse für Aktien, Indizes, Rohstoffe und Kryptowährungen.",
                schema({"symbol": {"type": "string", "description": "Ticker, z. B. AAPL, SAP.DE, BTC, DAX."}}, ["symbol"]),
                execute_finance_quote,
                source="builtin_finance",
            )

        if self.config.web_fetch_enabled:
            self.register_tool(
                "fetch_web_content",
                "Lädt Textinhalt einer Webseite anhand einer URL.",
                schema({"url": {"type": "string", "description": "Vollständige https/http URL."}}, ["url"]),
                execute_web_fetch,
                source="builtin_web",
            )

        self.register_tool(
            "get_live_news",
            "Liefert aktuelle Nachrichten und Schlagzeilen zu einem Thema.",
            schema({
                "topic": {"type": "string", "default": "general"},
                "max_results": {"type": "integer", "default": 5},
            }),
            execute_get_news,
            source="builtin_news",
        )

        self.register_tool(
            "get_current_weather",
            "Liefert aktuelle Wetterdaten für einen Ort weltweit.",
            schema({"location": {"type": "string", "description": "Stadt oder Ort."}}, ["location"]),
            execute_get_weather,
            source="builtin_weather",
        )

        self.register_tool(
            "get_weather_forecast",
            "Liefert eine echte 1- bis 16-Tage-Wettervorhersage mit Temperatur, Niederschlag, Wind, Sonnenauf- und -untergang.",
            schema({
                "location": {"type": "string", "description": "Stadt oder Ort."},
                "days": {"type": "integer", "minimum": 1, "maximum": 16, "default": 7},
            }, ["location"], strict=True),
            get_weather_forecast,
            source="builtin_weather",
        )

        self.register_tool(
            "search_events",
            "Durchsucht den ComputeMesh Event-Index nach lokalen Veranstaltungen und liefert kategorisierte Treffer im Radius.",
            schema({
                "city": {"type": "string", "description": "Stadt oder Gemeinde."},
                "radius_km": {"type": "number", "minimum": 1, "maximum": 300, "default": 50},
                "categories": {"type": "array", "items": {"type": "string"}},
                "date_from": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                "date_to": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                "query_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                "day_scope": {"type": "string", "enum": ["today", "today_tomorrow", "range"], "default": "today_tomorrow"},
                "sort": {"type": "string", "enum": ["recommended", "date", "quality"], "default": "recommended"},
                "max_events": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
            }, ["city"], strict=True),
            search_events,
            source="builtin_events",
        )

        self.register_tool(
            "search_places",
            "Sucht strukturierte Orte, POIs und benannte lokale Betriebe über OpenStreetMap.",
            schema({
                "query": {"type": "string", "description": "Name oder Art des gesuchten Ortes/Betriebs."},
                "location": {"type": "string", "description": "Optionaler Orts-/Regionskontext."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            }, ["query"], strict=True),
            search_places,
            source="builtin_places",
        )

        self.register_tool(
            "get_sports_data",
            "Liefert aktuelle Team- und Spielplandaten aus der freien TheSportsDB-API.",
            schema({
                "query": {"type": "string", "description": "Teamname für mode=teams."},
                "mode": {"type": "string", "enum": ["teams", "events", "next_league", "previous_league"], "default": "teams"},
                "date": {"type": "string", "description": "YYYY-MM-DD für mode=events."},
                "sport": {"type": "string", "description": "Optionaler Sportfilter."},
                "league": {"type": "string", "description": "Optionaler Ligafilter."},
                "league_id": {"type": "string", "description": "Numerische TheSportsDB League-ID."},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            }, strict=True),
            get_sports_data,
            source="builtin_sports",
        )

        self.register_tool(
            "lookup_company",
            "Sucht Rechtsträger im globalen GLEIF-LEI-Register und liefert standardisierte Registrierungs- und Adressdaten.",
            schema({
                "name": {"type": "string", "description": "Unternehmens-/Rechtsträgername."},
                "country": {"type": "string", "description": "Optionaler ISO-2-Ländercode, z. B. DE."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            }, ["name"], strict=True),
            lookup_company,
            source="builtin_company",
        )

        self.register_tool(
            "calculate_math",
            "Führt mathematische Berechnungen in der eingeschränkten Python-Rechenumgebung aus.",
            schema({"expression": {"type": "string"}}, ["expression"]),
            run_python_calc,
            source="builtin_math",
        )

        self.register_tool(
            "get_wikipedia_summary",
            "Liefert lexikalische Zusammenfassungen und Fakten aus Wikipedia.",
            schema({
                "query": {"type": "string"},
                "language": {"type": "string", "default": "de"},
            }, ["query"]),
            get_wikipedia_summary,
            source="builtin_wiki",
        )

        self.register_tool(
            "fetch_multilingual_wikipedia",
            "Durchsucht gleichzeitig die deutsche und englische Wikipedia nach detaillierten enzyklopädischen Artikeln, Infoboxen und Hintergründen.",
            schema({
                "query": {"type": "string", "description": "Suchbegriff oder Thema."},
            }, ["query"]),
            fetch_multilingual_wikipedia,
            source="builtin_wiki_multilingual",
        )

        self.register_tool(
            "cross_source_knowledge_search",
            "Führt eine hochintelligente, fundierte Tiefenrecherche durch (kombiniert parallel deutsche und englische Wikipedia, Echtzeit-Nachrichtenagenturen wie Tagesschau/Spiegel/Reuters und Live-Websuche mit Quellenverifikation).",
            schema({
                "query": {"type": "string", "description": "Zu recherchierendes Thema, Person, Konflikt, Ereignis oder Frage."},
            }, ["query"]),
            cross_source_knowledge_search,
            source="builtin_knowledge_fusion",
        )

        self.register_tool(
            "fetch_recent_timeline",
            "Erstellt eine chronologische Zeitleiste mit Daten, Kurzbeschreibungen und Quellen zu einem aktuellen Thema, Konflikt oder Ereignis.",
            schema({
                "topic": {"type": "string", "description": "Thema, Person oder Region für die Ereignis-Zeitleiste."},
                "max_events": {"type": "integer", "description": "Maximale Anzahl an Ereignissen.", "default": 6},
            }, ["topic"]),
            fetch_recent_timeline,
            source="builtin_timeline",
        )

        self.register_tool(
            "verify_fact_multi_source",
            "Überprüft eine Tatsachenbehauptung unabhängig über Wikipedia, Nachrichtenagenturen und Webquellen.",
            schema({
                "claim": {"type": "string", "description": "Zu überprüfende Aussage oder Behauptung."},
            }, ["claim"]),
            verify_fact_multi_source,
            source="builtin_fact_check",
        )

        self.register_tool(
            "get_time_and_calendar",
            "Liefert aktuelle Uhrzeit, Zeitzonen-, Kalender- und deutsche Feiertagsdaten.",
            schema({
                "timezone_name": {"type": "string", "default": "Europe/Berlin"},
                "target_date": {"type": "string"},
                "state": {"type": "string", "default": "BY"},
            }),
            get_time_and_calendar,
            source="builtin_time",
        )

        self.register_tool(
            "convert_currency",
            "Rechnet Geldbeträge live zwischen Fiat- und unterstützten Kryptowährungen um.",
            schema({
                "amount": {"type": "number", "default": 1.0},
                "from_currency": {"type": "string", "default": "EUR"},
                "to_currency": {"type": "string", "default": "USD"},
            }, ["amount", "from_currency", "to_currency"]),
            convert_currency,
            source="builtin_currency",
        )

        self.register_tool(
            "get_distance_route",
            "Berechnet Luftlinie, Fahrtstrecke, Koordinaten und Fahrzeit zwischen zwei Orten.",
            schema({
                "origin": {"type": "string"},
                "destination": {"type": "string"},
            }, ["origin", "destination"]),
            get_distance_route,
            source="builtin_geo",
        )

        self.register_tool(
            "lookup_country_data",
            "Liefert strukturierte Länder- und Demografiedaten.",
            schema({"country": {"type": "string"}}, ["country"]),
            lookup_country_data,
            source="builtin_open_data",
        )

        self.register_tool(
            "get_world_bank_stats",
            "Liefert offizielle makroökonomische Indikatoren der Weltbank.",
            schema({
                "country": {"type": "string", "default": "DEU"},
                "indicator": {"type": "string", "default": "gdp"},
            }, ["country"]),
            get_world_bank_stats,
            source="builtin_open_data",
        )

        self.register_tool(
            "search_arxiv_papers",
            "Durchsucht arXiv nach wissenschaftlichen Arbeiten und Preprints.",
            schema({
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 5},
            }, ["query"]),
            search_arxiv_papers,
            source="builtin_open_data",
        )

        self.register_tool(
            "lookup_food_product",
            "Liefert Inhaltsstoffe, Allergene und Nährwerte aus Open Food Facts.",
            schema({"product_name": {"type": "string"}}, ["product_name"]),
            lookup_food_product,
            source="builtin_open_data",
        )

        self.register_tool(
            "lookup_software_package",
            "Liefert Paketinformationen und bekannte OSV/CVE-Sicherheitslücken für PyPI/NPM.",
            schema({
                "package_name": {"type": "string"},
                "ecosystem": {"type": "string", "default": "pypi"},
            }, ["package_name"]),
            lookup_software_package,
            source="builtin_open_data",
        )

        self.register_tool(
            "get_recent_earthquakes",
            "Liefert aktuelle weltweite Erdbebendaten der USGS.",
            schema({
                "min_magnitude": {"type": "number", "default": 4.0},
                "limit": {"type": "integer", "default": 5},
            }),
            get_recent_earthquakes,
            source="builtin_open_data",
        )

        self.register_tool(
            "lookup_chemical_compound",
            "Liefert chemische Eigenschaften aus PubChem.",
            schema({"compound_name": {"type": "string"}}, ["compound_name"]),
            lookup_chemical_compound,
            source="builtin_open_data",
        )

        self.register_tool(
            "lookup_word_definition",
            "Liefert englische Definitionen, Phonetik, Wortarten und Synonyme.",
            schema({"word": {"type": "string"}}, ["word"]),
            lookup_word_definition,
            source="builtin_open_data",
        )

        self.register_tool(
            "lookup_train_schedule",
            "Liefert Bahn-Abfahrten, Linien, Gleise und Echtzeit-Verspätungen.",
            schema({
                "station": {"type": "string"},
                "max_results": {"type": "integer", "default": 5},
            }, ["station"]),
            lookup_train_schedule,
            source="builtin_open_data",
        )

        self.register_tool(
            "lookup_network_host",
            "Führt sichere Netzwerkdiagnosen für eine öffentliche Domain aus.",
            schema({
                "host": {"type": "string"},
                "check_type": {"type": "string", "default": "all"},
            }, ["host"]),
            lookup_network_host,
            owner_only=True,
            source="builtin_network",
        )

        self.register_tool(
            "generate_ai_image",
            "Generiert hochauflösende, fotorealistische KI-Bilder (1024x1024 / SDXL RealVisXL) mit der lokalen GPU oder Cloud-Fallback.",
            schema({
                "prompt": {"type": "string", "description": "Detaillierte Beschreibung des gewünschten Bildes (deutsch oder englisch)."},
                "style": {"type": "string", "description": "Optionaler Stil (photorealistic, cinematic, artistic, oil_painting, anime, cyberpunk, 3d_render).", "default": "photorealistic"},
                "width": {"type": "integer", "description": "Breite in Pixel (Standard 1024).", "default": 1024},
                "height": {"type": "integer", "description": "Höhe in Pixel (Standard 1024).", "default": 1024},
            }, ["prompt"]),
            generate_ai_image,
            source="builtin_image",
        )

        self.register_tool(
            "check_url_safety",
            "Prüft URLs auf Sicherheitsrisiken, interne/private Netzwerkadressen (SSRF-Schutz) und DNS-Integrität.",
            schema({"url": {"type": "string", "description": "Zu prüfende vollständige URL (z. B. https://example.com)."}}, ["url"]),
            check_url_safety,
            source="builtin_security",
        )

        self.register_tool(
            "execute_python_code",
            "Führt mehrzeiligen Python-Code in einer sicheren Data-Science-Sandbox aus (Pandas, Numpy, Matplotlib) und gibt Textausgaben sowie generierte Diagramme (PNG) zurück.",
            schema({
                "code": {"type": "string", "description": "Vollständiger mehrzeiliger Python-Code zur Ausführung."},
            }, ["code"]),
            execute_python_code,
            source="builtin_sandbox",
        )

        self.register_tool(
            "search_knowledge_base",
            "Durchsucht die lokale Dokumenten-Wissensdatenbank (PDFs, Dokumente, Codebasen) semantisch mittels Vektorsuche und liefert relevante Textauszüge mit Quellenangabe.",
            schema({
                "query": {"type": "string", "description": "Suchanfrage, Frage oder Schlagworte."},
                "top_k": {"type": "integer", "description": "Anzahl relevanter Textstellen (Standard 4).", "default": 4},
                "collection": {"type": "string", "description": "Name der Vektorsammlung.", "default": "default"},
            }, ["query"]),
            search_knowledge_base,
            source="builtin_rag",
        )

        self.register_tool(
            "index_document_text",
            "Fügt Textinhalte oder Dokumente zur persistenten Vektordatenbank hinzu.",
            schema({
                "text": {"type": "string", "description": "Textinhalt des Dokuments."},
                "filename": {"type": "string", "description": "Dateiname oder Dokumententitel.", "default": "document.txt"},
                "collection": {"type": "string", "description": "Name der Vektorsammlung.", "default": "default"},
            }, ["text"]),
            index_document_text,
            source="builtin_rag",
        )

        self.register_tool(
            "list_indexed_documents",
            "Listet alle aktuell in der Wissensdatenbank gespeicherten Dokumente auf.",
            schema({
                "collection": {"type": "string", "description": "Name der Vektorsammlung.", "default": "default"},
            }),
            list_indexed_documents,
            source="builtin_rag",
        )

        self.register_tool(
            "update_user_memory",
            "Speichert oder aktualisiert eine wichtige Benutzereigenschaft, Präferenz oder Projektkontext im persistenten Langzeitgedächtnis.",
            schema({
                "key": {"type": "string", "description": "Schlüsselbegriff (z. B. preferred_language, hardware_gpu, coding_style)."},
                "value": {"type": "string", "description": "Zu merkender Fakt oder Information."},
                "category": {"type": "string", "description": "Kategorie (z. B. general, preferences, hardware, project).", "default": "general"},
            }, ["key", "value"]),
            update_user_memory,
            source="builtin_memory",
        )

        self.register_tool(
            "get_user_memory",
            "Ruft gespeicherte Fakten und Benutzereigenschaften aus dem persistenten Langzeitgedächtnis ab.",
            schema({
                "key": {"type": "string", "description": "Optionaler Schlüsselbegriff. Wenn weggelassen, werden alle Fakten zurückgegeben."},
            }),
            get_user_memory,
            source="builtin_memory",
        )

        self.register_tool(
            "get_gpu_telemetry",
            "Liefert detaillierte GPU-Hardware-Telemetrie (NVIDIA CUDA / AMD ROCm VRAM-Auslastung, Temperatur, Compute-Load).",
            schema({}),
            execute_gpu_telemetry,
            source="builtin_system",
        )

        self.register_tool(
            "list_workspace_files",
            "Listet Dateien und Unterverzeichnisse im lokalen Workspace auf (mit Pfad-Sicherheitsprüfungen).",
            schema({
                "relative_path": {"type": "string", "description": "Relativer Pfad im Workspace (Standard '.').", "default": "."},
                "pattern": {"type": "string", "description": "Optionales Glob-Muster (z. B. '*.py', '*.json')."},
                "max_depth": {"type": "integer", "description": "Maximale Verzeichnistiefe (1-5, Standard 3).", "default": 3},
            }),
            list_workspace_files,
            source="builtin_filesystem",
        )

        self.register_tool(
            "read_workspace_file",
            "Liest Textzeilen aus einer Datei im Workspace mit Größenbegrenzung und Bereichswahl.",
            schema({
                "relative_path": {"type": "string", "description": "Relativer Dateipfad im Workspace."},
                "max_lines": {"type": "integer", "description": "Maximale Anzahl an Zeilen (Standard 200).", "default": 200},
                "offset_line": {"type": "integer", "description": "Startzeilennummer (1-basiert, Standard 1).", "default": 1},
            }, ["relative_path"]),
            read_workspace_file,
            source="builtin_filesystem",
        )

        self.register_tool(
            "analyze_data_table",
            "Analysiert Tabellendaten (CSV oder JSON-Arrays) und berechnet statistische Zusammenfassungen (Min, Max, Mean, Median, Nullwerte, Datentypen).",
            schema({
                "data": {"type": "string", "description": "CSV-Text oder JSON-Array von Objekten."},
                "delimiter": {"type": "string", "description": "Optionales CSV-Trennzeichen (z. B. ',', ';', '\\t')."},
                "max_sample_rows": {"type": "integer", "description": "Anzahl an Beispielzeilen (Standard 5).", "default": 5},
            }, ["data"]),
            analyze_data_table,
            source="builtin_data",
        )

        self.register_tool(
            "extract_document_content",
            "Extrahiert strukturierte Abschnitte, Überschriften und Stichpunkte aus Markdown-, Text- oder Log-Dateien.",
            schema({
                "content_or_path": {"type": "string", "description": "Dokumentinhalt oder lokaler Dateipfad."},
                "max_sections": {"type": "integer", "description": "Maximale Anzahl Abschnitte (Standard 10).", "default": 10},
                "extract_bullet_points": {"type": "boolean", "description": "Ob Stichpunkte extrahiert werden sollen.", "default": True},
            }, ["content_or_path"]),
            extract_document_content,
            source="builtin_document",
        )

        self.register_tool(
            "generate_office_document",
            "Erstellt strukturierte Office-Dokumente und Tabellen (.xlsx / Excel, .csv, .html, .md) aus Daten, Tabellen oder Zusammenfassungen.",
            schema({
                "file_format": {"type": "string", "description": "Dateiformat: 'xlsx' (Excel), 'csv', 'md' (Markdown), 'html', 'json'.", "default": "xlsx"},
                "title": {"type": "string", "description": "Titel des Dokuments oder Tabellenblatts.", "default": "Export"},
                "data": {"description": "Tabellendaten (Liste von Objekten, CSV-Text oder Schlüssel-Wert-Paare)."},
                "markdown_content": {"type": "string", "description": "Optionaler Markdown-Begleittext oder Analyse."},
                "filename": {"type": "string", "description": "Optionaler Zieldateiname (z. B. 'Vergleich.xlsx')."},
            }),
            generate_office_document,
            source="builtin_office",
        )

        self.register_tool(
            "parse_office_document",
            "Liest und analysiert Office-Tabellen (Excel .xlsx, .xls, .csv), Word-Dateien (.docx), PDFs und Markdown in strukturierte Tabellen.",
            schema({
                "file_path_or_content": {"type": "string", "description": "Dateipfad im Workspace oder Rohtext/CSV."},
                "file_format": {"type": "string", "description": "Optionales Format ('xlsx', 'csv', 'docx', 'pdf', 'md')."},
                "max_preview_rows": {"type": "integer", "description": "Maximale Anzahl an Vorschaudatensätzen (Standard 15).", "default": 15},
            }, ["file_path_or_content"]),
            parse_office_document,
            source="builtin_office",
        )

        self.register_tool(
            "convert_data_to_markdown_table",
            "Konvertiert Datensätze (JSON-Array, Liste von Objekten, CSV-String oder Key-Value-Map) in eine formatierte GitHub Markdown-Tabelle.",
            schema({
                "data": {"description": "Zu formatierende Daten (Liste von Objekten, CSV oder JSON)."},
                "columns": {"type": "array", "items": {"type": "string"}, "description": "Optionale Spaltenauswahl."},
                "sort_by": {"type": "string", "description": "Optionale Sortierspalte."},
                "ascending": {"type": "boolean", "description": "Sortierreihenfolge (Standard True).", "default": True},
                "title": {"type": "string", "description": "Optionaler Tabellentitel."},
            }, ["data"]),
            convert_data_to_markdown_table,
            source="builtin_office",
        )

        self.register_tool(
            "transcribe_audio_data",
            "Transkribiert Audiodaten (Base64 oder Audiodatei) in strukturierten Text mit Zeitstempeln.",
            schema({
                "audio_data_base64_or_path": {"type": "string", "description": "Base64-kodierte Audiodaten oder Pfad."},
                "language": {"type": "string", "description": "Sprachcode (z. B. 'de', 'en').", "default": "de"},
            }, ["audio_data_base64_or_path"]),
            transcribe_audio_data,
            source="builtin_multimodal",
        )

        self.register_tool(
            "synthesize_speech_audio",
            "Erstellt Audiosynthese-Metadaten für Sprachausgabe.",
            schema({
                "text": {"type": "string", "description": "Vorzulesender Text."},
                "voice": {"type": "string", "description": "Stimmprofil.", "default": "de-DE-Standard-A"},
                "speed": {"type": "number", "description": "Sprechgeschwindigkeit (0.5 - 2.0).", "default": 1.0},
            }, ["text"]),
            synthesize_speech_audio,
            source="builtin_multimodal",
        )

        if self.config.system_tools_enabled:
            self.register_tool(
                "get_system_info",
                "Liefert Host-, OS-, CPU-, RAM- und Festplatten-Telemetrie des Compute-Knotens.",
                schema({}),
                execute_system_info,
                owner_only=True,
                source="builtin_system",
            )

        self.register_tool(
            "replace_file_content",
            "Ersetzt einen exakten Codeblock in einer Datei im Workspace mit Zeilenbereichseingrenzung und Diff-Vorschau.",
            schema({
                "file_path": {"type": "string", "description": "Relativer oder absoluter Pfad zur Zieldatei."},
                "target_content": {"type": "string", "description": "Exakter Quelltext-Abschnitt, der ersetzt werden soll."},
                "replacement_content": {"type": "string", "description": "Neuer Ersatz-Code."},
                "start_line": {"type": "integer", "description": "Optionale Startzeilennummer (1-basiert)."},
                "end_line": {"type": "integer", "description": "Optionale Endzeilennummer (1-basiert)."},
                "allow_multiple": {"type": "boolean", "description": "Ob mehrfaches Vorkommen ersetzt werden darf.", "default": False},
            }, ["file_path", "target_content", "replacement_content"]),
            replace_file_content,
            source="builtin_coding",
        )

        self.register_tool(
            "multi_replace_file_content",
            "Wendet mehrere nicht-zusammenhängende Code-Ersetzungen atomar auf eine Zieldatei an.",
            schema({
                "file_path": {"type": "string", "description": "Pfad zur Zieldatei."},
                "replacement_chunks": {
                    "type": "array",
                    "description": "Liste von Ersetzungsblöcken mit target_content und replacement_content.",
                    "items": {"type": "object"},
                },
            }, ["file_path", "replacement_chunks"]),
            multi_replace_file_content,
            source="builtin_coding",
        )

        self.register_tool(
            "grep_search_code",
            "Durchsucht Projektdateien blitzschnell nach Textmustern oder regulären Ausdrücken (mit Dateifilter und Zeilennummern).",
            schema({
                "query": {"type": "string", "description": "Suchbegriff oder regulärer Ausdruck."},
                "search_path": {"type": "string", "description": "Startverzeichnis für die Suche (Standard '.').", "default": "."},
                "is_regex": {"type": "boolean", "description": "Ob query als regulärer Ausdruck interpretiert werden soll.", "default": False},
                "case_insensitive": {"type": "boolean", "description": "Groß-/Kleinschreibung ignorieren.", "default": True},
                "includes": {"type": "array", "items": {"type": "string"}, "description": "Optionale Dateimuster wie ['*.py', '*.go']."},
                "max_results": {"type": "integer", "description": "Maximale Trefferanzahl.", "default": 50},
            }, ["query"]),
            grep_search_code,
            source="builtin_coding",
        )

        self.register_tool(
            "extract_code_symbols",
            "Extrahiert Klassen, Funktionen, Methoden, Interfaces und Structs aus einer Quellcodedatei (Python AST, Go, Kotlin, JS/TS).",
            schema({
                "file_path": {"type": "string", "description": "Pfad zur Quellcodedatei."},
            }, ["file_path"]),
            extract_code_symbols,
            source="builtin_coding",
        )

        self.register_tool(
            "validate_code_syntax",
            "Validiert die Syntax von Quellcode vor der Ausführung oder Speicherung (Python AST, JSON, YAML, Go).",
            schema({
                "code": {"type": "string", "description": "Zu prüfender Quellcode."},
                "language": {"type": "string", "description": "Programmiersprache (python, json, yaml, go).", "default": "python"},
            }, ["code"]),
            validate_code_syntax,
            source="builtin_coding",
        )

        self.register_tool(
            "check_code_quality",
            "Prüft Quellcode auf Code-Smells, übermäßig lange Funktionen (>60 Zeilen) und fehlende Dokumentation.",
            schema({
                "code": {"type": "string", "description": "Zu analysierender Quellcode."},
                "language": {"type": "string", "description": "Programmiersprache (Standard 'python').", "default": "python"},
            }, ["code"]),
            check_code_quality,
            source="builtin_coding",
        )

        self.register_tool(
            "run_project_tests",
            "Führt automatisierte Test-Suites (pytest, go test, npm test, cargo test) aus und parst Fehlerberichte strukturiert.",
            schema({
                "framework": {"type": "string", "description": "Test-Framework (pytest, go, npm, cargo).", "default": "pytest"},
                "test_path": {"type": "string", "description": "Testverzeichnis oder Datei (Standard '.').", "default": "."},
                "filter_pattern": {"type": "string", "description": "Optionaler Testfilter (z. B. '-k test_name')."},
                "timeout_seconds": {"type": "number", "description": "Timeout in Sekunden.", "default": 45.0},
            }),
            run_project_tests,
            source="builtin_coding",
        )

        self.register_tool(
            "get_git_status",
            "Liefert den aktuellen Git-Branch sowie geänderte, gestagte und ungetrackte Dateien des Workspaces.",
            schema({
                "repo_path": {"type": "string", "description": "Pfad zum Git-Repository (Standard '.').", "default": "."},
            }),
            get_git_status,
            source="builtin_coding",
        )

        self.register_tool(
            "get_git_diff",
            "Zeigt den Unified-Diff ungespeicherter oder gestagter Änderungen im Workspace.",
            schema({
                "repo_path": {"type": "string", "description": "Pfad zum Git-Repository.", "default": "."},
                "file_path": {"type": "string", "description": "Optionaler Filter auf eine bestimmte Datei."},
                "staged": {"type": "boolean", "description": "Ob gestagte Änderungen angezeigt werden sollen.", "default": False},
            }),
            get_git_diff,
            source="builtin_coding",
        )

        self.register_tool(
            "get_git_log",
            "Liefert die Commit-Historie des Git-Repositories mit Hash, Datum, Autor und Commit-Nachricht.",
            schema({
                "repo_path": {"type": "string", "description": "Pfad zum Git-Repository.", "default": "."},
                "max_count": {"type": "integer", "description": "Maximale Anzahl Commits.", "default": 10},
            }),
            get_git_log,
            source="builtin_coding",
        )

        self.register_tool(
            "run_terminal_command",
            "Führt Shell-Befehle im Workspace sicher aus (mit Timeout- und Sicherheitsprüfung gegen destruktive Kommandos).",
            schema({
                "command": {"type": "string", "description": "Auszuführender Shell-Befehl."},
                "cwd": {"type": "string", "description": "Arbeitsverzeichnis (Standard '.').", "default": "."},
                "timeout_seconds": {"type": "number", "description": "Timeout in Sekunden.", "default": 30.0},
            }, ["command"]),
            run_terminal_command,
            source="builtin_developer",
        )

        self.register_tool(
            "execute_http_request",
            "Führt universelle HTTP-Requests (GET, POST, PUT, DELETE, PATCH) an REST-APIs oder Web-Endpunkte aus.",
            schema({
                "url": {"type": "string", "description": "Ziel-URL des HTTP-Requests."},
                "method": {"type": "string", "description": "HTTP-Methode (GET, POST, PUT, DELETE, PATCH).", "default": "GET"},
                "headers": {"type": "object", "description": "Optionale HTTP-Header als Key-Value-Map."},
                "params": {"type": "object", "description": "Optionale Query-Parameter."},
                "body": {"type": "string", "description": "Optionaler Request-Body (JSON oder Text)."},
                "timeout_seconds": {"type": "number", "description": "Timeout in Sekunden.", "default": 20.0},
            }, ["url"]),
            execute_http_request,
            source="builtin_developer",
        )

        self.register_tool(
            "github_get_repo",
            "Ruft umfassende GitHub-Repository-Metadaten ab (Sterne, Forks, Sprache, Open Issues, Lizenz, Default Branch).",
            schema({
                "owner": {"type": "string", "description": "Repository-Owner / Organisation."},
                "repo": {"type": "string", "description": "Repository-Name."},
            }, ["owner", "repo"]),
            github_get_repo,
            source="builtin_github",
        )

        self.register_tool(
            "github_search_repositories",
            "Sucht GitHub-Repositories nach Suchbegriffen oder Topics.",
            schema({
                "query": {"type": "string", "description": "Suchbegriff oder GitHub Search Query."},
                "limit": {"type": "integer", "description": "Maximale Trefferanzahl (1-30).", "default": 10},
            }, ["query"]),
            github_search_repositories,
            source="builtin_github",
        )

        self.register_tool(
            "github_get_file_contents",
            "Liest den Inhalt einer Datei direkt aus einem GitHub-Repository (dekodiert Base64 automatisch).",
            schema({
                "owner": {"type": "string", "description": "Repository-Owner."},
                "repo": {"type": "string", "description": "Repository-Name."},
                "path": {"type": "string", "description": "Dateipfad im Repository."},
                "ref": {"type": "string", "description": "Branch, Tag oder Commit-SHA (Standard: Default Branch)."},
            }, ["owner", "repo", "path"]),
            github_get_file_contents,
            source="builtin_github",
        )

        self.register_tool(
            "github_list_repo_tree",
            "Listet den Dateibaum oder Verzeichnisinhalt eines GitHub-Repositories auf.",
            schema({
                "owner": {"type": "string", "description": "Repository-Owner."},
                "repo": {"type": "string", "description": "Repository-Name."},
                "path": {"type": "string", "description": "Verzeichnispfad (Standard: Root).", "default": ""},
                "ref": {"type": "string", "description": "Branch oder Commit-SHA."},
            }, ["owner", "repo"]),
            github_list_repo_tree,
            source="builtin_github",
        )

        self.register_tool(
            "github_search_code",
            "Sucht nach Code-Snippets in GitHub-Repositories.",
            schema({
                "query": {"type": "string", "description": "Suchbegriff für Code."},
                "owner": {"type": "string", "description": "Optionaler Owner/Org zur Einschränkung."},
                "repo": {"type": "string", "description": "Optionaler Repository-Name zur Einschränkung."},
                "limit": {"type": "integer", "description": "Maximale Trefferanzahl (1-30).", "default": 10},
            }, ["query"]),
            github_search_code,
            source="builtin_github",
        )

        self.register_tool(
            "github_list_issues",
            "Listet Issues eines GitHub-Repositories auf (Filter nach state: open/closed/all, labels).",
            schema({
                "owner": {"type": "string", "description": "Repository-Owner."},
                "repo": {"type": "string", "description": "Repository-Name."},
                "state": {"type": "string", "description": "Status (open, closed, all).", "default": "open"},
                "labels": {"type": "string", "description": "Kommagetrennte Label-Filter."},
                "limit": {"type": "integer", "description": "Maximale Anzahl.", "default": 20},
            }, ["owner", "repo"]),
            github_list_issues,
            source="builtin_github",
        )

        self.register_tool(
            "github_get_issue",
            "Ruft ein einzelnes GitHub-Issue inklusive Kommentare und Label-Details ab.",
            schema({
                "owner": {"type": "string", "description": "Repository-Owner."},
                "repo": {"type": "string", "description": "Repository-Name."},
                "issue_number": {"type": "integer", "description": "Issue-Nummer."},
            }, ["owner", "repo", "issue_number"]),
            github_get_issue,
            source="builtin_github",
        )

        self.register_tool(
            "github_create_issue",
            "Erstellt ein neues Issue in einem GitHub-Repository (Authentifizierung per GITHUB_TOKEN erforderlich).",
            schema({
                "owner": {"type": "string", "description": "Repository-Owner."},
                "repo": {"type": "string", "description": "Repository-Name."},
                "title": {"type": "string", "description": "Titel des Issues."},
                "body": {"type": "string", "description": "Beschreibung / Markdown-Text."},
                "labels": {"type": "array", "description": "Optionale Liste von Labels.", "items": {"type": "string"}},
            }, ["owner", "repo", "title"]),
            github_create_issue,
            source="builtin_github",
        )

        self.register_tool(
            "github_add_issue_comment",
            "Fügt einen Kommentar zu einem GitHub-Issue oder PR hinzu.",
            schema({
                "owner": {"type": "string", "description": "Repository-Owner."},
                "repo": {"type": "string", "description": "Repository-Name."},
                "issue_number": {"type": "integer", "description": "Issue-Nummer."},
                "body": {"type": "string", "description": "Kommentartext in Markdown."},
            }, ["owner", "repo", "issue_number", "body"]),
            github_add_issue_comment,
            source="builtin_github",
        )

        self.register_tool(
            "github_list_pull_requests",
            "Listet Pull Requests eines GitHub-Repositories auf (state: open/closed/all).",
            schema({
                "owner": {"type": "string", "description": "Repository-Owner."},
                "repo": {"type": "string", "description": "Repository-Name."},
                "state": {"type": "string", "description": "Status (open, closed, all).", "default": "open"},
                "limit": {"type": "integer", "description": "Maximale Anzahl.", "default": 20},
            }, ["owner", "repo"]),
            github_list_pull_requests,
            source="builtin_github",
        )

        self.register_tool(
            "github_get_pull_request",
            "Ruft detaillierte Informationen zu einem Pull Request ab (Zweig-Infos, Merge-Status, Reviewer).",
            schema({
                "owner": {"type": "string", "description": "Repository-Owner."},
                "repo": {"type": "string", "description": "Repository-Name."},
                "pull_number": {"type": "integer", "description": "PR-Nummer."},
            }, ["owner", "repo", "pull_number"]),
            github_get_pull_request,
            source="builtin_github",
        )

        self.register_tool(
            "github_get_pull_request_diff",
            "Liefert den Unified-Diff eines GitHub Pull Requests.",
            schema({
                "owner": {"type": "string", "description": "Repository-Owner."},
                "repo": {"type": "string", "description": "Repository-Name."},
                "pull_number": {"type": "integer", "description": "PR-Nummer."},
            }, ["owner", "repo", "pull_number"]),
            github_get_pull_request_diff,
            source="builtin_github",
        )

        self.register_tool(
            "github_get_pull_request_files",
            "Listet geänderte Dateien eines PRs mit Zeilen-Statistiken (Additions/Deletions) auf.",
            schema({
                "owner": {"type": "string", "description": "Repository-Owner."},
                "repo": {"type": "string", "description": "Repository-Name."},
                "pull_number": {"type": "integer", "description": "PR-Nummer."},
            }, ["owner", "repo", "pull_number"]),
            github_get_pull_request_files,
            source="builtin_github",
        )

        self.register_tool(
            "github_list_releases",
            "Listet Releases und Tags eines GitHub-Repositories auf.",
            schema({
                "owner": {"type": "string", "description": "Repository-Owner."},
                "repo": {"type": "string", "description": "Repository-Name."},
                "limit": {"type": "integer", "description": "Maximale Anzahl.", "default": 10},
            }, ["owner", "repo"]),
            github_list_releases,
            source="builtin_github",
        )

        self.register_tool(
            "github_get_latest_release",
            "Ruft das neueste Release eines GitHub-Repositories inklusive Changelog und Download-Assets ab.",
            schema({
                "owner": {"type": "string", "description": "Repository-Owner."},
                "repo": {"type": "string", "description": "Repository-Name."},
            }, ["owner", "repo"]),
            github_get_latest_release,
            source="builtin_github",
        )

        self.register_tool(
            "github_list_commits",
            "Ruft die Commit-Historie eines GitHub-Repositories ab.",
            schema({
                "owner": {"type": "string", "description": "Repository-Owner."},
                "repo": {"type": "string", "description": "Repository-Name."},
                "sha": {"type": "string", "description": "Branch oder Commit SHA."},
                "limit": {"type": "integer", "description": "Maximale Anzahl.", "default": 20},
            }, ["owner", "repo"]),
            github_list_commits,
            source="builtin_github",
        )

        self.register_tool(
            "github_get_workflow_runs",
            "Ruft GitHub Actions CI/CD-Workflow-Läufe ab (Status, Conclusion, Commit).",
            schema({
                "owner": {"type": "string", "description": "Repository-Owner."},
                "repo": {"type": "string", "description": "Repository-Name."},
                "status": {"type": "string", "description": "Optionaler Statusfilter (completed, in_progress, queued)."},
                "limit": {"type": "integer", "description": "Maximale Anzahl.", "default": 10},
            }, ["owner", "repo"]),
            github_get_workflow_runs,
            source="builtin_github",
        )

        self.register_tool(
            "run_doctor_diagnostics",
            "Führt umfassende System- & Workspace-Diagnosen (Compiler, Runtimes, GPU, RAM, Disk, Cluster, ADB) aus.",
            schema({
                "categories": {"type": "array", "description": "Optionale Liste von Kategorien.", "items": {"type": "string"}},
                "workspace_root": {"type": "string", "description": "Workspace-Wurzelverzeichnis (Standard: '.').", "default": "."},
            }),
            run_doctor_diagnostics,
            source="builtin_developer",
        )

        self.register_tool(
            "quarantine_stage_files",
            "Staged vorgeschlagene Codeänderungen isoliert im Quarantäne-Sandbox-Verzeichnis (.computemesh-quarantine/).",
            schema({
                "files": {"type": "object", "description": "Map von relativen Dateipfaden zu neuem Dateiinhalt."},
                "workspace_root": {"type": "string", "description": "Workspace-Wurzelverzeichnis.", "default": "."},
            }, ["files"]),
            quarantine_stage_files,
            source="builtin_coding",
        )

        self.register_tool(
            "quarantine_validate",
            "Validiert Syntax und AST-Korrektheit aller Dateien in einer Quarantäne-Transaktion.",
            schema({
                "txn_id": {"type": "string", "description": "Transaktions-ID der Quarantäne."},
                "workspace_root": {"type": "string", "description": "Workspace-Wurzelverzeichnis.", "default": "."},
            }, ["txn_id"]),
            quarantine_validate,
            source="builtin_coding",
        )

        self.register_tool(
            "quarantine_commit",
            "Überträgt validierte Quarantäne-Dateien atomar in den echten Projekt-Workspace.",
            schema({
                "txn_id": {"type": "string", "description": "Transaktions-ID der Quarantäne."},
                "workspace_root": {"type": "string", "description": "Workspace-Wurzelverzeichnis.", "default": "."},
            }, ["txn_id"]),
            quarantine_commit,
            source="builtin_coding",
        )

        self.register_tool(
            "quarantine_rollback",
            "Verwirft eine Quarantäne-Transaktion ohne Änderungen am Workspace vorzunehmen.",
            schema({
                "txn_id": {"type": "string", "description": "Transaktions-ID der Quarantäne."},
                "workspace_root": {"type": "string", "description": "Workspace-Wurzelverzeichnis.", "default": "."},
            }, ["txn_id"]),
            quarantine_rollback,
            source="builtin_coding",
        )

        self.register_tool(
            "mission_start",
            "Initialisiert ein persistentes strukturiertes Mission-Journal für mehrstufige Agenten-Ziele.",
            schema({
                "objective": {"type": "string", "description": "Hauptziel der Mission."},
                "constraints": {"type": "array", "description": "Optionale Liste von Einschränkungen.", "items": {"type": "string"}},
                "success_criteria": {"type": "array", "description": "Optionale Liste von Erfolgskriterien.", "items": {"type": "string"}},
            }, ["objective"]),
            mission_start,
            source="builtin_developer",
        )

        self.register_tool(
            "mission_log_step",
            "Protokolliert einen Ausführungsschritt oder Beweis im Mission-Journal.",
            schema({
                "mission_id": {"type": "string", "description": "ID der aktiven Mission."},
                "phase": {"type": "string", "description": "Phase (planning, staging, verification, etc.)."},
                "action": {"type": "string", "description": "Ausgeführte Aktion."},
                "evidence": {"type": "string", "description": "Nachweis oder Ergebnis.", "default": ""},
                "status": {"type": "string", "description": "Status (done, failed, blocked).", "default": "done"},
            }, ["mission_id", "phase", "action"]),
            mission_log_step,
            source="builtin_developer",
        )

        self.register_tool(
            "mission_verify_postconditions",
            "Überprüft die Einhaltung aller Erfolgskriterien einer Mission.",
            schema({
                "mission_id": {"type": "string", "description": "ID der Mission."},
                "checks": {"type": "array", "description": "Liste von Prüfkriterien mit 'name' und 'passed' (bool).", "items": {"type": "object"}},
            }, ["mission_id", "checks"]),
            mission_verify_postconditions,
            source="builtin_developer",
        )

        self.register_tool(
            "mission_get_summary",
            "Ruft den vollständigen Status, Verlauf und Checkpoint einer Mission ab.",
            schema({
                "mission_id": {"type": "string", "description": "ID der Mission."},
            }, ["mission_id"]),
            mission_get_summary,
            source="builtin_developer",
        )

        self.register_tool(
            "detect_missing_tools",
            "Prüft das System auf vorhandene vs. fehlende Entwickler-Tools und Paketmanager.",
            schema({
                "tool_names": {"type": "array", "description": "Optionale Liste von Tool-Namen.", "items": {"type": "string"}},
            }),
            detect_missing_tools,
            source="builtin_developer",
        )

        self.register_tool(
            "install_dev_tool",
            "Installiert ein fehlendes Entwickler-Tool sicher über pip oder npm.",
            schema({
                "tool_name": {"type": "string", "description": "Name des zu installierenden Tools (z.B. pytest, ruff, mypy)."},
                "package_manager": {"type": "string", "description": "Optionaler Paketmanager (pip, npm)."},
            }, ["tool_name"]),
            install_dev_tool,
            source="builtin_developer",
        )

        self.register_tool(
            "adb_list_devices",
            "Listet alle verbundenen Android Edge-Nodes, Smartphones und Emulatoren via ADB auf.",
            schema({}),
            adb_list_devices,
            source="builtin_developer",
        )

        self.register_tool(
            "adb_capture_screenshot",
            "Erstellt einen Echtzeit-Screenshot eines verbundenen Android Edge-Nodes.",
            schema({
                "device_id": {"type": "string", "description": "Optionale Device-ID."},
                "output_path": {"type": "string", "description": "Optionaler lokaler Speicherpfad."},
            }),
            adb_capture_screenshot,
            source="builtin_developer",
        )

        self.register_tool(
            "adb_install_app",
            "Installiert oder aktualisiert eine Android APK auf einem verbundenen Edge-Node.",
            schema({
                "apk_path": {"type": "string", "description": "Pfad zur APK-Datei."},
                "device_id": {"type": "string", "description": "Optionale Device-ID."},
            }, ["apk_path"]),
            adb_install_app,
            source="builtin_developer",
        )

        self.register_tool(
            "adb_get_system_log",
            "Liest System-Logcat-Einträge von einem verbundenen Android Edge-Node aus.",
            schema({
                "device_id": {"type": "string", "description": "Optionale Device-ID."},
                "lines": {"type": "integer", "description": "Zeilenanzahl (Standard: 50).", "default": 50},
                "filter_tag": {"type": "string", "description": "Optionaler Tag-Filter."},
            }),
            adb_get_system_log,
            source="builtin_developer",
        )

        self.register_tool(
            "deploy_local_webapp",
            "Erstellt, sichert und hostet eine interaktive Web-App oder ein Spiel (HTML5/JS/Canvas) auf dem Node.",
            schema({
                "app_name": {"type": "string", "description": "Eindeutiger Name / URL-Slug der Anwendung (z.B. pacman, dashboard)."},
                "title": {"type": "string", "description": "Menschenlesbarer Titel der Anwendung."},
                "html_content": {"type": "string", "description": "Vollständiger HTML5-Code der Anwendung."},
                "js_content": {"type": "string", "description": "Optionaler separater JavaScript-Code (wird als app.js eingebunden)."},
                "css_content": {"type": "string", "description": "Optionaler separater CSS-Stylesheet-Code (wird als style.css eingebunden)."},
                "extra_files": {"type": "object", "description": "Optionale Map von zusätzlichen Dateien (z.B. app.json oder Configs)."},
                "description": {"type": "string", "description": "Kurze Beschreibung der Anwendung."},
            }, ["app_name", "title", "html_content"]),
            deploy_local_webapp,
            source="builtin_coding",
        )

        self.register_tool(
            "list_deployed_webapps",
            "Listet alle aktuell auf diesem Node gehosteten Web-Anwendungen und Spiele mit URLs auf.",
            schema({}),
            list_deployed_webapps,
            source="builtin_coding",
        )

        self.register_tool(
            "remove_deployed_webapp",
            "Löscht und deinstalliert eine gehostete Web-Anwendung sicher vom Node.",
            schema({
                "app_name": {"type": "string", "description": "Name / Slug der zu entfernenden WebApp."},
            }, ["app_name"]),
            remove_deployed_webapp,
            source="builtin_coding",
        )

        self.register_tool(
            "launch_deployed_webapp",
            "Öffnet oder startet eine installierte WebApp oder ein Spiel wie Pac-Man und liefert die spielbare URL.",
            schema({
                "app_name": {"type": "string", "description": "Name oder Slug des Spiels / der App (z.B. pacman)."},
            }),
            launch_deployed_webapp,
            source="builtin_coding",
        )

        def dynamic_compute_tool(task_description: str, inputs: Optional[Dict[str, Any]] = None, code: Optional[str] = None) -> Dict[str, Any]:
            from .dynamic.synthesizer import get_dynamic_tool_engine
            engine = get_dynamic_tool_engine()
            return engine.execute_dynamic_task(
                task_description=task_description,
                inputs=inputs or {},
                provided_code=code,
            )

        self.register_tool(
            "dynamic_compute_tool",
            "Autonomer Dynamic-MCP: Synthetisiert und führt on-demand deterministische Python-Micro-Tools für komplexe mathematische Berechnungen, Matrixoperationen, Simulationen oder proprietäre Datenkonvertierungen in einer 7-Stufen Zero-Trust Sandbox aus.",
            schema({
                "task_description": {"type": "string", "description": "Genaue Beschreibung der Berechnung, Transformation oder Analyse."},
                "inputs": {"type": "object", "description": "Eingabedaten / Parameter als Dictionary.", "default": {}},
                "code": {"type": "string", "description": "Optionaler vorab definierter Python-Code mit 'def execute(inputs: dict) -> dict'."},
            }, ["task_description"]),
            dynamic_compute_tool,
            source="builtin_dynamic",
        )

        def get_ledger_status() -> Dict[str, Any]:
            from .ledger import get_compact_ledger
            return get_compact_ledger().get_stats()

        self.register_tool(
            "get_ledger_status",
            "Liefert Metriken, Block-Höhe, Transaktionsanzahl und den kryptografischen Integritätsstatus der internen ComputeMesh Proof-of-Execution Blockchain.",
            schema({}),
            get_ledger_status,
            source="builtin_ledger",
        )

        def verify_proof_of_execution(receipt_id: str) -> Dict[str, Any]:
            from .ledger import get_compact_ledger, MerkleTree
            ledger = get_compact_ledger()
            res = ledger.get_receipt(receipt_id)
            if not res:
                return {"error": f"Kein Proof-of-Execution für Receipt-ID '{receipt_id}' gefunden.", "verified": False}
            
            is_valid = False
            if res.get("is_confirmed") and res.get("merkle_proof") is not None and res.get("block"):
                r_dict = res["receipt"]
                from .ledger.block import ProofOfExecutionReceipt
                receipt_obj = ProofOfExecutionReceipt(**r_dict)
                leaf_h = receipt_obj.compute_leaf_hash()
                expected_root = res["block"]["merkle_root"]
                is_valid = MerkleTree.verify_proof(leaf_h, res["merkle_proof"], expected_root)

            return {
                "receipt_id": receipt_id,
                "is_confirmed": res.get("is_confirmed", False),
                "block_index": res["receipt"].get("block_index"),
                "tool_name": res["receipt"].get("tool_name"),
                "elapsed_seconds": res["receipt"].get("elapsed_seconds"),
                "status": res["receipt"].get("status"),
                "node_id": res["receipt"].get("node_id"),
                "merkle_verified": is_valid,
                "timestamp": res["receipt"].get("timestamp"),
            }

        self.register_tool(
            "verify_proof_of_execution",
            "Verifiziert einen kryptografischen Proof-of-Execution (PoE) Receipt auf der internen ComputeMesh Blockchain über Merkle-Tree-Inclusion-Proofs.",
            schema({
                "receipt_id": {"type": "string", "description": "Eindeutige Receipt-ID (z. B. 'poe_1a2b3c4d5e6f7a8b')."},
            }, ["receipt_id"]),
            verify_proof_of_execution,
            source="builtin_ledger",
        )

        def save_dynamic_tool(
            name: str,
            description: str,
            parameters: Optional[Dict[str, Any]] = None,
            python_code: str = "",
            tags: Optional[List[str]] = None,
        ) -> Dict[str, Any]:
            from .dynamic.custom_tool_store import get_custom_tool_store
            store = get_custom_tool_store()
            res = store.save_tool(
                name=name,
                description=description,
                parameters=parameters or {},
                code=python_code,
                tags=tags or ["dynamic", "custom"],
            )
            store.load_into_registry(self)
            return res

        self.register_tool(
            "save_dynamic_tool",
            "Speichert und registriert ein benutzerdefiniertes oder synthetisiertes Python-Tool dauerhaft im Custom Tool Store (inklusive AST-Sicherheitscheck und automatischer MCP-Aktivierung).",
            schema({
                "name": {"type": "string", "description": "Eindeutiger Funktionsname (z. B. 'compute_custom_matrix')."},
                "description": {"type": "string", "description": "LLM-taugliche Funktionsbeschreibung."},
                "python_code": {"type": "string", "description": "Sicherer Python-Code mit 'def execute(inputs: dict) -> dict'."},
                "parameters": {"type": "object", "description": "JSON Schema der Eingabeparameter.", "default": {}},
                "tags": {"type": "array", "description": "Kategorie-Tags (z. B. ['math', 'finance']).", "items": {"type": "string"}},
            }, ["name", "description", "python_code"]),
            save_dynamic_tool,
            source="builtin_custom_tools",
        )

        def list_saved_custom_tools(
            tag: Optional[str] = None,
            search: Optional[str] = None,
        ) -> List[Dict[str, Any]]:
            from .dynamic.custom_tool_store import get_custom_tool_store
            return get_custom_tool_store().list_tools(tag=tag, search=search)

        self.register_tool(
            "list_saved_custom_tools",
            "Listet alle dauerhaft gespeicherten Custom-Tools inklusive Aufrufmetriken, Ausführungszeiten und Tags auf.",
            schema({
                "tag": {"type": "string", "description": "Optionaler Filter nach Kategorie-Tag."},
                "search": {"type": "string", "description": "Optionaler Suchtext in Name und Beschreibung."},
            }),
            list_saved_custom_tools,
            source="builtin_custom_tools",
        )

        def get_custom_tool_details(name: str) -> Dict[str, Any]:
            from .dynamic.custom_tool_store import get_custom_tool_store
            tool = get_custom_tool_store().get_tool(name)
            if not tool:
                return {"error": f"Custom Tool '{name}' existiert nicht."}
            return tool

        self.register_tool(
            "get_custom_tool_details",
            "Ruft Quellcode, Schema und Ausführungsstatistiken eines gespeicherten Custom-Tools ab.",
            schema({
                "name": {"type": "string", "description": "Name des abzufragenden Custom-Tools."},
            }, ["name"]),
            get_custom_tool_details,
            source="builtin_custom_tools",
        )

        def remove_dynamic_tool(name: str) -> Dict[str, Any]:
            from .dynamic.custom_tool_store import get_custom_tool_store
            store = get_custom_tool_store()
            deleted = store.delete_tool(name)
            self.unregister_tool(name)
            return {"name": name, "deleted": deleted}

        self.register_tool(
            "remove_dynamic_tool",
            "Löscht ein gespeichertes Custom-Tool dauerhaft aus dem Tool-Store und deregistriert es aus dem aktiven MCP-Katalog.",
            schema({
                "name": {"type": "string", "description": "Name des zu löschenden Custom-Tools."},
            }, ["name"]),
            remove_dynamic_tool,
            source="builtin_custom_tools",
        )

        def execute_custom_tool(name: str, inputs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
            from .dynamic.custom_tool_store import get_custom_tool_store
            return get_custom_tool_store().execute_tool(name=name, inputs=inputs or {})

        self.register_tool(
            "execute_custom_tool",
            "Führt ein gespeichertes Custom-Tool mit den angegebenen Eingabedaten in der Sandbox aus und erzeugt einen PoE-Blockchain-Receipt.",
            schema({
                "name": {"type": "string", "description": "Name des auszuführenden Custom-Tools."},
                "inputs": {"type": "object", "description": "Eingabedaten für das Tool als Key-Value Dictionary.", "default": {}},
            }, ["name"]),
            execute_custom_tool,
            source="builtin_custom_tools",
        )







