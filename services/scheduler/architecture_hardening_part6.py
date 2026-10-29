import collections
import hashlib
import time
import copy
from typing import Any, Dict, List, Optional, Set, Tuple

class HardeningPart6Error(RuntimeError):
    pass

class WholeExecutionPathError(HardeningPart6Error):
    pass

class OSNeutralContractError(HardeningPart6Error):
    pass

class ExplicitBoundaryError(HardeningPart6Error):
    pass

class ExecutionPathOptimizer:
    def __init__(self, optimize_whole_path: bool = True):
        self.optimize_whole_path = optimize_whole_path

    def optimize_and_verify(self, plan: Dict[str, Any]) -> None:
        if "optimization_target" in plan and plan["optimization_target"] == "individual_gpu":
            raise WholeExecutionPathError("MUST optimize the whole execution path, not individual GPUs.")

        if len(plan.get("provider_node_ids", [])) > 1:
            if "network_latency_ms" not in plan or "tensor_split" not in plan:
                raise WholeExecutionPathError("MUST optimize the whole execution path, including network and tensor split.")

            latency = plan.get("network_latency_ms", 100)
            tensor_split = list(plan.get("tensor_split", [0.5, 0.5]))

            if len(tensor_split) >= 2:
                if latency > 50:
                    tensor_split[0] = min(0.9, tensor_split[0] * 1.2)
                    tensor_split[1] = 1.0 - tensor_split[0]
                    plan["tensor_split"] = tensor_split
                    plan["path_optimization_applied"] = "latency_heuristic"
                else:
                    plan["path_optimization_applied"] = "balanced_compute"
            else:
                plan["path_optimization_applied"] = "balanced_compute"

        plan["execution_path_optimized"] = True

class OSNeutralProtocolEnforcer:
    def __init__(self):
        self.forbidden_os_specific_keys = {"windows_registry", "linux_cgroups", "mac_plist", "win32_handle", "unix_socket_path"}

    def validate_contract(self, contract: Dict[str, Any]) -> None:
        self._check_dict(contract)
        self._check_paths(contract)

    def _check_dict(self, d: Dict[str, Any]) -> None:
        for key, value in d.items():
            if key in self.forbidden_os_specific_keys:
                raise OSNeutralContractError(f"Protocol contracts MUST remain OS-neutral. Found OS-specific key: {key}")
            if isinstance(value, dict):
                self._check_dict(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        self._check_dict(item)
                    elif isinstance(item, str) and item in self.forbidden_os_specific_keys:
                         raise OSNeutralContractError(f"Protocol contracts MUST remain OS-neutral. Found OS-specific key: {item}")

    def _check_paths(self, d: Dict[str, Any]) -> None:
        for key, value in d.items():
            if isinstance(value, str) and ("\\" in value and ":" in value):
                 raise OSNeutralContractError(f"Protocol contracts MUST remain OS-neutral. Found OS-specific path format: {value}")
            if isinstance(value, dict):
                self._check_paths(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        self._check_paths(item)
                    elif isinstance(item, str) and ("\\" in item and ":" in item):
                        raise OSNeutralContractError(f"Protocol contracts MUST remain OS-neutral. Found OS-specific path format: {item}")

class ComponentBoundaryEnforcer:
    def __init__(self):
        self.explicit_boundaries = {"scheduler", "dispatcher", "verifier", "gateway", "runtime"}

    def call_across_boundary(self, source: str, target: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if source not in self.explicit_boundaries or target not in self.explicit_boundaries:
            raise ExplicitBoundaryError(f"The boundary MUST remain explicit in code. Unknown component: {source} -> {target}")

        payload_copy = {k: v for k, v in payload.items() if k != "boundary_transition"}

        def _make_hashable(obj):
            if isinstance(obj, dict):
                return tuple(sorted((k, _make_hashable(v)) for k, v in obj.items()))
            elif isinstance(obj, (list, tuple)):
                return tuple(_make_hashable(x) for x in obj)
            return obj

        canonical_form = str(_make_hashable(payload_copy)).encode('utf-8')
        payload_hash = hashlib.sha256(canonical_form).hexdigest()

        transition_marker = {
            "boundary_transition": {
                "source": source,
                "target": target,
                "explicit": True,
                "payload_hash": payload_hash,
                "timestamp": time.time()
            }
        }

        augmented = copy.deepcopy(payload)
        augmented.update(transition_marker)
        return augmented
