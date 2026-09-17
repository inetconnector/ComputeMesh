# SPDX-License-Identifier: Apache-2.0
"""ComputeMesh High-Performance Built-in Tool for AI Image Generation."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

log = logging.getLogger("computemesh.mcp.generate_image")

STYLE_PROMPTS = {
    "photorealistic": "award-winning professional 8k photograph, authentic fine textures, natural lighting, sharp focus, 85mm dslr, masterpiece, ultra-detailed skin pores and realistic lighting",
    "cinematic": "cinematic 8k, dramatic movie still, atmospheric lighting, anamorphic lens, masterpiece, color graded, blockbuster cinematography",
    "artistic": "beautiful detailed artistic digital painting style, rich vibrant colors, expressive brushwork, masterpiece",
    "oil_painting": "classic master oil painting, rich canvas texture, detailed impasto strokes, Rembrandt lighting, fine art masterpiece",
    "anime": "high-end modern anime aesthetic, Makoto Shinkai style, vibrant colors, stunning detail, 4k digital illustration",
    "cyberpunk": "cyberpunk style, neon lights, volumetric rain fog, holographic reflections, futuristic high-tech aesthetic, 8k",
    "3d_render": "octane 3d render, raytraced subsurface scattering, hyperrealistic CGI, Unreal Engine 5 aesthetic, 8k",
}


def expand_visual_prompt(prompt: str, style: str = "photorealistic") -> str:
    """Expands short or conceptual user prompts into vivid, high-fidelity diffusion prompts (DALL-E 3 / Midjourney style)."""
    p = prompt.strip()
    if not p:
        return p

    # Clean up command prefixes like 'erstelle ein bild von', 'male ein bild aus den...', 'draw', etc.
    p = re.sub(
        r"^(?:(?:generiere|erstelle|zeichne|male|mache|kreiere|generate|create|draw|paint)\s+(?:ein\s+|an?\s+)?(?:[a-zA-ZäöüÄÖÜß\-]+\s+)*(?:bild|foto|gemälde|zeichnung|grafik|artwork|illustration|image|photo|picture)\b\s*(?:von|vom|mit|aus|über|zu|zum|zur|der|des|den|of|with|from|about)?\s*)",
        "",
        p,
        flags=re.IGNORECASE
    ).strip()

    p_lower = p.lower()
    enhancements: list[str] = []

    # Subject-specific visual detailing
    if any(w in p_lower for w in ("raumfahrt", "weltall", "space", "starship", "rakete", "planet", "stern", "galaxy", "mars", "moon")):
        enhancements.append("cinematic wide shot, deep space cosmic background, nebulae dust, volumetric engine exhaust glow, high realism, 8k resolution")
    elif any(w in p_lower for w in ("nachricht", "news", "politik", "wirtschaft", "tagesschau", "finanz", "aktie", "börse", "bitcoin", "crypto")):
        enhancements.append("editorial conceptual composition, symbolic visual narrative, dramatic lighting, sharp depth of field, modern press aesthetics, highly detailed")
    elif any(w in p_lower for w in ("landschaft", "berge", "meer", "ozean", "natur", "wald", "fluss", "sunset", "sonnenuntergang", "landscape")):
        enhancements.append("breathtaking panoramic view, golden hour sunlight, atmospheric volumetric haze, pristine crystal-clear environment details, 8k photography")
    elif any(w in p_lower for w in ("mensch", "porträt", "frau", "mann", "gesicht", "person", "character", "portrait")):
        enhancements.append("fine photographic portrait, natural softbox studio lighting, authentic skin texture and realistic eye reflections, shallow depth of field, 85mm lens")
    elif any(w in p_lower for w in ("stadt", "city", "architektur", "gebäude", "futuristisch", "cyberpunk", "neon")):
        enhancements.append("intricate architectural details, raytraced wet asphalt reflections, volumetric street light glow, ultra-modern dynamic perspective")
    else:
        enhancements.append("masterpiece quality, vibrant lighting, intricate textures, sharp focus, professionally framed composition, 8k")

    style_key = style.lower().strip().replace(" ", "_") if style else "photorealistic"
    matched_style = STYLE_PROMPTS.get(style_key) or STYLE_PROMPTS.get("photorealistic", "")

    parts = [p]
    if enhancements:
        parts.append(", ".join(enhancements))
    if matched_style and matched_style.split(",")[0].lower() not in p_lower:
        parts.append(matched_style)

    return ", ".join(parts)


def _ensure_image_engine_running(timeout: float = 2.0) -> bool:
    try:
        req = urllib.request.Request("http://127.0.0.1:8085/v1/models", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=0.8) as resp:
            if resp.status == 200:
                return True
    except Exception:
        pass

    try:
        repo_root = Path(__file__).resolve().parents[3]
        service_script = repo_root / "runtime" / "sd_cpp" / "image_engine_service.py"
        if service_script.exists():
            subprocess.Popen([sys.executable, str(service_script), "--port", "8085"], cwd=str(repo_root))
            start_t = time.time()
            while time.time() - start_t < timeout:
                try:
                    time.sleep(0.4)
                    req = urllib.request.Request("http://127.0.0.1:8085/v1/models", headers={"Accept": "application/json"})
                    with urllib.request.urlopen(req, timeout=0.6) as resp:
                        if resp.status == 200:
                            return True
                except Exception:
                    continue
    except Exception:
        pass
    return False


def _get_candidate_endpoints() -> list[str]:
    """Resolves local and cluster-wide GPU diffusion endpoints."""
    endpoints = []
    env_backend = os.environ.get("COMPUTEMESH_IMAGE_BACKEND_URL", "").strip()
    if env_backend:
        endpoints.append(env_backend)

    endpoints.append("http://127.0.0.1:8085/v1/images/generations")
    endpoints.append("http://localhost:8085/v1/images/generations")

    # Discover online GPU nodes from gateway telemetry registry
    try:
        from services.gateway.server import NODE_TELEMETRY_REGISTRY
        for node_id, node in list(NODE_TELEMETRY_REGISTRY.items()):
            gpus = node.get("inventory", {}).get("total_gpus", 0) or len(node.get("inventory", {}).get("gpus", []))
            if gpus > 0:
                for cand in node.get("candidate_local_urls", []):
                    base = cand.rstrip("/")
                    endpoints.append(f"{base}/v1/images/generations")
                client_ip = node.get("client_ip")
                if client_ip and client_ip not in ("127.0.0.1", "::1"):
                    endpoints.append(f"http://{client_ip}:8085/v1/images/generations")
                    endpoints.append(f"http://{client_ip}:8080/v1/images/generations")
    except Exception:
        pass

    seen = set()
    return [ep for ep in endpoints if ep and ep not in seen and not seen.add(ep)]


def generate_ai_image(
    prompt: str,
    style: Optional[str] = "photorealistic",
    width: int = 1024,
    height: int = 1024,
    enhance: bool = True,
) -> Dict[str, Any]:
    """Generates a high-resolution AI image from a descriptive prompt using local GPU / ComputeMesh pipeline with cloud fallback.

    Args:
        prompt: The descriptive prompt in German or English (e.g. 'Majestätischer Adler über den Bergen').
        style: Optional style preset ('photorealistic', 'cinematic', 'artistic', 'oil_painting', 'anime', 'cyberpunk', '3d_render').
        width: Image width in pixels (default 1024).
        height: Image height in pixels (default 1024).
        enhance: Whether to apply automated prompt detail enhancement.

    Returns:
        A dictionary containing the generated image URL, markdown embed code, provenance, and metadata.
    """
    clean_prompt = prompt.strip()
    if not clean_prompt:
        return {"error": "Prompt darf nicht leer sein"}

    enriched_prompt = expand_visual_prompt(clean_prompt, style=style or "photorealistic") if enhance else clean_prompt

    _ensure_image_engine_running(timeout=1.5)

    local_endpoints = _get_candidate_endpoints()
    timeout_sec = float(os.environ.get("COMPUTEMESH_IMAGE_TIMEOUT_SECONDS", 60.0))

    provenance_meta = {
        "engine": "ComputeMesh RealVisXL / stable-diffusion.cpp (CUDA)",
        "ai_generated": True,
        "digital_source_type": "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia",
        "legal_notice": "AI-generated synthetic media according to EU AI Act Art. 50",
    }

    for ep in local_endpoints:
        if not ep:
            continue
        try:
            req_data = json.dumps({
                "prompt": enriched_prompt,
                "n": 1,
                "size": f"{width}x{height}",
                "response_format": "b64_json",
            }).encode("utf-8")
            req = urllib.request.Request(
                ep,
                data=req_data,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                method="POST",
            )
            # Use a quick connect timeout if remote, longer for generation
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                if resp.status in (200, 201):
                    res_body = json.loads(resp.read().decode("utf-8"))
                    data_arr = res_body.get("data", [])
                    if data_arr and isinstance(data_arr[0], dict):
                        b64 = data_arr[0].get("b64_json")
                        img_url = data_arr[0].get("url")
                        if b64:
                            data_uri = f"data:image/png;base64,{b64}"
                            return {
                                "status": "success",
                                "source": "local_mesh_gpu",
                                "prompt": clean_prompt,
                                "enriched_prompt": enriched_prompt,
                                "style": style,
                                "image_url": data_uri,
                                "markdown": f"![{clean_prompt}]({data_uri})\n\n[⬇️ **Bild in voller Auflösung herunterladen**]({data_uri})",
                                "width": width,
                                "height": height,
                                "provenance": provenance_meta,
                            }
                        elif img_url:
                            return {
                                "status": "success",
                                "source": "local_mesh_gpu",
                                "prompt": clean_prompt,
                                "enriched_prompt": enriched_prompt,
                                "style": style,
                                "image_url": img_url,
                                "markdown": f"![{clean_prompt}]({img_url})\n\n[⬇️ **Bild in voller Auflösung herunterladen**]({img_url})",
                                "width": width,
                                "height": height,
                                "provenance": provenance_meta,
                            }
        except Exception:
            # Fallback to next endpoint or cloud
            pass

    # 2. Cloud Fallback: Pollinations.ai
    seed = random.randint(100000, 9999999)
    encoded = urllib.parse.quote(enriched_prompt)
    image_url = f"https://image.pollinations.ai/prompt/{encoded}?width={width}&height={height}&seed={seed}&nologo=true&enhance={'true' if enhance else 'false'}"
    markdown = f"![{clean_prompt}]({image_url})\n\n[⬇️ **Bild in voller Auflösung herunterladen**]({image_url})"

    return {
        "status": "success",
        "source": "cloud_fallback",
        "prompt": clean_prompt,
        "enriched_prompt": enriched_prompt,
        "style": style,
        "image_url": image_url,
        "markdown": markdown,
        "width": width,
        "height": height,
        "seed": seed,
        "provenance": {
            **provenance_meta,
            "engine": "ComputeMesh AI Image Pipeline",
        },
    }

