"""Real contract/negative tests for the opt-in Kimi-Linear two-host path.

Positive GPU inference cannot be claimed without a physical CUDA+Polaris
topology and a downloaded, verified 30–41 GB GGUF artifact.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime.llama.kimi_linear_dual_host import (
    KimiDualHostError,
    _usable_mib,
    build_kimi_dual_host_plan,
)
from runtime.llama.rpc_spike import RpcEndpoint, SpikePlan, build_coordinator_command


class KimiDualHostTests(unittest.TestCase):
    def test_actual_free_memory_budget_not_advertised_capacity(self) -> None:
        self.assertEqual(_usable_mib("Vulkan GPU (8192 MiB, 7138 MiB free)", 1024), 6114)
        for detail in (
            "Vulkan GPU (8192 MiB)",
            "Vulkan GPU (8192 MiB, 0 MiB free)",
            "Vulkan GPU (8192 MiB, 700 MiB free)",
            "Vulkan GPU (8192 MiB, 7000 MiB free; 7001 MiB free)",
        ):
            with self.subTest(detail=detail), self.assertRaises(KimiDualHostError):
                _usable_mib(detail, 1024)

    def test_rpc_network_must_be_authenticated_tunnel_loopback(self) -> None:
        with self.assertRaisesRegex(KimiDualHostError, "authenticated loopback tunnel"):
            build_kimi_dual_host_plan(
                llama_server=Path("llama-server"),
                model=Path("model.gguf"),
                model_sha256="a" * 64,
                quant="Q6_K",
                worker_rpc=RpcEndpoint.parse("192.168.1.20:50052"),
                expected_runtime_commit="abcdef0",
            )

    def test_invalid_hash_is_rejected_before_model_open(self) -> None:
        with self.assertRaisesRegex(KimiDualHostError, "trusted model SHA-256"):
            build_kimi_dual_host_plan(
                llama_server=Path("llama-server"),
                model=Path("model.gguf"),
                model_sha256="invalid",
                quant="Q6_K",
                worker_rpc=RpcEndpoint.parse("127.0.0.1:50052"),
                expected_runtime_commit="abcdef0",
            )

    def test_tiny_or_unrecognized_model_never_reaches_remote_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "Kimi-Linear-48B-A3B-Instruct-Q6_K.gguf"
            model.write_bytes(b"GGUF" + b"x" * 128)
            digest = hashlib.sha256(model.read_bytes()).hexdigest()
            with self.assertRaisesRegex(KimiDualHostError, "model size"):
                build_kimi_dual_host_plan(
                    llama_server=Path("llama-server"),
                    model=model, model_sha256=digest, quant="Q6_K",
                    worker_rpc=RpcEndpoint.parse("127.0.0.1:50052"),
                    expected_runtime_commit="abcdef0",
                )

    def test_nodeos_packages_opt_in_rpc_without_auto_start(self) -> None:
        root = Path(__file__).resolve().parents[3]
        builder = (root / "deploy/appliance/build_real_live_appliance.py").read_text(encoding="utf-8")
        worker = (root / "deploy/systemd/computemesh-rpc-worker.service").read_text(encoding="utf-8")
        self.assertIn("COMPUTEMESH_ENABLE_RPC_EXPERIMENT", builder)
        self.assertIn("DGGML_RPC={", builder)
        self.assertIn("-DBUILD_SHARED_LIBS=OFF", builder)
        self.assertIn('targets = "llama-server ggml-rpc-server" if rpc_enabled else "llama-server"', builder)
        self.assertIn('rpc_source = cm_target / "deploy" / "systemd" / "computemesh-rpc-worker.service"', builder)
        self.assertIn("if rpc_enabled:\n            rpc_source =", builder)
        self.assertIn("shutil.copy(\n                rpc_source,", builder)
        self.assertNotIn("systemctl enable computemesh-rpc-worker", builder)
        self.assertIn("127.0.0.1", worker)
        self.assertNotIn("0.0.0.0", worker)
        self.assertIn("ConditionPathExists=/run/computemesh/node-preflight.ok", worker)

    def test_rpc_build_is_disabled_by_default(self) -> None:
        from deploy.appliance.build_real_live_appliance import _rpc_build_enabled
        with patch.dict("os.environ", {"COMPUTEMESH_ENABLE_RPC_EXPERIMENT": "0"}):
            self.assertFalse(_rpc_build_enabled())
        with patch.dict("os.environ", {"COMPUTEMESH_ENABLE_RPC_EXPERIMENT": "1"}):
            self.assertTrue(_rpc_build_enabled())
        with patch.dict("os.environ", {"COMPUTEMESH_ENABLE_RPC_EXPERIMENT": "invalid"}):
            self.assertFalse(_rpc_build_enabled())

    def test_existing_rpc_runner_builds_seven_device_offload(self) -> None:
        devices = ("CUDA0",) + tuple(f"RPC{i}" for i in range(6))
        plan = SpikePlan(
            Path("llama-server"), Path("kimi.gguf"),
            (RpcEndpoint.parse("127.0.0.1:50052"),),
            devices, (14000.0,) + (6100.0,) * 6,
        )
        args = build_coordinator_command(plan)
        self.assertEqual(args[args.index("--rpc") + 1], "127.0.0.1:50052")
        self.assertEqual(args[args.index("--device") + 1], ",".join(devices))
        self.assertEqual(len(args[args.index("--tensor-split") + 1].split(",")), 7)
        self.assertEqual(args[args.index("--host") + 1], "127.0.0.1")
        self.assertEqual(args[args.index("--fit") + 1], "off")
        self.assertIn("--offline", args)


if __name__ == "__main__":
    unittest.main()
