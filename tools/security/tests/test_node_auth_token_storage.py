from pathlib import Path
import os
import tempfile
import unittest

from tools.security.node_auth_token_storage import (
    NodeAuthTokenStorageError,
    read_existing_node_auth_token,
    rotate_node_auth_token,
)


class TestNodeAuthTokenStorage(unittest.TestCase):
    def test_rotation_replaces_existing_token_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "node_auth_token.txt"
            path.write_text("cm_tunnel_oldtoken\n", encoding="utf-8")
            rotated_path, token = rotate_node_auth_token(
                path,
                token_factory=lambda: "cm_tunnel_newtoken",
            )

            self.assertEqual(rotated_path, path)
            self.assertEqual(token, "cm_tunnel_newtoken")
            self.assertEqual(read_existing_node_auth_token([path]), token)

    def test_rotation_rejects_live_filesystem_paths(self) -> None:
        if os.name == "nt":
            self.skipTest("NodeOS live filesystem path is POSIX-only")
        with self.assertRaises(NodeAuthTokenStorageError):
            rotate_node_auth_token(Path("/run/live/node_auth_token.txt"))


if __name__ == "__main__":
    unittest.main()
