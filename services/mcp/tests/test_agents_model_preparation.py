# SPDX-License-Identifier: Apache-2.0
"""Tests for authorization-gated model preparation planning."""

from __future__ import annotations

import unittest

from services.mcp.platform.model_preparation import (
    ModelArtifactSpec,
    ModelPreparationCoordinator,
    ModelPreparationError,
)
from services.mcp.platform.node_registry import NodeRegistry

_DIGEST = "a" * 64


class TestModelPreparationCoordinator(unittest.TestCase):
    def _ready_for_preparation(self, *, models=()):
        registry = NodeRegistry()
        node = registry.discover("node-prep", "https://192.168.1.20:8080")
        registry.mark_reachable(node.node_id)
        registry.record_capabilities(node.node_id, capabilities=("inference",), models=models, profile_revision=1)
        registry.verify_identity(node.node_id, identity_key_id="key_1", evidence_digest="b" * 64)
        registry.mark_authenticated(node.node_id, principal_id="provider_1")
        return registry, node.node_id

    def test_unverified_node_requires_manual_authentication(self):
        registry = NodeRegistry()
        try:
            node = registry.discover("node-new", "https://192.168.1.20:8080")
            model = ModelArtifactSpec("qwen2.5:3b", _DIGEST, 100)
            plan = ModelPreparationCoordinator(registry).plan(node.node_id, model)
            self.assertEqual(plan.status, "manual_action_required")
            self.assertEqual(plan.reason_code, "authentication_required")
        finally:
            registry.close()

    def test_missing_model_requires_confirmation_and_uses_stable_key(self):
        registry, node_id = self._ready_for_preparation()
        try:
            calls = []
            coordinator = ModelPreparationCoordinator(registry, lambda node, request: calls.append((node, request)) or {
                "status": "prepared", "model_id": "qwen2.5:3b", "artifact_digest": _DIGEST,
            })
            model = ModelArtifactSpec("qwen2.5:3b", _DIGEST, 100)
            first = coordinator.prepare(node_id, model)
            second = coordinator.prepare(node_id, model)
            self.assertEqual(first.plan.reason_code, "installation_confirmation_required")
            self.assertEqual(first.plan.idempotency_key, second.plan.idempotency_key)
            self.assertEqual(calls, [])
            prepared = coordinator.prepare(node_id, model, authorized=True)
            self.assertEqual(prepared.plan.status, "prepared")
            self.assertEqual(calls[0][1]["idempotency_key"], first.plan.idempotency_key)
        finally:
            registry.close()

    def test_advertised_digest_is_available_without_install(self):
        registry, node_id = self._ready_for_preparation(models=({"id": "qwen2.5:3b", "artifact_digest": f"sha256:{_DIGEST}"},))
        try:
            model = ModelArtifactSpec("qwen2.5:3b", _DIGEST, 100)
            result = ModelPreparationCoordinator(registry).prepare(node_id, model, authorized=True)
            self.assertEqual(result.plan.status, "available")
            self.assertEqual(result.plan.reason_code, "model_already_advertised")
        finally:
            registry.close()

    def test_transport_digest_mismatch_is_rejected(self):
        registry, node_id = self._ready_for_preparation()
        try:
            coordinator = ModelPreparationCoordinator(
                registry,
                lambda _node, _request: {"status": "prepared", "model_id": "qwen2.5:3b", "artifact_digest": "c" * 64},
            )
            with self.assertRaises(ModelPreparationError):
                coordinator.prepare(node_id, ModelArtifactSpec("qwen2.5:3b", _DIGEST, 100), authorized=True)
        finally:
            registry.close()


if __name__ == "__main__":
    unittest.main()
