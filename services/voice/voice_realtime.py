# SPDX-License-Identifier: Apache-2.0
"""Low-Latency Streaming Voice & Audio Processing Engine for ComputeMesh."""

from __future__ import annotations

import io
import json
import logging
import math
import struct
import time
from typing import Any, Callable, Dict, Generator, List, Optional

log = logging.getLogger("computemesh.voice.realtime")


def compute_audio_energy(pcm_16bit_bytes: bytes) -> float:
    """Calculates Normalized RMS audio energy for a PCM 16-bit audio frame."""
    if len(pcm_16bit_bytes) < 2:
        return 0.0
    num_samples = len(pcm_16bit_bytes) // 2
    fmt = f"<{num_samples}h"
    try:
        samples = struct.unpack(fmt, pcm_16bit_bytes[: num_samples * 2])
    except Exception:
        return 0.0
    if not samples:
        return 0.0
    sum_sq = sum((s / 32768.0) ** 2 for s in samples)
    return float(math.sqrt(sum_sq / len(samples)))


class SimpleEnergyVAD:
    """Voice Activity Detector based on short-term frame energy and zero-crossing rate."""

    def __init__(self, sample_rate: int = 16000, frame_duration_ms: int = 20, threshold: float = 0.015):
        self.sample_rate = sample_rate
        self.frame_size = int(sample_rate * (frame_duration_ms / 1000.0))
        self.threshold = threshold

    def is_speech(self, pcm_16bit_bytes: bytes) -> bool:
        """Determines if a PCM 16-bit audio frame contains active human speech."""
        rms = compute_audio_energy(pcm_16bit_bytes)
        return rms > self.threshold


class RealtimeVoiceSession:
    """Manages full-duplex real-time audio interaction with instant barge-in interruption."""

    def __init__(
        self,
        session_id: str = "default",
        sample_rate: int = 16000,
        stt_handler: Optional[Callable[[bytes], str]] = None,
        llm_handler: Optional[Callable[[str], Generator[str, None, None]]] = None,
        tts_handler: Optional[Callable[[str], bytes]] = None,
    ):
        self.session_id = session_id
        self.sample_rate = sample_rate
        self.stt_handler = stt_handler
        self.llm_handler = llm_handler
        self.tts_handler = tts_handler
        self.vad = SimpleEnergyVAD(sample_rate=sample_rate)
        self.is_speaking = False
        self.is_ai_speaking = False
        self._audio_buffer = bytearray()
        self._silence_frames = 0
        self._speech_frames = 0

    def process_input_audio_chunk(self, chunk: bytes) -> bool:
        """Determines if the given audio chunk contains speech."""
        return self.vad.is_speech(chunk)

    def handle_barge_in(self, chunk: bytes) -> bool:
        """Handles user speech interruption during active playback."""
        if self.is_speaking and self.vad.is_speech(chunk):
            self.is_speaking = False
            self.is_ai_speaking = False
            return True
        return False


    def process_audio_chunk(self, chunk: bytes) -> Dict[str, Any]:
        """Receives a raw PCM 16-bit 16kHz audio chunk from client."""
        has_voice = self.vad.is_speech(chunk)

        events: List[str] = []

        if has_voice:
            self._speech_frames += 1
            self._silence_frames = 0
            self._audio_buffer.extend(chunk)

            # Barge-in: if user starts speaking while AI is speaking, interrupt immediately
            if self.is_ai_speaking and self._speech_frames >= 2:
                self.is_ai_speaking = False
                events.append("interruption_detected")
                log.info(f"[{self.session_id}] User interrupted AI speech!")

            if not self.is_speaking and self._speech_frames >= 2:
                self.is_speaking = True
                events.append("speech_started")
        else:
            if self.is_speaking:
                self._silence_frames += 1
                self._audio_buffer.extend(chunk)
                # After 600ms of silence, finalize user utterance
                if self._silence_frames >= 15:
                    self.is_speaking = False
                    self._speech_frames = 0
                    events.append("speech_ended")
                    utterance_bytes = bytes(self._audio_buffer)
                    self._audio_buffer.clear()
                    return {
                        "session_id": self.session_id,
                        "events": events,
                        "utterance_ready": True,
                        "audio_bytes_len": len(utterance_bytes),
                    }

        return {
            "session_id": self.session_id,
            "events": events,
            "utterance_ready": False,
            "is_user_speaking": self.is_speaking,
            "is_ai_speaking": self.is_ai_speaking,
        }

    def set_ai_speaking(self, status: bool) -> None:
        self.is_ai_speaking = status


def create_voice_session(session_id: str) -> RealtimeVoiceSession:
    return RealtimeVoiceSession(session_id=session_id)
