from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest

from runtime.llama.rpc_spike import RpcEndpoint
from runtime.llama.shared_request_live import (
    SharedRequestAborted,
    SharedRequestCancelled,
    run_live_shared_request,
)


class _Plan:
    model_basename = "model.gguf"
    model_size_bytes = 1
    model_sha256 = "a" * 64
    llama_build_number = 1
    llama_build_commit = "abcdef1"


class SharedRequestLiveHealthTests(unittest.TestCase):
    def _kwargs(self, root: Path):
        return dict(
            job_id="job-1",
            plan=_Plan(),
            llama_server=root / "llama-server",
            model_path=root / "model.gguf",
            worker_rpc=RpcEndpoint("127.0.0.1", 50052),
            output_dir=root / "out",
            prompt="hello",
        )

    def test_preexisting_health_abort_fails_before_runtime_or_filesystem_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            abort = threading.Event()
            abort.set()
            with self.assertRaisesRegex(SharedRequestAborted, "health was lost"):
                run_live_shared_request(**self._kwargs(Path(tmp)), abort_event=abort)
            self.assertFalse((Path(tmp) / "out").exists())

    def test_preexisting_user_cancel_remains_cancelled_not_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            cancel = threading.Event()
            cancel.set()
            with self.assertRaisesRegex(SharedRequestCancelled, "cancelled"):
                run_live_shared_request(**self._kwargs(Path(tmp)), cancel_event=cancel)
            self.assertFalse((Path(tmp) / "out").exists())


if __name__ == "__main__":
    unittest.main()
