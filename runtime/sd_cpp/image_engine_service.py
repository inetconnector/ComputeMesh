#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""ComputeMesh High-Performance Image Generation Service.

Manages local sd.cpp / sd-server with CUDA / ROCm / Vulkan acceleration,
handles automatic model provisioning (SDXL-Lightning / FLUX GGUF / SD 1.5),
and exposes an OpenAI-compatible /v1/images/generations HTTP endpoint for
ComputeMesh LAN nodes, Mobile Apps, and Miner Nodes.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [ComputeMesh.ImageEngine] %(message)s",
)
log = logging.getLogger("computemesh.image_engine")

BASE_DIR = Path(__file__).resolve().parent
BIN_DIR = BASE_DIR / "bin"
MODELS_DIR = BASE_DIR.parents[1] / "models" / "diffusion"

# Recommended fast models for high-performance generation
FAST_MODELS = {
    "realvisxl-lightning": {
        "url": "https://huggingface.co/SG161222/RealVisXL_V4.0_Lightning/resolve/main/RealVisXL_V4.0_Lightning.safetensors",
        "filename": "RealVisXL_V4.0_Lightning.safetensors",
        "type": "sdxl",
        "description": "RealVisXL V4.0 Lightning (State of the Art Photorealism, 1024x1024, ~8-12GB VRAM)",
    },
    "sdxl-lightning": {
        "url": "https://huggingface.co/ByteDance/SDXL-Lightning/resolve/main/sdxl_lightning_4step.safetensors",
        "filename": "sdxl_lightning_4step.safetensors",
        "type": "sdxl",
        "description": "SDXL Lightning (4-Step Ultra Fast, 1024x1024, ~8-12GB VRAM)",
    },
    "flux-schnell-q4": {
        "url": "https://huggingface.co/city96/FLUX.1-schnell-gguf/resolve/main/flux1-schnell-Q4_0.gguf",
        "filename": "flux1-schnell-Q4_0.gguf",
        "type": "flux",
        "description": "FLUX.1 Schnell GGUF Q4 (State of the art 4-step, ~12-16GB VRAM)",
    },
    "sd15-fast": {
        "url": "https://huggingface.co/runwayml/stable-diffusion-v1-5/resolve/main/v1-5-pruned-emaonly.safetensors",
        "filename": "v1-5-pruned-emaonly.safetensors",
        "type": "sd15",
        "description": "Standard SD 1.5 (High Speed, ~4GB VRAM)",
    },
}


def find_sd_server_binary() -> Optional[Path]:
    """Locate the compiled sd-server binary on Windows or Linux."""
    system_ext = ".exe" if platform.system() == "Windows" else ""
    candidates = [
        BIN_DIR / f"sd-server{system_ext}",
        BASE_DIR / "build_ninja" / "bin" / f"sd-server{system_ext}",
        BASE_DIR / "build_ninja" / f"sd-server{system_ext}",
        BASE_DIR / "build_nmake" / "bin" / f"sd-server{system_ext}",
        BASE_DIR / "build_nmake" / f"sd-server{system_ext}",
        BASE_DIR / "build" / "bin" / "Release" / f"sd-server{system_ext}",
        BASE_DIR / "build_linux" / "bin" / f"sd-server{system_ext}",
        BASE_DIR / "build_linux" / f"sd-server{system_ext}",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def ensure_model(model_key: str = "realvisxl-lightning") -> Path:
    """Ensure a diffusion model exists locally; guide download if missing."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Check if any .safetensors or .gguf model already exists in MODELS_DIR
    existing = list(MODELS_DIR.glob("*.safetensors")) + list(MODELS_DIR.glob("*.gguf"))
    if existing:
        log.info(f"Found existing model: {existing[0].name}")
        return existing[0]

    model_info = FAST_MODELS.get(model_key, FAST_MODELS["realvisxl-lightning"])
    target_path = MODELS_DIR / model_info["filename"]
    
    if not target_path.exists():
        log.info(f"Model '{model_info['filename']}' not found in {MODELS_DIR}.")
        log.info(f"Downloading {model_info['description']} from Hugging Face...")
        log.info(f"URL: {model_info['url']}")
        try:
            def _progress(count, block_size, total_size):
                if total_size > 0:
                    pct = int(count * block_size * 100 / total_size)
                    mb = (count * block_size) / (1024 * 1024)
                    tot_mb = total_size / (1024 * 1024)
                    if count % 200 == 0:
                        sys.stdout.write(f"\r[DOWNLOAD] {mb:.1f}MB / {tot_mb:.1f}MB ({pct}%)")
                        sys.stdout.flush()

            urllib.request.urlretrieve(model_info["url"], str(target_path), reporthook=_progress)
            print()
            log.info("Download completed successfully!")
        except Exception as exc:
            log.error(f"Download error: {exc}. Please place a .safetensors or .gguf file into {MODELS_DIR}")
            raise
    return target_path


def start_server(
    host: str = "0.0.0.0",
    port: int = 8085,
    model_path: Optional[Path] = None,
    threads: int = 8,
):
    """Start the sd-server HTTP daemon with OpenAI compatibility."""
    binary = find_sd_server_binary()
    if not binary:
        log.error("sd-server binary not found! Please build it first using build_cuda.bat or build_linux.sh")
        sys.exit(1)

    if model_path is None:
        model_path = ensure_model()

    log.info("=" * 60)
    log.info(" Starting ComputeMesh High-Performance sd.cpp Engine")
    log.info(f" Host OS:   {platform.system()} ({platform.machine()})")
    log.info(f" Binary:    {binary}")
    log.info(f" Model:     {model_path}")
    log.info(f" Endpoint:  http://{host}:{port}/v1/images/generations")
    log.info("=" * 60)

    cmd = [
        str(binary),
        "-m", str(model_path),
        "--listen-ip", str(host),
        "--listen-port", str(port),
        "--threads", str(threads),
    ]

    model_name_lower = model_path.name.lower()
    if "realvis" in model_name_lower or "sdxl" in model_name_lower or "lightning" in model_name_lower:
        cmd.extend([
            "--steps", "6",
            "--cfg-scale", "2.0",
            "--sampling-method", "euler",
            "--type", "q8_0",
            "--vae-tiling",
        ])
    elif "turbo" in model_name_lower:
        cmd.extend(["--steps", "1", "--cfg-scale", "1.0", "--sampling-method", "euler_a"])

    log.info(f"Executing: {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(cmd)
        proc.wait()
    except KeyboardInterrupt:
        log.info("Shutting down ComputeMesh Image Engine...")
        proc.terminate()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ComputeMesh Image Generation Service")
    parser.add_argument("--host", default="0.0.0.0", help="Listen IP (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8085, help="Listen Port (default 8085)")
    parser.add_argument("--model", type=str, default=None, help="Path to model file (.safetensors / .gguf)")
    parser.add_argument("--threads", type=int, default=8, help="Worker CPU threads")
    args = parser.parse_args()

    m_path = Path(args.model) if args.model else None
    start_server(host=args.host, port=args.port, model_path=m_path, threads=args.threads)
