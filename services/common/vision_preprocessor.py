"""ComputeMesh Vision Preprocessor & Image Analysis Optimization Pipeline.

Provides industrial-grade image preprocessing for multimodal Vision AI models
(e.g., Qwen2-VL, LLaVA, LLaMA-Vision, GPT-4o-compatible backends).

Features:
- Automatic image format ingestion (Data URIs, Base64, Raw Bytes, Remote URLs)
- EXIF orientation auto-rotation
- Smart dimension optimization (Lanczos scaling preserving aspect ratio)
- Patch grid & dynamic vision token estimation for ledger metering
- Color space normalization (RGBA/CMYK/Palette -> RGB)
- Multimodal payload normalization for OpenAI and Ollama formats
"""
from __future__ import annotations

import base64
import io
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageOps
    _HAS_PIL = True
except ImportError:  # pragma: no cover
    _HAS_PIL = False


# Optimal image dimension constants matching SOTA vision model patch grids
DEFAULT_MAX_EDGE: int = 1344
DEFAULT_MIN_EDGE: int = 28
DEFAULT_JPEG_QUALITY: int = 88
DEFAULT_PATCH_SIZE: int = 28
DEFAULT_PATCH_OVERHEAD: int = 32
MAX_IMAGE_DOWNLOAD_BYTES: int = 20 * 1024 * 1024  # 20 MB max payload
ALLOWED_MIME_TYPES: tuple[str, ...] = (
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/bmp",
    "image/tiff",
)


class VisionPreprocessingError(ValueError):
    """Raised when an image payload cannot be parsed, downloaded, or preprocessed."""


@dataclass(frozen=True)
class ProcessedImage:
    """Represents a normalized, optimized image ready for vision model inference."""
    data_base64: str
    mime_type: str
    width: int
    height: int
    original_width: int
    original_height: int
    original_format: str
    estimated_tokens: int

    @property
    def data_uri(self) -> str:
        """Returns standard Data URI format (e.g. data:image/jpeg;base64,...)."""
        return f"data:{self.mime_type};base64,{self.data_base64}"

    @property
    def aspect_ratio(self) -> float:
        """Returns aspect ratio (width / height)."""
        return round(self.width / max(1, self.height), 4)


