import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from datetime import datetime, timezone

from runtime.llama.rpc_spike import RpcEndpoint
from runtime.llama.shared_trial import (
    DeviceInfo,
    SharedTrialError,
    TrialPlan,
    _discover_command,
    _write_failure,
    choose_local_device,
    choose_rpc_device,
    discover_devices,
    load_trial_plan,
    parse_device_listing,
    preflight_server_rpc,
    run_shared_trial,
    sibling_llama_cli,
)
from runtime.llama.tests.test_shared_run_evidence import bundle as evidence_bundle


NOW = datetime(2026, 8, 22, 6, 0, tzinfo=timezone.utc)


def plan(kind="gpu", name="NVIDIA GeForce RTX 3080 Laptop GPU") -> TrialPlan:
    return TrialPlan(
        bundle_id="experiment-bundle-0123456789abcdef",
        placement_decision_id="placement-0123456789abcdef",
        coordinator_node_id="node-a",
        worker_node_id="node-b",
        coordinator_kind=kind,
        coordinator_name=name,
        model_basename="model.gguf",
        model_size_bytes=3,
        model_sha256=hashlib.sha256(b"abc").hexdigest(),
        tensor_split=(30.0, 10.0),
        layer_ranges=(
            {"node_id": "node-a", "start_layer": 0, "end_layer_exclusive": 30},
            {"node_id": "node-b", "start_layer": 30, "end_layer_exclusive": 40},
        ),
    )


def valid_bundle_for_model(model: Path) -> dict:
    value = evidence_bundle()
    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    value["benchmark_model_name"] = model.name
    value["placement_decision"]["model"]["benchmark_model_name"] = model.name
    value["placement_decision"]["model"]["artifact_size_bytes"] = model.stat().st_size
    value["placement_decision"]["model"]["artifact_digest"] = "sha256:" + digest
    return value


