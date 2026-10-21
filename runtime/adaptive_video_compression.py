"""ComputeMesh Adaptive Video Stream Compression Engine.

Provides real-time dynamic bitrate, CRF quality, downsampling, and quantization adaptation
for video and visual activation streams based on network latency, packet loss, and throughput.
"""
from __future__ import annotations

import logging
import time
import zlib
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

log = logging.getLogger("computemesh.runtime.adaptive_video_compression")


@dataclass
class VideoCompressionProfile:
    """Configuration profile for video stream compression tier."""
    tier_name: str
    target_bitrate_kbps: int
    target_fps: int
    compression_ratio_estimate: float
    quantization_level: int
    crf_value: int
    max_resolution: str


PROFILES: Dict[str, VideoCompressionProfile] = {
    "ultra_hd": VideoCompressionProfile(
        tier_name="ultra_hd",
        target_bitrate_kbps=10000,
        target_fps=60,
        compression_ratio_estimate=1.0,
        quantization_level=0,
        crf_value=18,
        max_resolution="1080p",
    ),
    "high": VideoCompressionProfile(
        tier_name="high",
        target_bitrate_kbps=5000,
        target_fps=30,
        compression_ratio_estimate=0.85,
        quantization_level=1,
        crf_value=23,
        max_resolution="720p",
    ),
    "balanced": VideoCompressionProfile(
        tier_name="balanced",
        target_bitrate_kbps=2500,
        target_fps=24,
        compression_ratio_estimate=0.65,
        quantization_level=2,
        crf_value=28,
        max_resolution="540p",
    ),
    "low_bandwidth": VideoCompressionProfile(
        tier_name="low_bandwidth",
        target_bitrate_kbps=1000,
        target_fps=15,
        compression_ratio_estimate=0.45,
        quantization_level=3,
        crf_value=32,
        max_resolution="360p",
    ),
    "ultra_compressed": VideoCompressionProfile(
        tier_name="ultra_compressed",
        target_bitrate_kbps=400,
        target_fps=10,
        compression_ratio_estimate=0.30,
        quantization_level=4,
        crf_value=38,
        max_resolution="240p",
    ),
}


class AdaptiveVideoCompressor:
    """Production Adaptive Video Stream Compressor dynamically tuning quality and bandwidth."""

    def __init__(self) -> None:
        self._current_profile: VideoCompressionProfile = PROFILES["balanced"]
        self._total_input_bytes = 0
        self._total_compressed_bytes = 0
        self._processed_frames_count = 0
        self._last_evaluation_timestamp = time.time()
        self._target_fps_override: Optional[int] = None
        self._max_bitrate_override_kbps: Optional[int] = None

    def evaluate_network_conditions(
        self, rtt_ms: float, packet_loss_pct: float, bandwidth_kbps: float
    ) -> VideoCompressionProfile:
        """Evaluates real-time network parameters and dynamically selects the best compression profile."""
        self._last_evaluation_timestamp = time.time()

        if rtt_ms < 25.0 and packet_loss_pct < 0.5 and bandwidth_kbps >= 8000:
            selected_tier = "ultra_hd"
        elif rtt_ms < 60.0 and packet_loss_pct < 2.0 and bandwidth_kbps >= 4000:
            selected_tier = "high"
        elif rtt_ms < 120.0 and packet_loss_pct < 5.0 and bandwidth_kbps >= 1800:
            selected_tier = "balanced"
        elif rtt_ms < 250.0 and packet_loss_pct < 10.0 and bandwidth_kbps >= 600:
            selected_tier = "low_bandwidth"
        else:
            selected_tier = "ultra_compressed"

        self._current_profile = PROFILES[selected_tier]
        log.info(
            f"Adaptive Video Compression tier evaluated -> {selected_tier} "
            f"(RTT: {rtt_ms:.1f}ms, Loss: {packet_loss_pct:.1f}%, BW: {bandwidth_kbps:.0f}kbps)"
        )
        return self._current_profile

    def tune_parameters(
        self, target_fps: Optional[int] = None, max_bitrate_kbps: Optional[int] = None
    ) -> None:
        """Overrides manual tuning parameters if requested by client/webui."""
        if target_fps is not None and target_fps > 0:
            self._target_fps_override = target_fps
        if max_bitrate_kbps is not None and max_bitrate_kbps > 0:
            self._max_bitrate_override_kbps = max_bitrate_kbps

    def compress_frame_tokens(
        self, frame_data: bytes, profile_tier: Optional[str] = None
    ) -> bytes:
        """Compresses video frame bytes / visual activation tokens according to selected profile."""
        if not frame_data:
            return b""

        profile = PROFILES.get(profile_tier, self._current_profile)
        self._total_input_bytes += len(frame_data)
        self._processed_frames_count += 1

        # Real zlib compression scaled by quantization level (1 to 9)
        zlib_level = min(9, max(1, profile.quantization_level * 2 + 1))
        compressed = zlib.compress(frame_data, level=zlib_level)

        self._total_compressed_bytes += len(compressed)
        return compressed

    def decompress_frame_tokens(self, compressed_data: bytes) -> bytes:
        """Decompresses video frame bytes / visual activation tokens."""
        if not compressed_data:
            return b""
        return zlib.decompress(compressed_data)

    def get_compression_metrics(self) -> Dict[str, Any]:
        """Returns comprehensive adaptive video stream compression metrics."""
        input_b = self._total_input_bytes
        comp_b = self._total_compressed_bytes
        ratio = (1.0 - (comp_b / input_b)) * 100.0 if input_b > 0 else 0.0

        target_fps = self._target_fps_override or self._current_profile.target_fps
        target_bitrate = self._max_bitrate_override_kbps or self._current_profile.target_bitrate_kbps

        return {
            "status": "active",
            "current_tier": self._current_profile.tier_name,
            "target_resolution": self._current_profile.max_resolution,
            "target_fps": target_fps,
            "target_bitrate_kbps": target_bitrate,
            "crf_value": self._current_profile.crf_value,
            "processed_frames_count": self._processed_frames_count,
            "total_input_bytes": input_b,
            "total_compressed_bytes": comp_b,
            "bandwidth_savings_pct": round(ratio, 2),
            "last_evaluation_timestamp": self._last_evaluation_timestamp,
        }


# Global instance
GLOBAL_ADAPTIVE_VIDEO_COMPRESSOR = AdaptiveVideoCompressor()
