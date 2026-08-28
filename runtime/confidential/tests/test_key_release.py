import unittest
from runtime.confidential.key_release import KeyReleaseBinding, KeyReleaseError, reject_server_side_content_key


class KeyReleaseTests(unittest.TestCase):
    def test_attested_binding_accepts_exact_target(self):
        KeyReleaseBinding("job", "node", "nonce", "pk").bind_ciphertext_recipient(node_id="node", nonce="nonce", public_key="pk")

    def test_binding_changes_are_rejected(self):
        binding = KeyReleaseBinding("job", "node", "nonce", "pk")
        for kwargs in ({"node_id": "other", "nonce": "nonce", "public_key": "pk"}, {"node_id": "node", "nonce": "other", "public_key": "pk"}, {"node_id": "node", "nonce": "nonce", "public_key": "other"}):
            with self.assertRaises(KeyReleaseError):
                binding.bind_ciphertext_recipient(**kwargs)

    def test_gateway_content_key_path_is_deliberately_absent(self):
        with self.assertRaises(KeyReleaseError):
            reject_server_side_content_key("secret")


if __name__ == "__main__":
    unittest.main()