class SharedTrialTests(unittest.TestCase):
    def test_parse_current_llama_device_listing(self):
        text = """ggml_cuda_init: found 1 CUDA devices:\nAvailable devices:\n  CUDA0: NVIDIA GeForce RTX 4060 Ti (16302 MiB, 15039 MiB free)\n  RPC0: 10.0.15.214:50052 (8187 MiB, 7106 MiB free)\n"""
        devices = parse_device_listing(text)
        self.assertEqual([x.name for x in devices], ["CUDA0", "RPC0"])
        self.assertIn("RTX 4060 Ti", devices[0].description)

    def test_parse_rejects_missing_section_duplicate_and_oversized_output(self):
        with self.assertRaises(SharedTrialError):
            parse_device_listing("CUDA0: gpu")
        with self.assertRaises(SharedTrialError):
            parse_device_listing("Available devices:\n CUDA0: a\n CUDA0: b\n")
        with self.assertRaises(SharedTrialError):
            parse_device_listing("Available devices:\n" + ("x" * (1024 * 1024 + 1)))

    def test_discovery_command_registers_rpc_before_listing(self):
        endpoint = RpcEndpoint.parse("192.168.1.20:50052")
        command = _discover_command(Path("llama-server"), (endpoint,))
        self.assertEqual(command[:4], ["llama-server", "--offline", "--rpc", "192.168.1.20:50052"])
        self.assertEqual(command[-1], "--list-devices")

    def test_discover_devices_is_bounded_and_requires_successful_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "llama-server"; exe.write_bytes(b"x")
            good = subprocess.CompletedProcess([], 0, stdout="Available devices:\n CUDA0: GPU (1 MiB, 1 MiB free)\n")
            devices = discover_devices(exe, runner=lambda *a, **k: good)
            self.assertEqual(devices[0].name, "CUDA0")
            bad = subprocess.CompletedProcess([], 7, stdout="Available devices:\n CUDA0: GPU\n")
            with self.assertRaises(SharedTrialError):
                discover_devices(exe, runner=lambda *a, **k: bad)

    def test_local_device_prefers_planner_hardware_description(self):
        devices = (
            DeviceInfo("CUDA0", "NVIDIA GeForce RTX 3060 (12 GiB)"),
            DeviceInfo("CUDA1", "NVIDIA GeForce RTX 3080 Laptop GPU (16 GiB)"),
        )
        self.assertEqual(choose_local_device(devices, plan()), "CUDA1")
        with self.assertRaises(SharedTrialError):
            choose_local_device(devices, plan(name="not present"))
        self.assertEqual(choose_local_device(devices, plan(), "CUDA0"), "CUDA0")

    def test_cpu_coordinator_without_offload_device_uses_none(self):
        self.assertEqual(choose_local_device((), plan(kind="cpu", name="Intel CPU")), "none")

    def test_rpc_device_must_be_unique_or_explicit(self):
        one = (DeviceInfo("CUDA0", "local"), DeviceInfo("RPC0", "remote"))
        self.assertEqual(choose_rpc_device(one), "RPC0")
        many = one + (DeviceInfo("RPC1", "remote2"),)
        with self.assertRaises(SharedTrialError):
            choose_rpc_device(many)
        self.assertEqual(choose_rpc_device(many, "RPC1"), "RPC1")

    def test_server_rpc_regression_is_distinguished_when_cli_still_sees_worker(self):
        server = Path("llama-server")
        cli = Path("llama-cli")
        endpoint = RpcEndpoint.parse("192.168.1.20:50052")

        def fake(executable, endpoints):
            if executable == server:
                return (DeviceInfo("CUDA0", "local"),)
            return (DeviceInfo("CUDA0", "local"), DeviceInfo("RPC0", "remote"))

        with self.assertRaisesRegex(SharedTrialError, "llama-server cannot expose.*llama-cli"):
            preflight_server_rpc(server, endpoint, llama_cli=cli, discovery=fake)

    def test_rpc_preflight_reports_generic_connectivity_failure_when_both_fail(self):
        endpoint = RpcEndpoint.parse("192.168.1.20:50052")

        def fail(executable, endpoints):
            raise SharedTrialError("no connection")

        with self.assertRaisesRegex(SharedTrialError, "verify worker process"):
            preflight_server_rpc(Path("server"), endpoint, llama_cli=Path("cli"), discovery=fail)

    def test_sibling_cli_is_only_used_when_real_regular_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); server = root / "llama-server"; cli = root / "llama-cli"
            server.write_bytes(b"s")
            self.assertIsNone(sibling_llama_cli(server))
            cli.write_bytes(b"c")
            self.assertEqual(sibling_llama_cli(server), cli)

    def test_load_trial_plan_binds_exact_model_and_rechecks_profile_freshness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); model = root / "model.gguf"; model.write_bytes(b"abc")
            value = valid_bundle_for_model(model)
            bundle_path = root / "bundle.json"; bundle_path.write_text(json.dumps(value), encoding="utf-8")
            loaded = load_trial_plan(bundle_path, model, now=NOW)
            self.assertEqual(loaded.model_sha256, hashlib.sha256(b"abc").hexdigest())
            self.assertEqual(loaded.tensor_split, (30.0, 10.0))
            stale = datetime(2026, 8, 24, 6, 0, tzinfo=timezone.utc)
            with self.assertRaisesRegex(SharedTrialError, "older than"):
                load_trial_plan(bundle_path, model, now=stale)

    def test_load_trial_plan_rejects_wrong_model_or_forced_nonshared_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); model = root / "model.gguf"; model.write_bytes(b"abc")
            value = valid_bundle_for_model(model)
            bundle_path = root / "bundle.json"; bundle_path.write_text(json.dumps(value), encoding="utf-8")
            model.write_bytes(b"abd")
            with self.assertRaisesRegex(SharedTrialError, "SHA-256|byte size"):
                load_trial_plan(bundle_path, model, now=NOW)
            model.write_bytes(b"abc")
            value["placement_decision"]["recommendation"]["mode"] = "local_only"
            bundle_path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(SharedTrialError, "do not force"):
                load_trial_plan(bundle_path, model, now=NOW)

    def test_runner_uses_exact_planner_split_and_builds_final_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); output = root / "trial"
            server = root / "llama-server"; server.write_bytes(b"x")
            model = root / "model.gguf"; model.write_bytes(b"abc")
            bundle_path = root / "bundle.json"; bundle_path.write_text("{}", encoding="utf-8")
            worker = RpcEndpoint.parse("192.168.1.20:50052")
            fake_plan = plan()
            captured_plans = []

            def fake_spike(spike_plan, *, prompt, output_dir, startup_timeout, request_timeout):
                captured_plans.append(spike_plan)
                output_dir.mkdir(parents=True, exist_ok=False)
                result = output_dir / "runtime_spike_result.json"
                result.write_text("{}", encoding="utf-8")
                return result

            relay = SimpleNamespace(endpoint=RpcEndpoint.parse("127.0.0.1:50053"))

            def fake_proof(**kwargs):
                kwargs["output_path"].write_text("{}", encoding="utf-8")
                return kwargs["output_path"]

            with patch("runtime.llama.shared_trial.load_trial_plan", return_value=fake_plan), \
                 patch("runtime.llama.shared_trial.runtime_version", return_value="build 1"), \
                 patch("runtime.llama.shared_trial.discover_devices", return_value=(DeviceInfo("CUDA0", fake_plan.coordinator_name),)), \
                 patch("runtime.llama.shared_trial.preflight_server_rpc", return_value=(DeviceInfo("CUDA0", "local"), DeviceInfo("RPC0", "remote"))), \
                 patch("runtime.llama.shared_trial.run_spike", side_effect=fake_spike), \
                 patch("runtime.llama.shared_trial.start_measurement_relay", return_value=relay), \
                 patch("runtime.llama.shared_trial.wait_relay_success"), \
                 patch("runtime.llama.shared_trial.compare_results", return_value={"exact_output_match": True}), \
                 patch("runtime.llama.shared_trial.write_shared_run_evidence", side_effect=fake_proof):
                proof = run_shared_trial(
                    bundle_path=bundle_path,
                    llama_server=server,
                    model_path=model,
                    worker_rpc=worker,
                    output_dir=output,
                )

            self.assertEqual(proof, output / "shared_run_evidence.json")
            self.assertEqual(captured_plans[0].devices, ("CUDA0",))
            self.assertEqual(captured_plans[1].devices, ("CUDA0", "RPC0"))
            self.assertEqual(captured_plans[1].tensor_split, (30.0, 10.0))
            self.assertEqual(captured_plans[1].rpc_endpoints[0].text(), "127.0.0.1:50053")

    def test_runner_retains_bounded_failure_record_on_correctness_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); output = root / "trial"
            server = root / "llama-server"; server.write_bytes(b"x")
            model = root / "model.gguf"; model.write_bytes(b"abc")
            bundle_path = root / "bundle.json"; bundle_path.write_text("{}", encoding="utf-8")
            relay = SimpleNamespace(endpoint=RpcEndpoint.parse("127.0.0.1:50053"))

            def fake_spike(spike_plan, *, prompt, output_dir, startup_timeout, request_timeout):
                output_dir.mkdir(parents=True, exist_ok=False)
                path = output_dir / "runtime_spike_result.json"; path.write_text("{}", encoding="utf-8"); return path

            with patch("runtime.llama.shared_trial.load_trial_plan", return_value=plan()), \
                 patch("runtime.llama.shared_trial.runtime_version", return_value="build 1"), \
                 patch("runtime.llama.shared_trial.discover_devices", return_value=(DeviceInfo("CUDA0", plan().coordinator_name),)), \
                 patch("runtime.llama.shared_trial.preflight_server_rpc", return_value=(DeviceInfo("RPC0", "remote"),)), \
                 patch("runtime.llama.shared_trial.run_spike", side_effect=fake_spike), \
                 patch("runtime.llama.shared_trial.start_measurement_relay", return_value=relay), \
                 patch("runtime.llama.shared_trial.wait_relay_success"), \
                 patch("runtime.llama.shared_trial.compare_results", return_value={"exact_output_match": False}):
                with self.assertRaisesRegex(SharedTrialError, "does not exactly match"):
                    run_shared_trial(
                        bundle_path=bundle_path,
                        llama_server=server,
                        model_path=model,
                        worker_rpc=RpcEndpoint.parse("192.168.1.20:50052"),
                        output_dir=output,
                    )
            failure = json.loads((output / "shared_trial_failure.json").read_text(encoding="utf-8"))
            self.assertEqual(failure["phase"], "comparison")
            self.assertLessEqual(len(failure["message"]), 1024)

    def test_failure_writer_bounds_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_failure(root, "phase", SharedTrialError("x" * 5000))
            value = json.loads((root / "shared_trial_failure.json").read_text(encoding="utf-8"))
            self.assertEqual(len(value["message"]), 1024)


if __name__ == "__main__":
    unittest.main()
