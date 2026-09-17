"""Persistent, fail-closed skill registry for ComputeMesh Agents Platform."""
from __future__ import annotations

from dataclasses import replace
import ast
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Callable, Iterable, Sequence

from .contracts import RiskLevel, SideEffectLevel, SkillManifest, SkillStatus

MAX_SKILL_BYTES = 512 * 1024


def _now() -> float:
    return time.time()


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text.replace("'", '"'))
                return _as_tuple(parsed)
            except Exception:
                try:
                    return _as_tuple(ast.literal_eval(text))
                except Exception:
                    return tuple(part.strip().strip("'\"") for part in text[1:-1].split(",") if part.strip())
        return (text,) if text else ()
    return (str(value),)


def _parse_scalar(value: str) -> Any:
    text = value.strip()
    if not text:
        return ""
    lower = text.casefold()
    if lower in {"true", "false"}:
        return lower == "true"
    if lower in {"null", "none", "~"}:
        return None
    if text.startswith("[") and text.endswith("]"):
        try:
            return json.loads(text.replace("'", '"'))
        except Exception:
            try:
                return ast.literal_eval(text)
            except Exception:
                return [part.strip().strip("'\"") for part in text[1:-1].split(",") if part.strip()]
    if text.startswith("{") and text.endswith("}"):
        try:
            return json.loads(text.replace("'", '"'))
        except Exception:
            try:
                return ast.literal_eval(text)
            except Exception:
                return text
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text.strip("'\"")


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        raise ValueError("SKILL.md frontmatter is required")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("frontmatter must start at first line")
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        raise ValueError("frontmatter terminator missing")
    metadata: dict[str, Any] = {}
    pending_list_key: str | None = None
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith((" ", "\t")):
            stripped = raw.strip()
            if pending_list_key and stripped.startswith("-"):
                metadata.setdefault(pending_list_key, []).append(_parse_scalar(stripped[1:].strip()))
                continue
            raise ValueError("nested frontmatter is not supported in SKILL.md; use a manifest sidecar")
        if ":" not in raw:
            raise ValueError(f"invalid frontmatter line: {raw[:80]}")
        key, raw_value = raw.split(":", 1)
        key = key.strip()
        if not key:
            raise ValueError("empty frontmatter key")
        if key in metadata:
            raise ValueError(f"duplicate frontmatter key: {key}")
        raw_value = raw_value.strip()
        if raw_value == "":
            metadata[key] = []
            pending_list_key = key
        else:
            metadata[key] = _parse_scalar(raw_value)
            pending_list_key = None
    return metadata, "\n".join(lines[end + 1 :]).lstrip("\n")


def _extract_section(body: str, headings: Sequence[str]) -> str:
    wanted = {h.casefold() for h in headings}
    lines = body.splitlines()
    start: int | None = None
    level = 0
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            hashes = len(stripped) - len(stripped.lstrip("#"))
            title = stripped[hashes:].strip().casefold()
            if start is None and title in wanted:
                start = idx + 1
                level = hashes
                continue
            if start is not None and hashes <= level:
                return "\n".join(lines[start:idx]).strip()
    return "\n".join(lines[start:]).strip() if start is not None else ""


