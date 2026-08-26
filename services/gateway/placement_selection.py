"""Fail-closed adapter from M1 scheduler placement decisions to gateway dispatch.

The current M1 placement schema explicitly marks recommendations as non-production.
Consequently this adapter requires an explicit experimental opt-in before a
`shared_experiment` decision may drive orchestrator reservations.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


class PlacementSelectionError(ValueError):
    """Raised when a placement decision cannot safely drive shared dispatch."""


@dataclass(frozen=True)
class PlacementSelection:
    decision_id: str
    model_id: str
    artifact_digest: str
    provider_node_ids: tuple[str, ...]
    layer_ranges: tuple[tuple[str, int, int], ...]


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlacementSelectionError("placement decision could not be read") from exc
    if not isinstance(value, dict):
        raise PlacementSelectionError("placement decision root must be an object")
    return value


def load_shared_placement_selection(
    decision_path: str | Path,
    *,
    allow_experimental: bool = False,
) -> PlacementSelection:
    """Validate and extract exactly one feasible shared M1 placement.

    M1 placement decisions currently carry `production_scheduling=false` by schema.
    They can therefore drive this integration only with explicit experimental opt-in.
    """
    path = Path(decision_path)
    decision = _load_object(path)
    schema_path = Path(__file__).resolve().parents[1] / "scheduler" / "placement_decision.schema.json"
    schema = _load_object(schema_path)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(decision), key=lambda item: list(item.absolute_path))
    if errors:
        first = errors[0]
        where = ".".join(str(part) for part in first.absolute_path) or "$"
        raise PlacementSelectionError(f"placement decision invalid at {where}: {first.message}")

    recommendation = decision["recommendation"]
    if recommendation["production_scheduling"] is not False:
        raise PlacementSelectionError("unexpected placement production_scheduling contract")
    if not allow_experimental:
        raise PlacementSelectionError(
            "M1 shared placement is experimental; set explicit experimental opt-in"
        )
    if recommendation["mode"] != "shared_experiment":
        raise PlacementSelectionError("scheduler did not recommend a shared experiment")
    if not all(bool(item["passed"]) for item in decision["hard_constraints"]):
        raise PlacementSelectionError("placement hard constraints are not all satisfied")

    shared = [
        candidate
        for candidate in decision["candidates"]
        if candidate["mode"] == "shared_contiguous_layers"
    ]
    if len(shared) != 1 or not shared[0]["feasible"]:
        raise PlacementSelectionError("no unique feasible shared placement candidate")

    ranges = shared[0]["layer_ranges"]
    if len(ranges) < 2:
        raise PlacementSelectionError("shared placement must contain at least two layer ranges")
    nodes = tuple(str(item["node_id"]) for item in ranges)
    if len(set(nodes)) != len(nodes):
        raise PlacementSelectionError("shared placement node ids must be unique")

    expected_nodes = {
        str(decision["nodes"]["coordinator"]["node_id"]),
        str(decision["nodes"]["worker"]["node_id"]),
    }
    if set(nodes) != expected_nodes:
        raise PlacementSelectionError("shared layer ranges do not match decision nodes")

    layer_ranges = tuple(
        (
            str(item["node_id"]),
            int(item["start_layer"]),
            int(item["end_layer_exclusive"]),
        )
        for item in ranges
    )
    ordered = sorted(layer_ranges, key=lambda item: item[1])
    if ordered[0][1] != 0:
        raise PlacementSelectionError("shared layer ranges must begin at layer zero")
    for previous, current in zip(ordered, ordered[1:]):
        if previous[2] != current[1]:
            raise PlacementSelectionError("shared layer ranges must be contiguous")
    if ordered[-1][2] != int(decision["model"]["layer_count"]):
        raise PlacementSelectionError("shared layer ranges do not cover the model")

    return PlacementSelection(
        decision_id=str(decision["decision_id"]),
        model_id=str(decision["model"]["model_id"]),
        artifact_digest=str(decision["model"]["artifact_digest"]),
        provider_node_ids=nodes,
        layer_ranges=layer_ranges,
    )
