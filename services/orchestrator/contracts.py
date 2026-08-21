from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

try:
    from .persistence import SQLiteStateStore, StateRecord
    from .state_machine import JobState, ReservationState
except ImportError:  # direct-file execution/tests
    from persistence import SQLiteStateStore, StateRecord
    from state_machine import JobState, ReservationState


class ContractValidationError(ValueError):
    pass


class ContractValidator:
    """Load and validate the versioned M0 JSON Schema contracts."""

    _FILES = {
        "node_profile": "node_profile.schema.json",
        "benchmark_result": "benchmark_result.schema.json",
        "model_manifest": "model_manifest.schema.json",
        "shard_manifest": "shard_manifest.schema.json",
        "reservation": "reservation.schema.json",
        "job": "job.schema.json",
    }

    def __init__(self, schema_dir: str | Path | None = None):
        if schema_dir is None:
            schema_dir = Path(__file__).resolve().parents[2] / "protocol" / "schemas"
        self.schema_dir = Path(schema_dir)
        self._validators: dict[str, Draft202012Validator] = {}

    def _validator(self, contract: str) -> Draft202012Validator:
        if contract not in self._FILES:
            raise KeyError(f"unknown contract {contract!r}")
        validator = self._validators.get(contract)
        if validator is None:
            path = self.schema_dir / self._FILES[contract]
            with path.open("r", encoding="utf-8") as handle:
                schema = json.load(handle)
            Draft202012Validator.check_schema(schema)
            validator = Draft202012Validator(schema, format_checker=FormatChecker())
            self._validators[contract] = validator
        return validator

    def validate(self, contract: str, document: Mapping[str, Any]) -> None:
        errors = sorted(self._validator(contract).iter_errors(document), key=lambda e: list(e.absolute_path))
        if not errors:
            return
        parts: list[str] = []
        for error in errors:
            path = ".".join(str(item) for item in error.absolute_path) or "$"
            parts.append(f"{path}: {error.message}")
        raise ContractValidationError("; ".join(parts))


class ContractAdmission:
    """Validate initial control-plane documents before creating durable state."""

    def __init__(self, store: SQLiteStateStore, validator: ContractValidator):
        self.store = store
        self.validator = validator

    def admit_job(self, document: Mapping[str, Any]) -> StateRecord:
        self.validator.validate("job", document)
        if document["state"] != JobState.CREATED.value or document["revision"] != 0:
            raise ContractValidationError("job admission requires state=CREATED and revision=0")
        record = self.store.ensure_job(str(document["job_id"]))
        if record.state != JobState.CREATED or record.revision != 0:
            raise ContractValidationError("job_id already exists with non-initial durable state")
        return record

    def admit_reservation(self, document: Mapping[str, Any]) -> StateRecord:
        self.validator.validate("reservation", document)
        if document["state"] != ReservationState.CANDIDATE.value or document["revision"] != 0:
            raise ContractValidationError("reservation admission requires state=CANDIDATE and revision=0")
        record = self.store.ensure_reservation(str(document["reservation_id"]))
        if record.state != ReservationState.CANDIDATE or record.revision != 0:
            raise ContractValidationError("reservation_id already exists with non-initial durable state")
        return record
