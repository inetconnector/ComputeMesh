"""ComputeMesh Dynamic Mesh & Sharding API Handler for Appliance Dashboard."""
from __future__ import annotations

import json
from http import HTTPStatus
from typing import Any

from runtime.dynamic_sharding import DynamicShardingEngine, NodeShardCapability
from runtime.distributed_model_cache import GLOBAL_DISTRIBUTED_MODEL_CACHE
from runtime.p2p_stream_federation import GLOBAL_STREAM_FEDERATOR
from runtime.multi_cluster_federation import GLOBAL_MULTI_CLUSTER_FEDERATOR
from runtime.zero_trust_worker import GLOBAL_ZERO_TRUST_WORKER_COMMUNICATOR
from runtime.adaptive_video_compression import GLOBAL_ADAPTIVE_VIDEO_COMPRESSOR
from services.appliance_dashboard.mesh_aggregator import GLOBAL_MESH_AGGREGATOR


class MeshShardingHandler:
    """Sub-handler managing endpoints for Dynamic Sharding, Distributed Cache, P2P Stream Federation, Multi-Cluster Federation, Zero-Trust Worker Communication, and Adaptive Video Stream Compression."""

    @staticmethod
    def handle_get(handler_inst: Any, path: str) -> bool:
        if path == "/api/v1/mesh/sharding/plan":
            local_status = getattr(handler_inst, "_get_status_dict", lambda: None)()
            mesh_stats = GLOBAL_MESH_AGGREGATOR.get_mesh_stats(local_status=local_status)

            nodes_cap = []
            for n in mesh_stats.get("nodes", []):
                nid = n.get("node_id", "unknown")
                vram_bytes = int(n.get("vram_gb", 0) * (1024**3))
                tflops = float(n.get("tflops", 0.0))
                is_local = bool(n.get("is_local", False))
                nodes_cap.append(
                    NodeShardCapability(
                        node_id=nid,
                        vram_bytes=vram_bytes,
                        tflops=tflops,
                        is_local=is_local,
                    )
                )

            # Sample 72B parameters model plan calculation
            plan = DynamicShardingEngine.calculate_sharding_plan(
                model_id="Qwen/Qwen2.5-72B-Instruct-GGUF",
                total_layers=80,
                model_vram_bytes=42 * 1024 * 1024 * 1024,  # 42GB VRAM
                nodes=nodes_cap,
            )

            handler_inst._send_json(
                {
                    "sharding_plan": {
                        "model_id": plan.model_id,
                        "total_layers": plan.total_layers,
                        "required_vram_bytes": plan.required_vram_bytes,
                        "required_vram_gb": round(plan.required_vram_bytes / (1024**3), 2),
                        "feasible": plan.feasible,
                        "reason": plan.reason,
                        "estimated_pipeline_latency_ms": plan.estimated_pipeline_latency_ms,
                        "tensor_parallel_enabled": plan.tensor_parallel_enabled,
                        "assignments": [
                            {
                                "node_id": a.node_id,
                                "start_layer": a.start_layer,
                                "end_layer": a.end_layer,
                                "assigned_layers_count": a.assigned_layers_count,
                                "allocated_vram_gb": round(a.allocated_vram_bytes / (1024**3), 2),
                                "fraction": a.fraction,
                                "is_local": a.is_local,
                                "tensor_parallel_degree": a.tensor_parallel_degree,
                                "estimated_transfer_ms": a.estimated_transfer_ms,
                            }
                            for a in plan.assignments
                        ],
                    }
                }
            )
            return True

        if path == "/api/v1/mesh/cache/status":
            summary = GLOBAL_DISTRIBUTED_MODEL_CACHE.get_cache_summary()
            handler_inst._send_json({"distributed_model_cache": summary})
            return True

        if path == "/api/v1/mesh/stream/status":
            peers_health = GLOBAL_STREAM_FEDERATOR.get_peer_health()
            handler_inst._send_json(
                {
                    "p2p_stream_federation": {
                        "status": "active",
                        "peers_count": len(GLOBAL_STREAM_FEDERATOR._peers),
                        "active_streams_count": len(GLOBAL_STREAM_FEDERATOR._active_streams),
                        "peers": peers_health,
                    }
                }
            )
            return True

        if path in ("/api/v1/mesh/federation/clusters", "/api/v1/mesh/federation/health"):
            capacity = GLOBAL_MULTI_CLUSTER_FEDERATOR.get_federated_capacity()
            handler_inst._send_json({"multi_cluster_federation": capacity})
            return True

        if path == "/api/v1/mesh/zero_trust/status":
            zt_status = GLOBAL_ZERO_TRUST_WORKER_COMMUNICATOR.get_zero_trust_status()
            handler_inst._send_json({"zero_trust_worker_communication": zt_status})
            return True

        if path == "/api/v1/mesh/video/compression/status":
            comp_metrics = GLOBAL_ADAPTIVE_VIDEO_COMPRESSOR.get_compression_metrics()
            handler_inst._send_json({"adaptive_video_stream_compression": comp_metrics})
            return True

        return False

    @staticmethod
    def handle_post(handler_inst: Any, path: str, post_body: bytes) -> bool:
        if path == "/api/v1/mesh/sharding/calculate":
            try:
                data = json.loads(post_body.decode("utf-8")) if post_body else {}
                model_id = str(data.get("model_id", "Qwen/Qwen2.5-72B-Instruct-GGUF"))
                total_layers = int(data.get("total_layers", 80))
                model_vram_bytes = int(data.get("model_vram_bytes", 42 * 1024 * 1024 * 1024))
                enable_tp = bool(data.get("enable_tensor_parallel", False))

                local_status = getattr(handler_inst, "_get_status_dict", lambda: None)()
                mesh_stats = GLOBAL_MESH_AGGREGATOR.get_mesh_stats(local_status=local_status)

                nodes_cap = []
                for n in mesh_stats.get("nodes", []):
                    nid = n.get("node_id", "unknown")
                    vram_bytes = int(n.get("vram_gb", 0) * (1024**3))
                    tflops = float(n.get("tflops", 0.0))
                    is_local = bool(n.get("is_local", False))
                    nodes_cap.append(
                        NodeShardCapability(
                            node_id=nid,
                            vram_bytes=vram_bytes,
                            tflops=tflops,
                            is_local=is_local,
                        )
                    )

                plan = DynamicShardingEngine.calculate_sharding_plan(
                    model_id=model_id,
                    total_layers=total_layers,
                    model_vram_bytes=model_vram_bytes,
                    nodes=nodes_cap,
                    enable_tensor_parallel=enable_tp,
                )

                handler_inst._send_json(
                    {
                        "sharding_plan": {
                            "model_id": plan.model_id,
                            "total_layers": plan.total_layers,
                            "required_vram_bytes": plan.required_vram_bytes,
                            "required_vram_gb": round(plan.required_vram_bytes / (1024**3), 2),
                            "feasible": plan.feasible,
                            "reason": plan.reason,
                            "estimated_pipeline_latency_ms": plan.estimated_pipeline_latency_ms,
                            "tensor_parallel_enabled": plan.tensor_parallel_enabled,
                            "assignments": [
                                {
                                    "node_id": a.node_id,
                                    "start_layer": a.start_layer,
                                    "end_layer": a.end_layer,
                                    "assigned_layers_count": a.assigned_layers_count,
                                    "allocated_vram_gb": round(a.allocated_vram_bytes / (1024**3), 2),
                                    "fraction": a.fraction,
                                    "is_local": a.is_local,
                                    "tensor_parallel_degree": a.tensor_parallel_degree,
                                    "estimated_transfer_ms": a.estimated_transfer_ms,
                                }
                                for a in plan.assignments
                            ],
                        }
                    }
                )
                return True
            except Exception as exc:
                handler_inst._send_json(
                    {"error": {"message": f"Invalid sharding calculation request: {exc}", "code": 400}},
                    HTTPStatus.BAD_REQUEST,
                )
                return True

        if path == "/api/v1/mesh/cache/clear":
            GLOBAL_DISTRIBUTED_MODEL_CACHE.clear_all()
            handler_inst._send_json({"status": "success", "message": "Distributed model cache cleared successfully"})
            return True

        if path == "/api/v1/mesh/cache/verify":
            try:
                data = json.loads(post_body.decode("utf-8")) if post_body else {}
                model_id = str(data.get("model_id", ""))
                res = GLOBAL_DISTRIBUTED_MODEL_CACHE.verify_shard_integrity(model_id)
                handler_inst._send_json({"integrity": res})
                return True
            except Exception as exc:
                handler_inst._send_json(
                    {"error": {"message": f"Cache verification failed: {exc}", "code": 400}},
                    HTTPStatus.BAD_REQUEST,
                )
                return True

        if path == "/api/v1/mesh/federation/sync":
            try:
                data = json.loads(post_body.decode("utf-8")) if post_body else {}
                clusters = data.get("clusters", [])
                synced_count = GLOBAL_MULTI_CLUSTER_FEDERATOR.sync_cluster_states(clusters)
                handler_inst._send_json(
                    {
                        "status": "success",
                        "synced_clusters_count": synced_count,
                        "federated_capacity": GLOBAL_MULTI_CLUSTER_FEDERATOR.get_federated_capacity(),
                    }
                )
                return True
            except Exception as exc:
                handler_inst._send_json(
                    {"error": {"message": f"Multi-cluster sync failed: {exc}", "code": 400}},
                    HTTPStatus.BAD_REQUEST,
                )
                return True

        if path == "/api/v1/mesh/video/compression/tune":
            try:
                data = json.loads(post_body.decode("utf-8")) if post_body else {}
                rtt_ms = float(data.get("rtt_ms", 35.0))
                loss_pct = float(data.get("packet_loss_pct", 0.5))
                bw_kbps = float(data.get("bandwidth_kbps", 3000.0))
                target_fps = data.get("target_fps")
                max_bitrate = data.get("max_bitrate_kbps")

                profile = GLOBAL_ADAPTIVE_VIDEO_COMPRESSOR.evaluate_network_conditions(
                    rtt_ms=rtt_ms, packet_loss_pct=loss_pct, bandwidth_kbps=bw_kbps
                )
                if target_fps or max_bitrate:
                    GLOBAL_ADAPTIVE_VIDEO_COMPRESSOR.tune_parameters(
                        target_fps=int(target_fps) if target_fps else None,
                        max_bitrate_kbps=int(max_bitrate) if max_bitrate else None,
                    )

                handler_inst._send_json(
                    {
                        "status": "success",
                        "adaptive_video_stream_compression": GLOBAL_ADAPTIVE_VIDEO_COMPRESSOR.get_compression_metrics(),
                    }
                )
                return True
            except Exception as exc:
                handler_inst._send_json(
                    {"error": {"message": f"Video compression tuning failed: {exc}", "code": 400}},
                    HTTPStatus.BAD_REQUEST,
                )
                return True

        return False
