"""Tests for tool-result normalization and egress/secret protection contracts."""
from __future__ import annotations

import unittest

from services.mcp.platform.tool_contracts import (
    EgressPolicy,
    SecretKind,
    SecretScanner,
    ToolEgressGuard,
    ToolResultStatus,
    normalize_tool_result,
)


class TestAgentsToolContracts(unittest.TestCase):
    def test_secret_scanner_returns_fingerprint_not_secret(self) -> None:
        secret = "Bearer AbCDef0123456789_token-value-XYZ"
        findings = SecretScanner().scan({"authorization": secret})
        self.assertTrue(findings)
        self.assertTrue(any(finding.kind in {SecretKind.API_KEY, SecretKind.BEARER_TOKEN} for finding in findings))
        self.assertNotIn(secret, repr(findings))

    def test_egress_guard_blocks_secret_by_default(self) -> None:
        result = ToolEgressGuard().check(
            {"token": "AbCdEfGhIjKlMnOpQrStUvWxYz012345"},
            EgressPolicy(),
        )
        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "secret_detected")
        self.assertNotIn("AbCdEfGhIjKlMnOpQrStUvWxYz012345", str(result))

    def test_egress_guard_enforces_field_allowlist_and_payload_bound(self) -> None:
        guard = ToolEgressGuard()
        denied = guard.check({"query": "ok", "extra": 1}, EgressPolicy(allowed_fields=("query",)))
        self.assertFalse(denied["allowed"])
        self.assertEqual(denied["reason"], "fields_not_allowlisted")
        too_large = guard.check({"query": "x" * 100}, EgressPolicy(max_payload_bytes=20))
        self.assertFalse(too_large["allowed"])
        self.assertEqual(too_large["reason"], "payload_too_large")

    def test_paginated_result_is_not_claimed_complete(self) -> None:
        envelope = normalize_tool_result(
            "search",
            {"results": [1, 2], "next_cursor": "cursor-2", "has_more": True},
        )
        self.assertEqual(envelope.status, ToolResultStatus.PARTIAL_SUCCESS)
        self.assertFalse(envelope.complete)
        self.assertEqual(envelope.pagination.next_cursor, "cursor-2")

    def test_error_with_data_is_partial_success(self) -> None:
        envelope = normalize_tool_result(
            "batch-read",
            {"items": [1, 2], "error": "2 of 4 items failed", "count": 2},
        )
        self.assertEqual(envelope.status, ToolResultStatus.PARTIAL_SUCCESS)
        self.assertFalse(envelope.complete)

    def test_resource_identity_and_provenance_are_preserved(self) -> None:
        envelope = normalize_tool_result(
            "file-read",
            {"id": "file-123", "uri": "file:///tmp/report", "version": "7", "data": "ok"},
            source="filesystem",
            version="1.2",
        )
        self.assertEqual(envelope.status, ToolResultStatus.SUCCESS)
        self.assertEqual(envelope.resources[0].resource_id, "file-123")
        self.assertEqual(envelope.resources[0].version, "7")
        self.assertEqual(envelope.provenance.tool_id, "file-read")
        self.assertEqual(envelope.provenance.source, "filesystem")


if __name__ == "__main__":
    unittest.main()