class PersistentSkillRegistry:
    """SQLite-backed skill registry with content-integrity and lifecycle checks."""

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        *,
        allowed_roots: Sequence[str | Path] = (),
        available_tools: Iterable[str] | None = None,
        max_skill_bytes: int = MAX_SKILL_BYTES,
        signature_verifier: Callable[[bytes, str], bool] | None = None,
    ) -> None:
        self.db_path = str(db_path)
        self.allowed_roots = tuple(Path(root).resolve() for root in allowed_roots)
        self.available_tools = set(str(x) for x in available_tools) if available_tools is not None else None
        self.max_skill_bytes = max(1, int(max_skill_bytes))
        self.signature_verifier = signature_verifier
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS skills (
                    skill_id TEXT NOT NULL, version TEXT NOT NULL, name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, priority INTEGER NOT NULL,
                    location TEXT NOT NULL DEFAULT '', checksum TEXT NOT NULL, signature TEXT,
                    manifest_json TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', validation_error TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    PRIMARY KEY (skill_id, version)
                );
                CREATE INDEX IF NOT EXISTS idx_skills_status ON skills(status);
                CREATE INDEX IF NOT EXISTS idx_skills_id ON skills(skill_id);
                CREATE TABLE IF NOT EXISTS registry_meta (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at REAL NOT NULL
                );
                """
            )
            self._set_meta("schema_version", "1.0")

    def _set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO registry_meta(key,value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
            (key, value, _now()),
        )

    def _ensure_allowed(self, path: Path) -> Path:
        resolved = path.resolve(strict=True)
        if self.allowed_roots and not any(resolved == root or root in resolved.parents for root in self.allowed_roots):
            raise ValueError(f"skill path outside allowed roots: {resolved}")
        return resolved

    def _manifest_from_metadata(self, metadata: dict[str, Any], *, checksum: str, location: str) -> SkillManifest:
        status_raw = str(metadata.get("status", "ACTIVE")).upper()
        if status_raw == "QUARANTINED":
            status_raw = "BROKEN"
        try:
            status = SkillStatus(status_raw)
        except ValueError as exc:
            raise ValueError(f"invalid status: {status_raw}") from exc
        risk_raw = str(metadata.get("risk_level", "LOW")).upper()
        side_raw = str(metadata.get("side_effect_level", metadata.get("side_effect", "NONE"))).upper()
        if side_raw == "WRITE":
            side_raw = "WRITE_REVERSIBLE"
        raw_priority = metadata.get("priority", 50)
        priority = {"critical": 100, "high": 80, "normal": 50, "low": 20}.get(
            str(raw_priority).casefold(), int(raw_priority) if str(raw_priority).strip().isdigit() else 50
        )
        deps = tuple(
            dep for dep in _as_tuple(metadata.get("dependencies"))
            if dep and " " not in dep and dep[0].isalpha()
        )
        manifest = SkillManifest(
            skill_id=str(metadata.get("skill_id") or metadata.get("id") or "").strip(),
            name=str(metadata.get("name") or "").strip(),
            version=str(metadata.get("version") or "").strip(),
            description=str(metadata.get("description") or "").strip(),
            status=status,
            priority=priority,
            domains=_as_tuple(metadata.get("domains")),
            intents=_as_tuple(metadata.get("intents") or metadata.get("semantic_intents")),
            triggers=_as_tuple(metadata.get("triggers")),
            negative_triggers=_as_tuple(metadata.get("negative_triggers") or metadata.get("exclusions")),
            examples=_as_tuple(metadata.get("examples") or metadata.get("positive_examples")),
            anti_examples=_as_tuple(metadata.get("anti_examples") or metadata.get("negative_examples")),
            required_inputs=_as_tuple(metadata.get("required_inputs")),
            optional_inputs=_as_tuple(metadata.get("optional_inputs")),
            input_schema=metadata.get("input_schema") if isinstance(metadata.get("input_schema"), dict) else {},
            output_schema=metadata.get("output_schema") if isinstance(metadata.get("output_schema"), dict) else {},
            required_tools=_as_tuple(metadata.get("required_tools")),
            optional_tools=_as_tuple(metadata.get("optional_tools")),
            forbidden_tools=_as_tuple(metadata.get("forbidden_tools")),
            dependencies=deps,
            conflicts_with=_as_tuple(metadata.get("conflicts_with") or metadata.get("conflicts")),
            fallback_skills=_as_tuple(metadata.get("fallback_skills")),
            side_effect_level=SideEffectLevel(side_raw),
            risk_level=RiskLevel(risk_raw),
            estimated_context_tokens=int(metadata.get("estimated_context_tokens", 0) or 0),
            estimated_latency_ms=int(metadata.get("estimated_latency_ms", 0) or 0),
            estimated_cost_class=str(metadata.get("estimated_cost") or metadata.get("estimated_cost_class") or "unknown"),
            validation_rules=_as_tuple(metadata.get("validation_rules") or metadata.get("validation_methods")),
            checksum=checksum,
            signature=None if metadata.get("signature") in (None, "") else str(metadata.get("signature")),
            location=location,
            source=str(metadata.get("source") or metadata.get("author/source") or "local"),
            summary=str(metadata.get("summary") or metadata.get("description") or ""),
        )
        errors = manifest.validate()
        if errors:
            raise ValueError("; ".join(errors))
        return manifest

    def register_manifest(self, manifest: SkillManifest, *, body: str = "", replace_existing: bool = False) -> SkillManifest:
        errors = manifest.validate()
        if errors:
            raise ValueError("; ".join(errors))
        if manifest.status in {SkillStatus.ACTIVE, SkillStatus.EXPERIMENTAL} and self.available_tools is not None:
            missing_tools = sorted(set(manifest.required_tools) - self.available_tools)
            if missing_tools:
                raise ValueError(f"missing required tools: {', '.join(missing_tools)}")
        payload = json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        checksum = manifest.checksum or hashlib.sha256((payload + "\n" + body).encode("utf-8")).hexdigest()
        if manifest.checksum != checksum:
            manifest = replace(manifest, checksum=checksum)
            payload = json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self._lock, self._conn:
            existing = self._conn.execute(
                "SELECT checksum FROM skills WHERE skill_id=? AND version=?", (manifest.skill_id, manifest.version)
            ).fetchone()
            if existing and not replace_existing:
                if existing["checksum"] != manifest.checksum:
                    raise ValueError("duplicate skill id/version has a different checksum")
                return self.get(manifest.skill_id, version=manifest.version) or manifest
            now = _now()
            self._conn.execute(
                """
                INSERT INTO skills(skill_id,version,name,description,status,priority,location,checksum,signature,
                                   manifest_json,body,validation_error,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(skill_id,version) DO UPDATE SET
                    name=excluded.name,description=excluded.description,status=excluded.status,
                    priority=excluded.priority,location=excluded.location,checksum=excluded.checksum,
                    signature=excluded.signature,manifest_json=excluded.manifest_json,body=excluded.body,
                    validation_error=excluded.validation_error,updated_at=excluded.updated_at
                """,
                (manifest.skill_id, manifest.version, manifest.name, manifest.description, manifest.status.value,
                 manifest.priority, manifest.location, manifest.checksum, manifest.signature, payload, body, "", now, now),
            )
            self._set_meta("last_write", str(now))
        return manifest

    def _record_broken(self, path: str, error: str, *, skill_id: str = "") -> None:
        digest = hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]
        broken_id = skill_id if skill_id and skill_id.isascii() else f"broken.{digest}"
        if not broken_id or not broken_id[0].isalpha():
            broken_id = f"broken.{digest}"
        manifest = SkillManifest(
            skill_id=broken_id.lower().replace("_", "-"), name=f"Broken skill: {Path(path).name}",
            version=f"broken-{digest}", description=error[:500], status=SkillStatus.BROKEN,
            location=path, checksum=digest,
        )
        try:
            self.register_manifest(manifest, body="", replace_existing=True)
            with self._lock, self._conn:
                self._conn.execute(
                    "UPDATE skills SET validation_error=? WHERE skill_id=? AND version=?",
                    (error[:4000], manifest.skill_id, manifest.version),
                )
        except Exception:
            pass

    def register_file(self, path: str | Path, *, replace_existing: bool = False) -> SkillManifest:
        raw_path = Path(path)
        try:
            resolved = self._ensure_allowed(raw_path)
            if resolved.name != "SKILL.md":
                raise ValueError("only SKILL.md files may be registered")
            if resolved.stat().st_size > self.max_skill_bytes:
                raise ValueError(f"skill file exceeds maximum size {self.max_skill_bytes}")
            raw = resolved.read_bytes()
            if b"\x00" in raw:
                raise ValueError("NUL byte not allowed")
            try:
                text = raw.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise ValueError("SKILL.md must be valid UTF-8") from exc
            checksum = hashlib.sha256(raw).hexdigest()
            metadata, body = parse_frontmatter(text)
            signature = metadata.get("signature")
            if signature:
                if self.signature_verifier is None:
                    raise ValueError("signed skill cannot be verified: no signature verifier configured")
                if not self.signature_verifier(raw, str(signature)):
                    raise ValueError("skill signature verification failed")
            manifest = self._manifest_from_metadata(metadata, checksum=checksum, location=str(resolved))
            return self.register_manifest(manifest, body=body, replace_existing=replace_existing)
        except Exception as exc:
            self._record_broken(str(raw_path), str(exc))
            raise

    def discover(self, roots: Sequence[str | Path] | None = None) -> dict[str, Any]:
        selected_roots = tuple(Path(r).resolve() for r in (roots or self.allowed_roots))
        if not selected_roots:
            raise ValueError("at least one skill root is required")
        loaded: list[str] = []
        broken: list[dict[str, str]] = []
        for root in selected_roots:
            if self.allowed_roots and not any(root == allowed or allowed in root.parents for allowed in self.allowed_roots):
                broken.append({"path": str(root), "error": "root outside allowed roots"})
                continue
            if not root.exists():
                continue
            for document in sorted(root.rglob("SKILL.md")):
                try:
                    manifest = self.register_file(document)
                    loaded.append(f"{manifest.skill_id}@{manifest.version}")
                except Exception as exc:
                    broken.append({"path": str(document), "error": str(exc)})
        return {"loaded": loaded, "broken": broken, "dependency_errors": self.validate_graph()}

    def _row_to_manifest(self, row: sqlite3.Row) -> SkillManifest:
        data = json.loads(row["manifest_json"])
        data["status"] = SkillStatus(str(row["status"]))
        data["risk_level"] = RiskLevel(str(data.get("risk_level", "LOW")))
        data["side_effect_level"] = SideEffectLevel(str(data.get("side_effect_level", "NONE")))
        for field_name in {
            "domains", "intents", "triggers", "negative_triggers", "examples", "anti_examples",
            "required_inputs", "optional_inputs", "required_tools", "optional_tools", "forbidden_tools",
            "dependencies", "conflicts_with", "fallback_skills", "validation_rules",
        }:
            data[field_name] = tuple(data.get(field_name) or ())
        return SkillManifest(**data)

    @staticmethod
    def _version_key(version: str) -> tuple[Any, ...]:
        return tuple(int(part) if part.isdigit() else part.casefold() for part in version.replace("-", ".").split("."))

    def get(self, skill_id: str, *, version: str | None = None, include_inactive: bool = True) -> SkillManifest | None:
        with self._lock:
            if version:
                row = self._conn.execute(
                    "SELECT * FROM skills WHERE skill_id=? AND version=?", (skill_id, version)
                ).fetchone()
                if not row:
                    return None
                manifest = self._row_to_manifest(row)
                if not include_inactive and manifest.status not in {SkillStatus.ACTIVE, SkillStatus.EXPERIMENTAL}:
                    return None
                return manifest
            rows = self._conn.execute("SELECT * FROM skills WHERE skill_id=?", (skill_id,)).fetchall()
        manifests = [self._row_to_manifest(row) for row in rows]
        if not include_inactive:
            manifests = [m for m in manifests if m.status in {SkillStatus.ACTIVE, SkillStatus.EXPERIMENTAL}]
        return sorted(manifests, key=lambda m: self._version_key(m.version), reverse=True)[0] if manifests else None

    def list(self, *, statuses: Sequence[SkillStatus | str] | None = None) -> list[SkillManifest]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM skills").fetchall()
        manifests = [self._row_to_manifest(row) for row in rows]
        if statuses:
            allowed = {s.value if isinstance(s, SkillStatus) else str(s).upper() for s in statuses}
            manifests = [m for m in manifests if m.status.value in allowed]
        return sorted(manifests, key=lambda m: (m.skill_id, self._version_key(m.version)))

    def active(self) -> list[SkillManifest]:
        latest: dict[str, SkillManifest] = {}
        for manifest in self.list(statuses=(SkillStatus.ACTIVE, SkillStatus.EXPERIMENTAL)):
            current = latest.get(manifest.skill_id)
            if current is None or self._version_key(manifest.version) > self._version_key(current.version):
                latest[manifest.skill_id] = manifest
        return sorted(latest.values(), key=lambda m: (-m.priority, m.skill_id))

    def set_status(self, skill_id: str, status: SkillStatus | str, *, version: str | None = None) -> int:
        status_obj = status if isinstance(status, SkillStatus) else SkillStatus(str(status).upper())
        with self._lock, self._conn:
            if version:
                cursor = self._conn.execute(
                    "UPDATE skills SET status=?,updated_at=? WHERE skill_id=? AND version=?",
                    (status_obj.value, _now(), skill_id, version),
                )
            else:
                cursor = self._conn.execute(
                    "UPDATE skills SET status=?,updated_at=? WHERE skill_id=?", (status_obj.value, _now(), skill_id),
                )
            return cursor.rowcount

    def search(self, query: str, *, limit: int = 20, include_inactive: bool = False) -> list[SkillManifest]:
        tokens = {token for token in str(query).casefold().replace("_", " ").replace("-", " ").split() if token}
        pool = self.list() if include_inactive else self.active()
        scored: list[tuple[float, SkillManifest]] = []
        for skill in pool:
            haystack = " ".join((skill.skill_id, skill.name, skill.description, *skill.domains, *skill.intents, *skill.triggers)).casefold()
            score = sum(1.0 for token in tokens if token in haystack)
            if score or not tokens:
                scored.append((score + skill.priority / 1000.0, skill))
        scored.sort(key=lambda item: (-item[0], item[1].skill_id))
        return [skill for _, skill in scored[: max(1, int(limit))]]

    def validate_graph(self) -> list[dict[str, Any]]:
        active = {skill.skill_id: skill for skill in self.active()}
        errors: list[dict[str, Any]] = []
        for skill in active.values():
            missing = [dep for dep in skill.dependencies if dep not in active]
            conflicts = [other for other in skill.conflicts_with if other in active]
            missing_tools = sorted(set(skill.required_tools) - self.available_tools) if self.available_tools is not None else []
            if missing or missing_tools:
                errors.append({"skill_id": skill.skill_id, "missing_dependencies": missing, "missing_tools": missing_tools})
                self.set_status(skill.skill_id, SkillStatus.BROKEN, version=skill.version)
            if conflicts:
                errors.append({"skill_id": skill.skill_id, "active_conflicts": conflicts})
        active = {skill.skill_id: skill for skill in self.active()}
        visiting: set[str] = set()
        visited: set[str] = set()
        stack: list[str] = []

        def visit(skill_id: str) -> None:
            if skill_id in visited:
                return
            if skill_id in visiting:
                try:
                    idx = stack.index(skill_id)
                    cycle = stack[idx:] + [skill_id]
                except ValueError:
                    cycle = [skill_id]
                errors.append({"skill_id": skill_id, "dependency_cycle": cycle})
                return
            visiting.add(skill_id)
            stack.append(skill_id)
            for dep in active[skill_id].dependencies:
                if dep in active:
                    visit(dep)
            stack.pop()
            visiting.remove(skill_id)
            visited.add(skill_id)

        for sid in sorted(active):
            visit(sid)
        return errors

    def load_content(self, skill_id: str, *, version: str | None = None, level: str = "metadata") -> dict[str, Any] | str | None:
        manifest = self.get(skill_id, version=version, include_inactive=True)
        if manifest is None:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT body FROM skills WHERE skill_id=? AND version=?", (manifest.skill_id, manifest.version)
            ).fetchone()
        body = str(row["body"] if row else "")
        level_normalized = level.casefold()
        if level_normalized == "metadata":
            return manifest.to_dict()
        if level_normalized == "summary":
            return manifest.summary or manifest.description
        if level_normalized == "workflow":
            return _extract_section(body, ("workflow", "execution contract", "task graph"))
        if level_normalized in {"rules", "relevant_rules"}:
            chunks = [
                _extract_section(body, ("decision rules",)),
                _extract_section(body, ("validation", "validation and recovery")),
                _extract_section(body, ("security", "safety and provenance")),
            ]
            return "\n\n".join(chunk for chunk in chunks if chunk)
        if level_normalized == "full":
            return body
        raise ValueError(f"unknown loading level: {level}")

    def backup(self, destination: str | Path) -> Path:
        dest = Path(destination)
        dest.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(dest)
        try:
            with self._lock:
                self._conn.backup(target)
        finally:
            target.close()
        return dest

    def restore(self, source: str | Path) -> None:
        src = Path(source)
        if not src.exists():
            raise FileNotFoundError(src)
        source_conn = sqlite3.connect(src)
        try:
            with self._lock:
                source_conn.backup(self._conn)
                self._conn.commit()
        finally:
            source_conn.close()

    def health(self) -> dict[str, Any]:
        with self._lock:
            integrity = self._conn.execute("PRAGMA integrity_check").fetchone()[0]
            counts = {row["status"]: row["count"] for row in self._conn.execute("SELECT status,COUNT(*) AS count FROM skills GROUP BY status")}
        return {"integrity": integrity, "counts": counts, "graph_errors": self.validate_graph()}
