#!/usr/bin/env python3
"""Fleet-aware launcher for the existing authenticated ComputeMesh provider agent.

This keeps provider_agent.py backwards compatible while making fleet identity and a
privacy-preserving hardware fingerprint the default for governed deployments.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

from apps.node import provider_agent
from services.identity.machine_identity import MachineIdentityError, attach_governance_identity


class GovernedProviderAgentError(RuntimeError):
    pass


def _extract_option(argv: list[str], name: str) -> tuple[str | None, list[str]]:
    result: list[str] = []
    value: str | None = None
    index = 0
    while index < len(argv):
        item = argv[index]
        if item == name:
            if index + 1 >= len(argv):
                raise GovernedProviderAgentError(f"{name} requires a value")
            value = argv[index + 1]
            index += 2
            continue
        if item.startswith(name + "="):
            value = item.split("=", 1)[1]
            index += 1
            continue
        result.append(item)
        index += 1
    return value, result


def _replace_profile(argv: list[str], profile_path: Path) -> list[str]:
    result = list(argv)
    for index, item in enumerate(result):
        if item == "--profile" and index + 1 < len(result):
            result[index + 1] = str(profile_path)
            return result
        if item.startswith("--profile="):
            result[index] = "--profile=" + str(profile_path)
            return result
    raise GovernedProviderAgentError("--profile is required")


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    fleet_arg, forwarded = _extract_option(raw_args, "--fleet-id")
    fleet_id = (fleet_arg or os.environ.get("COMPUTEMESH_FLEET_ID", "primary")).strip()

    profile_value: str | None = None
    for index, item in enumerate(forwarded):
        if item == "--profile" and index + 1 < len(forwarded):
            profile_value = forwarded[index + 1]
            break
        if item.startswith("--profile="):
            profile_value = item.split("=", 1)[1]
            break
    if not profile_value:
        raise GovernedProviderAgentError("--profile is required")
    source = Path(profile_value)
    if source.is_symlink() or not source.is_file():
        raise GovernedProviderAgentError("profile must be an existing non-symlink file")
    try:
        profile = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GovernedProviderAgentError("profile could not be loaded") from exc
    if not isinstance(profile, dict):
        raise GovernedProviderAgentError("profile root must be an object")
    try:
        governed = attach_governance_identity(profile, fleet_id=fleet_id)
    except MachineIdentityError as exc:
        raise GovernedProviderAgentError(str(exc)) from exc

    with tempfile.TemporaryDirectory(prefix="computemesh-governed-profile-") as directory:
        generated = Path(directory) / "node_profile.json"
        generated.write_text(
            json.dumps(governed, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        try:
            generated.chmod(0o600)
        except OSError:
            pass
        return provider_agent.main(_replace_profile(forwarded, generated))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GovernedProviderAgentError as exc:
        print(f"governed provider agent failed: {exc}")
        raise SystemExit(2) from exc