class VisionPreprocessor:
    """High-performance image preprocessor for multimodal vision pipelines."""

    def __init__(
        self,
        *,
        max_edge: int = DEFAULT_MAX_EDGE,
        min_edge: int = DEFAULT_MIN_EDGE,
        jpeg_quality: int = DEFAULT_JPEG_QUALITY,
        patch_size: int = DEFAULT_PATCH_SIZE,
        patch_overhead_tokens: int = DEFAULT_PATCH_OVERHEAD,
    ) -> None:
        self._has_pil = _HAS_PIL
        self.max_edge = max(64, min(int(max_edge), 4096))
        self.min_edge = max(14, min(int(min_edge), 512))
        self.jpeg_quality = max(50, min(int(jpeg_quality), 100))
        self.patch_size = max(7, min(int(patch_size), 64))
        self.patch_overhead_tokens = max(0, int(patch_overhead_tokens))

    def _load_raw_bytes(self, raw_input: str | bytes | Path) -> bytes:
        """Decodes raw input from Data URI, base64, bytes, or HTTP(S) URL."""
        if isinstance(raw_input, bytes):
            if len(raw_input) > MAX_IMAGE_DOWNLOAD_BYTES:
                raise VisionPreprocessingError(f"Image payload exceeds {MAX_IMAGE_DOWNLOAD_BYTES} bytes")
            return raw_input

        if isinstance(raw_input, Path):
            if not raw_input.exists():
                raise VisionPreprocessingError(f"Image file not found: {raw_input}")
            data = raw_input.read_bytes()
            if len(data) > MAX_IMAGE_DOWNLOAD_BYTES:
                raise VisionPreprocessingError(f"Image file exceeds {MAX_IMAGE_DOWNLOAD_BYTES} bytes")
            return data

        if not isinstance(raw_input, str):
            raise VisionPreprocessingError(f"Unsupported image input type: {type(raw_input)}")

        raw_str = raw_input.strip()
        if not raw_str:
            raise VisionPreprocessingError("Empty image input string")

        # 1. Data URI scheme: data:image/jpeg;base64,<data>
        if raw_str.startswith("data:"):
            match = re.match(r"^data:(image\/[a-zA-Z0-9.+_-]+);base64,(.+)$", raw_str, re.DOTALL | re.IGNORECASE)
            if not match:
                raise VisionPreprocessingError("Invalid data URI scheme for image")
            b64_part = match.group(2).strip()
            try:
                decoded = base64.b64decode(b64_part, validate=True)
                if len(decoded) > MAX_IMAGE_DOWNLOAD_BYTES:
                    raise VisionPreprocessingError("Decoded data URI image exceeds size limit")
                return decoded
            except Exception as exc:
                raise VisionPreprocessingError(f"Failed to decode base64 from data URI: {exc}") from exc

        # 2. Remote HTTP / HTTPS URL
        if raw_str.startswith(("http://", "https://")):
            parsed = urllib.parse.urlparse(raw_str)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise VisionPreprocessingError(f"Invalid image URL: {raw_str}")
            req = urllib.request.Request(
                raw_str,
                headers={"User-Agent": "ComputeMesh-Vision-Engine/1.0", "Accept": "image/*"},
            )
            try:
                with urllib.request.urlopen(req, timeout=10.0) as resp:
                    content_type = resp.headers.get("Content-Type", "").lower()
                    if content_type and not any(ct in content_type for ct in ALLOWED_MIME_TYPES) and "application/octet-stream" not in content_type:
                        raise VisionPreprocessingError(f"Remote URL returned non-image Content-Type: {content_type}")
                    data = resp.read(MAX_IMAGE_DOWNLOAD_BYTES + 1)
                    if len(data) > MAX_IMAGE_DOWNLOAD_BYTES:
                        raise VisionPreprocessingError("Remote image exceeded maximum allowed size")
                    return data
            except Exception as exc:
                if isinstance(exc, VisionPreprocessingError):
                    raise
                raise VisionPreprocessingError(f"Failed to fetch remote image from {raw_str}: {exc}") from exc

        # 3. Raw Base64 string
        # Clean any whitespace or newlines
        clean_b64 = re.sub(r"\s+", "", raw_str)
        try:
            decoded = base64.b64decode(clean_b64, validate=True)
            if len(decoded) > MAX_IMAGE_DOWNLOAD_BYTES:
                raise VisionPreprocessingError("Decoded base64 image exceeds size limit")
            return decoded
        except Exception as exc:
            raise VisionPreprocessingError(f"Invalid base64 image encoding: {exc}") from exc

    def calculate_vision_tokens(self, width: int, height: int) -> int:
        """Estimates vision model token consumption based on patch grid geometry."""
        grid_w = max(1, math.ceil(width / self.patch_size))
        grid_h = max(1, math.ceil(height / self.patch_size))
        patches = grid_w * grid_h
        return patches + self.patch_overhead_tokens

    def process_image(
        self,
        raw_input: str | bytes | Path,
        *,
        max_edge: int | None = None,
        min_edge: int | None = None,
    ) -> ProcessedImage:
        """Loads, rotates, normalizes color space, resizes, and encodes an image."""
        if not self._has_pil:
            raise VisionPreprocessingError("Pillow (PIL) is required to process and resize images.")

        raw_bytes = self._load_raw_bytes(raw_input)
        target_max_edge = max_edge if max_edge is not None else self.max_edge
        target_min_edge = min_edge if min_edge is not None else self.min_edge

        try:
            img = Image.open(io.BytesIO(raw_bytes))
            orig_format = (img.format or "JPEG").upper()
            orig_w, orig_h = img.size
        except Exception as exc:
            raise VisionPreprocessingError(f"Invalid or corrupted image format: {exc}") from exc

        # 1. EXIF orientation correction
        try:
            img = ImageOps.exif_transpose(img)
        except (AttributeError, KeyError, IndexError, ValueError, OSError):
            pass  # Non-fatal if EXIF is missing or malformed

        cur_w, cur_h = img.size

        # 2. Color space normalization to standard RGB
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            # Create RGB image with white background to blend transparency cleanly
            img_rgba = img.convert("RGBA")
            background = Image.new("RGB", img_rgba.size, (255, 255, 255))
            background.paste(img_rgba, mask=img_rgba.split()[3])  # 3 is the alpha channel
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # 3. Smart Aspect-Ratio Preserving Resizing
        scale = 1.0
        if cur_w > target_max_edge or cur_h > target_max_edge:
            scale = min(target_max_edge / cur_w, target_max_edge / cur_h)
        elif cur_w < target_min_edge and cur_h < target_min_edge:
            scale = max(target_min_edge / cur_w, target_min_edge / cur_h)

        if scale != 1.0:
            new_w = max(target_min_edge, round(cur_w * scale))
            new_h = max(target_min_edge, round(cur_h * scale))
            # Clamp to max_edge
            new_w = min(new_w, target_max_edge)
            new_h = min(new_h, target_max_edge)
            resample_filter = getattr(Image, "Resampling", Image).LANCZOS
            img = img.resize((new_w, new_h), resample=resample_filter)
            final_w, final_h = new_w, new_h
        else:
            final_w, final_h = cur_w, cur_h

        # 4. High-Quality Output Compression & Base64 Encoding
        out_buf = io.BytesIO()
        img.save(out_buf, format="JPEG", quality=self.jpeg_quality, optimize=True)
        processed_bytes = out_buf.getvalue()
        b64_encoded = base64.b64encode(processed_bytes).decode("ascii")

        tokens = self.calculate_vision_tokens(final_w, final_h)

        return ProcessedImage(
            data_base64=b64_encoded,
            mime_type="image/jpeg",
            width=final_w,
            height=final_h,
            original_width=orig_w,
            original_height=orig_h,
            original_format=orig_format,
            estimated_tokens=tokens,
        )

    def extract_and_preprocess_multimodal_content(
        self,
        content_or_images: Any,
    ) -> tuple[str, list[ProcessedImage]]:
        """Extracts text and preprocessed images from OpenAI or Ollama payload structures."""
        text_parts: list[str] = []
        images: list[ProcessedImage] = []

        if isinstance(content_or_images, str):
            text_parts.append(content_or_images)
            return "".join(text_parts), images

        if isinstance(content_or_images, list):
            for part in content_or_images:
                if isinstance(part, str):
                    text_parts.append(part)
                elif isinstance(part, dict):
                    part_type = str(part.get("type", "")).lower()
                    if part_type == "text" or "text" in part:
                        text_parts.append(str(part.get("text", "")))
                    elif part_type == "image_url" or "image_url" in part:
                        img_info = part.get("image_url", {})
                        if isinstance(img_info, dict):
                            url_val = img_info.get("url", "")
                        else:
                            url_val = str(img_info)
                        if url_val:
                            processed = self.process_image(url_val)
                            images.append(processed)
                    elif part_type == "image" and "image" in part:
                        img_val = part.get("image", "")
                        if img_val:
                            processed = self.process_image(img_val)
                            images.append(processed)

        return " ".join(tp.strip() for tp in text_parts if tp.strip()), images

    def normalize_multimodal_messages(
        self,
        messages: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int]:
        """Normalizes messages containing text and/or images.

        Returns: (normalized_messages, total_estimated_prompt_tokens)
        """
        normalized_messages: list[dict[str, Any]] = []
        total_vision_tokens = 0
        total_text_tokens = 0

        for raw_msg in messages:
            if not isinstance(raw_msg, dict):
                continue

            role = str(raw_msg.get("role", "user")).strip() or "user"
            raw_content = raw_msg.get("content", "")
            msg_images: list[str] = []
            processed_img_objs: list[ProcessedImage] = []

            # 1. Check for Ollama-style 'images' array
            ollama_images = raw_msg.get("images")
            if isinstance(ollama_images, list):
                for img_item in ollama_images:
                    if img_item:
                        try:
                            proc = self.process_image(img_item)
                            msg_images.append(proc.data_base64)
                            processed_img_objs.append(proc)
                            total_vision_tokens += proc.estimated_tokens
                        except VisionPreprocessingError:
                            # Forward raw base64 if preprocessor fails
                            msg_images.append(str(img_item))
                            total_vision_tokens += 576

            # 2. Check for OpenAI-style multimodal 'content' list or plain string
            if isinstance(raw_content, list):
                text_content, openai_images = self.extract_and_preprocess_multimodal_content(raw_content)
                for proc in openai_images:
                    msg_images.append(proc.data_base64)
                    processed_img_objs.append(proc)
                    total_vision_tokens += proc.estimated_tokens
            else:
                text_content = str(raw_content)

            # Estimate text tokens
            words = text_content.split()
            text_tokens = max(len(words) * 2, len(text_content) // 4) if text_content else 0
            total_text_tokens += text_tokens

            # Format normalized output message
            norm_msg: dict[str, Any] = {
                "role": role,
                "content": text_content,
            }
            if msg_images:
                norm_msg["images"] = msg_images
                norm_msg["_processed_images"] = [
                    {
                        "estimated_tokens": p.estimated_tokens,
                        "width": p.width,
                        "height": p.height,
                        "mime_type": p.mime_type,
                    }
                    for p in processed_img_objs
                ]

            normalized_messages.append(norm_msg)

        total_prompt_tokens = max(16, total_text_tokens + total_vision_tokens)
        return normalized_messages, total_prompt_tokens


# Global default preprocessor singleton
_DEFAULT_VISION_PREPROCESSOR: VisionPreprocessor | None = None


def get_vision_preprocessor() -> VisionPreprocessor:
    """Returns the shared VisionPreprocessor instance."""
    global _DEFAULT_VISION_PREPROCESSOR
    if _DEFAULT_VISION_PREPROCESSOR is None:
        _DEFAULT_VISION_PREPROCESSOR = VisionPreprocessor()
    return _DEFAULT_VISION_PREPROCESSOR
