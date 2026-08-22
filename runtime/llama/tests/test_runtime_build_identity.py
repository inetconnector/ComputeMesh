import unittest

from runtime.llama.rpc_spike import (
    RpcSpikeError,
    parse_runtime_build_identity,
    runtime_build_matches,
)


class RuntimeBuildIdentityTests(unittest.TestCase):
    def test_parses_current_llama_version_shape(self):
        identity = parse_runtime_build_identity("version: 10218 (`de69995`)\nbuilt with GNU 13.3.0 for Linux x86_64")
        self.assertEqual(identity.build_number, 10218)
        self.assertEqual(identity.commit, "de69995")

    def test_accepts_short_full_commit_prefix_equivalence(self):
        identity = parse_runtime_build_identity("version: 10218 (de69995abcdef1234567890)\nbuilt with test")
        self.assertTrue(runtime_build_matches(identity, expected_number=10218, expected_commit="de69995"))
        self.assertFalse(runtime_build_matches(identity, expected_number=10217, expected_commit="de69995"))
        self.assertFalse(runtime_build_matches(identity, expected_number=10218, expected_commit="deadbee"))

    def test_rejects_unknown_or_unstructured_version(self):
        with self.assertRaises(RpcSpikeError):
            parse_runtime_build_identity("version: 0 (unknown)")
        with self.assertRaises(RpcSpikeError):
            parse_runtime_build_identity("build 10218 de69995")


if __name__ == "__main__":
    unittest.main()
