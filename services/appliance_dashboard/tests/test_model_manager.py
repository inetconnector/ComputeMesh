"""Tests for ModelManager and HuggingFace Hub Client."""
from __future__ import annotations

import hashlib
import http.server
import tempfile
import threading
import time
import unittest
from pathlib import Path

from services.appliance_dashboard.model_manager import POPULAR_GGUF_MODELS, ModelManager


class MockDownloadHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class TestModelManager(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_storage = tempfile.TemporaryDirectory()
        self.manager = ModelManager(Path(self.temp_storage.name))

        # Setup local mock HTTP server for downloads
        self.server_dir = tempfile.TemporaryDirectory()
        # Ensure payload starts with GGUF magic header
        self.mock_file_content = b"GGUF" + (b"TEST_GGUF_BINARY_PAYLOAD_CHUNK_DATA_9876543210" * 100)
        self.mock_sha256 = hashlib.sha256(self.mock_file_content).hexdigest()

        mock_file_path = Path(self.server_dir.name) / "mock_model.gguf"
        mock_file_path.write_bytes(self.mock_file_content)

        handler_cls = lambda *args, **kwargs: MockDownloadHandler(*args, directory=self.server_dir.name, **kwargs)
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 18997), handler_cls)
        self.server_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.server_thread.start()
        time.sleep(0.1)

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.server_dir.cleanup()
        self.temp_storage.cleanup()

    def test_storage_stats(self) -> None:
        stats = self.manager.get_storage_stats()
        self.assertIn("free_bytes", stats)
        self.assertIn("total_bytes", stats)
        self.assertGreater(stats["total_bytes"], 0)

    def test_popular_models_list(self) -> None:
        results = self.manager.search_huggingface("")
        self.assertTrue(len(results) >= len(POPULAR_GGUF_MODELS))
        qwen_results = self.manager.search_huggingface("Qwen")
        self.assertTrue(any("qwen" in r["name"].lower() for r in qwen_results))

    def test_path_traversal_prevention(self) -> None:
        with self.assertRaises(ValueError):
            self.manager.delete_model("../../etc/shadow.gguf")
        with self.assertRaises(ValueError):
            self.manager.start_download(
                url="http://127.0.0.1:18997/mock_model.gguf",
                filename="../malicious.gguf",
            )
        with self.assertRaises(ValueError):
            self.manager.start_download(
                url="http://127.0.0.1:18997/mock_model.gguf",
                filename="script.sh",
            )

    def test_invalid_magic_header_rejected(self) -> None:
        bad_file = Path(self.server_dir.name) / "bad_magic.gguf"
        bad_file.write_bytes(b"NOT_A_GGUF_MAGIC_HEADER_DATA")
        dl_id = self.manager.start_download(
            url="http://127.0.0.1:18997/bad_magic.gguf",
            filename="bad_magic.gguf",
        )
        for _ in range(50):
            prog = self.manager.active_downloads.get(dl_id)
            if prog and prog.status in ("COMPLETED", "FAILED"):
                break
            time.sleep(0.1)

        prog = self.manager.active_downloads[dl_id]
        self.assertEqual(prog.status, "FAILED")
        self.assertIn("not a valid GGUF", prog.error_message or "")

    def test_atomic_download_and_sha256_verification(self) -> None:
        url = "http://127.0.0.1:18997/mock_model.gguf"
        filename = "downloaded_test_model.gguf"
        dl_id = self.manager.start_download(
            url=url,
            filename=filename,
            repo_id="test/mock-repo",
            expected_size_bytes=len(self.mock_file_content),
            expected_sha256=self.mock_sha256,
        )

        # Wait for download worker
        for _ in range(50):
            prog = self.manager.active_downloads.get(dl_id)
            if prog and prog.status in ("COMPLETED", "FAILED"):
                break
            time.sleep(0.1)

        prog = self.manager.active_downloads[dl_id]
        self.assertEqual(prog.status, "COMPLETED")
        self.assertEqual(prog.percent, 100.0)

        # Check local file exists and was renamed from .part
        target_path = self.manager.storage_dir / filename
        self.assertTrue(target_path.exists())
        self.assertEqual(target_path.stat().st_size, len(self.mock_file_content))

        # Check list_local_models
        local_models = self.manager.list_local_models()
        self.assertTrue(any(m.filename == filename for m in local_models))

        # Delete model
        ok = self.manager.delete_model(filename)
        self.assertTrue(ok)
        self.assertFalse(target_path.exists())

    def test_checksum_mismatch_fails_and_removes_part(self) -> None:
        url = "http://127.0.0.1:18997/mock_model.gguf"
        filename = "mismatched_model.gguf"
        dl_id = self.manager.start_download(
            url=url,
            filename=filename,
            repo_id="test/mock-repo",
            expected_size_bytes=len(self.mock_file_content),
            expected_sha256="invalid_expected_sha256_hash",
        )

        for _ in range(50):
            prog = self.manager.active_downloads.get(dl_id)
            if prog and prog.status in ("COMPLETED", "FAILED"):
                break
            time.sleep(0.1)

        prog = self.manager.active_downloads[dl_id]
        self.assertEqual(prog.status, "FAILED")
        self.assertIn("Checksum mismatch", prog.error_message or "")
        self.assertFalse((self.manager.storage_dir / filename).exists())
        self.assertFalse((self.manager.storage_dir / f"{filename}.part").exists())


if __name__ == "__main__":
    unittest.main()
