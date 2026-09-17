"""Authorized administrative API facade for the persistent Skill Registry."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from .audit import AuditLogger
from .contracts import SkillStatus
from .skill_registry import PersistentSkillRegistry


class RegistryAdminError(RuntimeError):
    pass


class SkillRegistryAdminAPI:
    """Small service API for register/search/status/backup/restore operations.

    Authentication is supplied by the host application. The facade requires an
    explicit ``authorized`` flag for mutations and never invents operator rights.
    """

    def __init__(self, registry: PersistentSkillRegistry, *, audit: AuditLogger | None = None) -> None:
        self.registry = registry
        self.audit = audit

    @staticmethod
    def _require(authorized: bool) -> None:
        if not authorized:
            raise PermissionError("registry administration requires explicit authorization")

    def search(self, query: str, *, limit: int = 20, include_inactive: bool = False) -> list[dict[str, Any]]:
        return [manifest.to_dict() for manifest in self.registry.search(query, limit=limit, include_inactive=include_inactive)]

    def get(self, skill_id: str, *, version: str | None = None, include_inactive: bool = True) -> dict[str, Any] | None:
        manifest = self.registry.get(skill_id, version=version, include_inactive=include_inactive)
        return manifest.to_dict() if manifest else None

    def register_file(self, path: str | Path, *, authorized: bool, replace_existing: bool = False) -> dict[str, Any]:
        self._require(authorized)
        manifest = self.registry.register_file(path, replace_existing=replace_existing)
        self._audit("registry_register", manifest.skill_id, {"version": manifest.version, "location": manifest.location})
        return manifest.to_dict()

    def discover(self, roots: Sequence[str | Path] | None = None, *, authorized: bool) -> dict[str, Any]:
        self._require(authorized)
        result = self.registry.discover(roots)
        self._audit("registry_discover", "registry", {"loaded": result.get("loaded", []), "broken_count": len(result.get("broken", []))})
        return result

    def set_status(self, skill_id: str, status: SkillStatus | str, *, authorized: bool, version: str | None = None) -> dict[str, Any]:
        self._require(authorized)
        status_obj = status if isinstance(status, SkillStatus) else SkillStatus(str(status).upper())
        changed = self.registry.set_status(skill_id, status_obj, version=version)
        if not changed:
            raise RegistryAdminError(f"skill not found: {skill_id}")
        self._audit("registry_status", skill_id, {"version": version, "status": status_obj.value, "changed": changed})
        return {"skill_id": skill_id, "version": version, "status": status_obj.value, "changed": changed}

    def deactivate(self, skill_id: str, *, authorized: bool, version: str | None = None) -> dict[str, Any]:
        return self.set_status(skill_id, SkillStatus.DISABLED, authorized=authorized, version=version)

    def backup(self, destination: str | Path, *, authorized: bool) -> dict[str, Any]:
        self._require(authorized)
        path = self.registry.backup(destination)
        self._audit("registry_backup", "registry", {"destination": str(path)})
        return {"status": "completed", "destination": str(path)}

    def restore(self, source: str | Path, *, authorized: bool) -> dict[str, Any]:
        self._require(authorized)
        source_path = Path(source)
        self.registry.restore(source_path)
        health = self.registry.health()
        if health.get("integrity") != "ok":
            raise RegistryAdminError("restored registry failed integrity check")
        self._audit("registry_restore", "registry", {"source": str(source_path), "health": health})
        return {"status": "completed", "source": str(source_path), "health": health}

    def health(self) -> dict[str, Any]:
        return self.registry.health()

    def _audit(self, action: str, subject: str, evidence: dict[str, Any]) -> None:
        if self.audit:
            self.audit.log(
                "registry_admin",
                decision="authorized_mutation",
                action=action,
                evidence={"subject": subject, **evidence},
            )
