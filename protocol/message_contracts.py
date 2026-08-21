from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker


class MessageContractError(ValueError):
    pass


_EMPTY_MESSAGES = {
    "ActivateReservation",
    "ReleaseReservation",
    "RejectReservation",
    "ValidateJob",
    "PlanJob",
    "ReserveJob",
    "PrepareJob",
    "StartJob",
    "VerifyJob",
    "CompleteJob",
    "SettleJob",
    "FailJob",
    "RefundJob",
}

_SCHEMA_BY_MESSAGE = {
    **{name: "empty_payload.schema.json" for name in _EMPTY_MESSAGES},
    "ReserveCapacity": "reserve_capacity_payload.schema.json",
    "CommitReservation": "commit_reservation_payload.schema.json",
    "CancelJob": "cancel_job_payload.schema.json",
}


class MessageContractValidator:
    """Validate message payloads independently of the chosen transport."""

    def __init__(self, schema_dir: str | Path | None = None):
        self.schema_dir = (
            Path(schema_dir)
            if schema_dir is not None
            else Path(__file__).resolve().parent / "schemas"
        )
        self._validators: dict[str, Draft202012Validator] = {}

    def supported_messages(self) -> frozenset[str]:
        return frozenset(_SCHEMA_BY_MESSAGE)

    def validate(self, message_type: str, payload: Mapping[str, Any]) -> None:
        filename = _SCHEMA_BY_MESSAGE.get(message_type)
        if filename is None:
            raise KeyError(message_type)

        validator = self._validators.get(filename)
        if validator is None:
            with (self.schema_dir / filename).open("r", encoding="utf-8") as handle:
                schema = json.load(handle)
            Draft202012Validator.check_schema(schema)
            validator = Draft202012Validator(schema, format_checker=FormatChecker())
            self._validators[filename] = validator

        errors = sorted(
            validator.iter_errors(payload),
            key=lambda error: list(error.absolute_path),
        )
        if not errors:
            return

        parts: list[str] = []
        for error in errors:
            path = ".".join(str(item) for item in error.absolute_path) or "$"
            parts.append(f"{path}: {error.message}")
        raise MessageContractError("; ".join(parts))
