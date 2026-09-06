"""Tests for the public gateway's canonical model registry integration."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.gateway.registry_client import ModelRegistryClient, RegistryClientError


class _Response:
    def __init__(self, value: dict) -> None:
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.value).encode()


class TestRegistryClient(unittest.TestCase):
    def test_validates_and_caches_public_registry_response(self) -> None:
        payload = {
            "object": "list",
            "data": [{
                "id": "qwen/test",
                "display_name": "Test",
                "context_length": 8192,
                "capabilities": ["chat"],
                "availability": "available_warm",
                "license": "Apache-2.0",
                "artifact": {"digest": "sha256:" + "a" * 64, "size_bytes": 123, "quantization": "Q4_K_M"},
            }],
        }
        with patch("services.gateway.registry_client.urlopen", return_value=_Response(payload)) as fetch:
            client = ModelRegistryClient("https://control-plane/v1/registry/models", cache_ttl_seconds=60)
            first = client.models()
            second = client.models()
        self.assertEqual(first, second)
        self.assertEqual(first[0].artifact_digest, "sha256:" + "a" * 64)
        fetch.assert_called_once()

    def test_invalid_response_without_cache_fails_closed(self) -> None:
        with patch("services.gateway.registry_client.urlopen", return_value=_Response({"object": "list", "data": [{"id": "bad"}]})):
            with self.assertRaises(RegistryClientError):
                ModelRegistryClient("https://control-plane/v1/registry/models").models()


if __name__ == "__main__":
    unittest.main()
