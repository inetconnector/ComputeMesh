# SPDX-License-Identifier: Apache-2.0
"""Persistent User Memory and Profile Extraction Engine for ComputeMesh."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("computemesh.memory")

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "memory"


@dataclass
class UserProfile:
    name: str = ""
    preferred_language: str = "Deutsch"
    preferences: List[str] = field(default_factory=list)
    facts: List[str] = field(default_factory=list)


class UserMemoryStore:
    """Thread-safe persistent key-value and fact store for cross-session user personalization."""

    def __init__(self, persist_dir: Optional[Path | str] = None, storage_path: Optional[Path | str] = None):
        if storage_path:
            self.persist_file = Path(storage_path)
            self.persist_dir = self.persist_file.parent
        else:
            self.persist_dir = Path(persist_dir or DATA_DIR)
            self.persist_file = self.persist_dir / "user_profile.json"
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._memories: Dict[str, Dict[str, Any]] = {}
        self._profile = UserProfile()
        self._load()

    def _load(self) -> None:
        with self._lock:
            if self.persist_file.exists():
                try:
                    with open(self.persist_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        self._memories = data.get("memories", {})
                        prof = data.get("profile", {})
                        if isinstance(prof, dict):
                            self._profile = UserProfile(
                                name=prof.get("name", ""),
                                preferred_language=prof.get("preferred_language", "Deutsch"),
                                preferences=prof.get("preferences", []),
                                facts=prof.get("facts", []),
                            )
                    log.info(f"Loaded {len(self._memories)} persistent memory facts")
                except Exception as exc:
                    log.warning(f"Error loading user memory: {exc}")
                    self._memories = {}
                    self._profile = UserProfile()
            else:
                self._memories = {}
                self._profile = UserProfile()

    def _save(self) -> None:
        with self._lock:
            try:
                temp_file = self.persist_dir / f"{self.persist_file.stem}.tmp"
                payload = {
                    "updated_at": int(time.time()),
                    "total_facts": len(self._memories),
                    "profile": asdict(self._profile),
                    "memories": self._memories,
                }
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                if temp_file.exists():
                    temp_file.replace(self.persist_file)
            except Exception as exc:
                log.error(f"Error saving user memory: {exc}")

    def update_profile(
        self,
        name: str = "",
        preferred_language: str = "",
        preferences: Optional[List[str]] = None,
        facts: Optional[List[str]] = None,
    ) -> UserProfile:
        with self._lock:
            if name:
                self._profile.name = name
            if preferred_language:
                self._profile.preferred_language = preferred_language
            if preferences is not None:
                self._profile.preferences = list(preferences)
            if facts is not None:
                self._profile.facts = list(facts)
            self._save()
            return self._profile

    def get_profile(self) -> UserProfile:
        with self._lock:
            return self._profile


    def update_memory(self, key: str, value: str, category: str = "general") -> Dict[str, Any]:
        """Stores or updates a persistent user memory fact."""
        clean_key = str(key or "").strip().lower().replace(" ", "_")
        clean_val = str(value or "").strip()
        if not clean_key or not clean_val:
            return {"error": "Schlüssel und Wert für Memory dürfen nicht leer sein", "success": False}

        with self._lock:
            self._memories[clean_key] = {
                "key": clean_key,
                "value": clean_val,
                "category": category.strip().lower(),
                "updated_at": int(time.time()),
            }
            self._save()

        return {
            "success": True,
            "key": clean_key,
            "value": clean_val,
            "category": category,
            "message": f"Erinnerung '{clean_key}' erfolgreich gespeichert.",
        }

    def get_memory(self, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._memories.get(key.strip().lower().replace(" ", "_"))

    def delete_memory(self, key: str) -> Dict[str, Any]:
        clean_key = str(key or "").strip().lower().replace(" ", "_")
        with self._lock:
            if clean_key in self._memories:
                del self._memories[clean_key]
                self._save()
                return {"success": True, "message": f"Erinnerung '{clean_key}' gelöscht."}
            return {"error": f"Erinnerung '{clean_key}' nicht gefunden", "success": False}

    def get_all_memories(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "total": len(self._memories),
                "memories": dict(self._memories),
            }

    def clear(self) -> None:
        with self._lock:
            self._memories.clear()
            self._save()

    def get_memory_summary(self) -> str:
        """Formats active memory facts into a compact system prompt injection string."""
        with self._lock:
            if not self._memories and not self._profile.name and not self._profile.preferences and not self._profile.facts:
                return ""
            lines = ["### 🧠 Gespeichertes Benutzerprofil & Präferenzen:"]
            if self._profile.name:
                lines.append(f"- **Benutzer:** {self._profile.name}")
            if self._profile.preferred_language:
                lines.append(f"- **Bevorzugte Sprache:** {self._profile.preferred_language}")
            for pref in self._profile.preferences:
                lines.append(f"- **[Präferenz]:** {pref}")
            for fact in self._profile.facts:
                lines.append(f"- **[Fakt]:** {fact}")
            for item in sorted(self._memories.values(), key=lambda x: (x.get("category", ""), x.get("key", ""))):
                k = item.get("key", "")
                v = item.get("value", "")
                cat = item.get("category", "general").capitalize()
                lines.append(f"- **[{cat}] {k}:** {v}")
            return "\n".join(lines)



# Singleton memory instance
_GLOBAL_MEMORY = UserMemoryStore()


def get_user_memory_store() -> UserMemoryStore:
    return _GLOBAL_MEMORY


def get_user_memory(key: Optional[str] = None) -> Dict[str, Any]:
    """Retrieves all or a specific user memory fact."""
    store = get_user_memory_store()
    if key:
        m = store.get_memory(key)
        return m if m is not None else {"error": f"Keine Erinnerung für '{key}' gefunden"}
    return store.get_all_memories()


def update_user_memory(key: str, value: str, category: str = "general") -> Dict[str, Any]:
    """Saves or updates a user fact or preference in persistent long-term memory."""
    store = get_user_memory_store()
    return store.update_memory(key=key, value=value, category=category)


def delete_user_memory(key: str) -> Dict[str, Any]:
    """Removes a user memory fact."""
    store = get_user_memory_store()
    return store.delete_memory(key=key)
