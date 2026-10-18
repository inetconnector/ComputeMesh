"""Versioned capability evaluation corpus and fail-closed evidence summaries.

A blank results file is not a passing baseline. Only externally executed
tasks with retained evidence and explicit review can receive pass/fail status.
No prompts, secrets, user content or private traces are stored in reports.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SUITE_PATH = HERE / "ai_capability_tasks_v1.json"
CATEGORIES = frozenset({
    "research", "multi_tool", "file_analysis", "code_change", "session_restart",
    "vision", "speech", "android_reconnect", "prompt_injection", "role_switch",
    "budget_exhaustion",
})
TIERS = frozenset({"basic", "intermediate", "advanced"})
LOCALES = frozenset({"de", "en"})
STATUSES = frozenset({"passed", "failed", "not_measured"})


def read_suite(path: Path = SUITE_PATH) -> dict[str, Any]:
    suite = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(suite, dict) or suite.get("schema_version") != 1:
        raise ValueError("unsupported suite schema_version")
    tasks = suite.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("suite requires non-empty tasks")
    ids: set[str] = set()
    categories: set[str] = set()
    tiers: set[str] = set()
    locales: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("task must be a mapping")
        identifier = task.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in ids:
            raise ValueError("invalid or duplicate task id")
        ids.add(identifier)
        category = task.get("category")
        tier = task.get("tier")
        locale = task.get("locale")
        if category not in CATEGORIES or tier not in TIERS or locale not in LOCALES:
            raise ValueError(f"invalid task classification: {identifier}")
        categories.add(category)
        tiers.add(tier)
        locales.add(locale)
        for key in ("prompt", "success_criteria"):
            value = task.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{identifier} lacks {key}")
        if task.get("environment") not in {"software", "physical_android", "live_model"}:
            raise ValueError(f"invalid environment for {identifier}")
    if categories != CATEGORIES or tiers != TIERS or locales != LOCALES:
        raise ValueError("suite lacks required coverage")
    return suite


def read_observations(path: Path | None, suite: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Only one observation per task; reject fabricated success without evidence."""
    if path is None:
        return {}
    allowed = {task["id"] for task in suite["tasks"]}
    observations: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        observation = json.loads(line)
        if not isinstance(observation, dict):
            raise ValueError(f"line {line_number}: observation must be object")
        task_id = observation.get("task_id")
        status = observation.get("status")
        if task_id not in allowed or task_id in observations or status not in STATUSES:
            raise ValueError(f"line {line_number}: invalid/duplicate task or status")
        if status != "not_measured":
            for key in ("model_id", "config_id", "evidence_ref", "review_rationale"):
                if not isinstance(observation.get(key), str) or not observation[key].strip():
                    raise ValueError(f"line {line_number}: missing {key}")
            if not isinstance(observation.get("latency_ms"), (int, float)):
                raise ValueError(f"line {line_number}: missing numeric latency_ms")
            if observation["latency_ms"] < 0:
                raise ValueError(f"line {line_number}: negative latency_ms")
        observations[task_id] = observation
    return observations


def summarize(
    suite: dict[str, Any],
    observations: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    cases = suite["tasks"]
    by_status = Counter(observations.get(task["id"], {}).get("status", "not_measured") for task in cases)
    by_category: dict[str, dict[str, int]] = {}
    for category in sorted(CATEGORIES):
        selected = [task for task in cases if task["category"] == category]
        by_category[category] = dict(
            Counter(observations.get(task["id"], {}).get("status", "not_measured")
                    for task in selected)
        )
    measured = [record for record in observations.values() if record.get("status") != "not_measured"]
    return {
        "suite_id": suite["suite_id"],
        "schema_version": 1,
        "task_count": len(cases),
        "passed": by_status["passed"],
        "failed": by_status["failed"],
        "not_measured": by_status["not_measured"],
        "by_category": by_category,
        "release_gate": "BLOCKED" if by_status["not_measured"] or by_status["failed"] else "REQUIRES_SECURITY_AND_DEVICE_GATES",
        "numeric_slos": None,
        "note": "Evaluation outcomes are only from supplied evidence. No live/model/phone result is inferred.",
        "measured_model_ids": sorted({row["model_id"] for row in measured}),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=SUITE_PATH)
    parser.add_argument("--observations", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args(argv)
    suite = read_suite(args.suite)
    observations = read_observations(args.observations, suite)
    report = summarize(suite, observations)
    payload = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    if args.require_complete and report["release_gate"] == "BLOCKED":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
