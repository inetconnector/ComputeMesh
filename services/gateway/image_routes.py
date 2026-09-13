"""OpenAI-compatible image generation route wrapper.

The route is disabled by default and refuses to start unless a generation
backend plus prompt and output moderation services are configured. This avoids
accidentally exposing an unmoderated image model.
"""
from __future__ import annotations

from http import HTTPStatus
import base64
import json
import os
from typing import Any
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

from services.gateway.image_generation import (
    ImageGenerationRejected,
    ImageGenerationService,
    openai_images_response,
    rejected_response,
)
from services.gateway.image_safety import (
    ClassifierResult,
    ImageSafetyError,
    ImageSafetyOrchestrator,
    SafetyAction,
)


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _post_json(url: str, payload: dict[str, Any], *, api_key: str = "", timeout: float = 60.0) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise RuntimeError("invalid configured service URL")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    req = urllib_request.Request(url, data=raw, headers=headers, method="POST")
    try:
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(25 * 1024 * 1024)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError("configured image service unavailable") from exc
    try:
        obj = json.loads(body.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("configured image service returned malformed JSON") from exc
    if not isinstance(obj, dict):
        raise RuntimeError("configured image service returned invalid response")
    return obj


def _parse_action(value: str) -> SafetyAction:
    cleaned = str(value or "").strip().lower()
    if cleaned == "allow":
        return SafetyAction.ALLOW
    if cleaned == "review":
        return SafetyAction.REVIEW
    return SafetyAction.BLOCK


class HttpModerationClient:
    """Adapter for a dedicated multilingual/multimodal moderation service.

    Expected response fields:
      action: allow|review|block
      categories: [string, ...]
      confidence: number|null
      subject_age_min / subject_age_max: integer|null
      real_person_likelihood: number|null
      sexual_content_likelihood: number|null
    """

    def __init__(self, *, url: str, api_key: str = "") -> None:
        self.url = url
        self.api_key = api_key

    @staticmethod
    def _normalize(data: dict[str, Any]) -> ClassifierResult:
        categories = data.get("categories") or []
        if not isinstance(categories, list):
            categories = []
        return ClassifierResult(
            action=_parse_action(data.get("action", "block")),
            categories=tuple(str(x) for x in categories[:64]),
            confidence=float(data["confidence"]) if data.get("confidence") is not None else None,
            subject_age_min=int(data["subject_age_min"]) if data.get("subject_age_min") is not None else None,
            subject_age_max=int(data["subject_age_max"]) if data.get("subject_age_max") is not None else None,
            real_person_likelihood=float(data["real_person_likelihood"]) if data.get("real_person_likelihood") is not None else None,
            sexual_content_likelihood=float(data["sexual_content_likelihood"]) if data.get("sexual_content_likelihood") is not None else None,
        )

    def moderate_prompt(self, prompt: str) -> ClassifierResult:
        data = _post_json(
            self.url,
            {"input_type": "text", "task": "image_generation_prompt", "text": prompt},
            api_key=self.api_key,
            timeout=20.0,
        )
        return self._normalize(data)

    def moderate_output(self, image_bytes: bytes, *, mime_type: str) -> ClassifierResult:
        data = _post_json(
            self.url,
            {
                "input_type": "image",
                "task": "image_generation_output",
                "mime_type": mime_type,
                "image_b64": base64.b64encode(image_bytes).decode("ascii"),
            },
            api_key=self.api_key,
            timeout=30.0,
        )
        return self._normalize(data)


class OpenAICompatibleImageBackend:
    """Minimal backend adapter requiring base64 responses (no remote URL fetch)."""

    def __init__(self, *, url: str, api_key: str = "") -> None:
        self.url = url
        self.api_key = api_key

    def generate(self, *, prompt: str, model: str, size: str, n: int, seed: int | None = None):
        payload: dict[str, Any] = {
            "prompt": prompt,
            "model": model,
            "size": size,
            "n": n,
            "response_format": "b64_json",
        }
        if seed is not None:
            payload["seed"] = seed
        data = _post_json(self.url, payload, api_key=self.api_key, timeout=180.0)
        items = data.get("data")
        if not isinstance(items, list):
            raise RuntimeError("image backend response missing data array")
        result: list[tuple[bytes, str]] = []
        for item in items:
            if not isinstance(item, dict) or not item.get("b64_json"):
                # Deliberately refuse URL downloads to avoid SSRF and moderation bypass.
                raise RuntimeError("image backend must return b64_json")
            try:
                raw = base64.b64decode(str(item["b64_json"]), validate=True)
            except Exception as exc:
                raise RuntimeError("invalid base64 image response") from exc
            if not raw or len(raw) > 20 * 1024 * 1024:
                raise RuntimeError("invalid generated image size")
            mime_type = str(item.get("mime_type") or "image/png")
            if mime_type not in {"image/png", "image/jpeg", "image/webp"}:
                raise RuntimeError("unsupported generated image MIME type")
            result.append((raw, mime_type))
        return result


def build_image_generation_service_from_env() -> ImageGenerationService:
    if not _truthy("COMPUTEMESH_IMAGE_GENERATION_ENABLED"):
        raise RuntimeError("image generation is disabled")

    backend_url = os.environ.get("COMPUTEMESH_IMAGE_BACKEND_URL", "").strip()
    moderation_url = os.environ.get("COMPUTEMESH_IMAGE_MODERATION_URL", "").strip()
    if not backend_url or not moderation_url:
        raise RuntimeError("image generation requires backend and moderation URLs")

    moderation = HttpModerationClient(
        url=moderation_url,
        api_key=os.environ.get("COMPUTEMESH_IMAGE_MODERATION_API_KEY", "").strip(),
    )
    safety = ImageSafetyOrchestrator(
        prompt_classifier=moderation.moderate_prompt,
        output_classifier=moderation.moderate_output,
    )
    backend = OpenAICompatibleImageBackend(
        url=backend_url,
        api_key=os.environ.get("COMPUTEMESH_IMAGE_BACKEND_API_KEY", "").strip(),
    )
    return ImageGenerationService(backend=backend, safety=safety)


def install_image_generation_routes(base_handler_cls):
    """Return a handler subclass adding /v1/images/generations.

    Other requests are delegated unchanged to the existing ComputeMesh handler.
    """

    class ImageGenerationGatewayHandler(base_handler_cls):
        _image_service = None
        _image_service_error = None

        @classmethod
        def _get_image_service(cls):
            if cls._image_service is not None:
                return cls._image_service
            if cls._image_service_error is not None:
                raise cls._image_service_error
            try:
                cls._image_service = build_image_generation_service_from_env()
                return cls._image_service
            except Exception as exc:
                cls._image_service_error = exc
                raise

        def do_POST(self):
            clean_path = urlparse(self.path).path.rstrip("/")
            if clean_path not in {"/v1/images/generations", "/api/v1/images/generations"}:
                return super().do_POST()

            if not self._check_rate_limit():
                return

            auth = self.auth_manager.authenticate_request(
                self.headers,
                getattr(self, "client_address", None),
                allow_teaser=False,
            )
            if not auth.is_authenticated:
                self._send_error_response(
                    auth.error_message or "Valid API key required for image generation",
                    "authentication_error",
                    auth.status_code or HTTPStatus.UNAUTHORIZED,
                )
                return

            length_header = self.headers.get("Content-Length", "")
            try:
                length = int(length_header)
            except Exception:
                self._send_error_response("Valid Content-Length required", "invalid_request_error", HTTPStatus.BAD_REQUEST)
                return
            if length < 2 or length > 256 * 1024:
                self._send_error_response("Invalid image request payload size", "invalid_request_error", HTTPStatus.BAD_REQUEST)
                return

            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                self._send_error_response("Malformed JSON request body", "invalid_request_error", HTTPStatus.BAD_REQUEST)
                return

            prompt = str(body.get("prompt") or "").strip()
            model = str(body.get("model") or os.environ.get("COMPUTEMESH_IMAGE_DEFAULT_MODEL", "")).strip()
            size = str(body.get("size") or "1024x1024").strip()
            n = body.get("n", 1)
            seed = body.get("seed")
            if not model:
                self._send_error_response("Image model is required", "invalid_request_error", HTTPStatus.BAD_REQUEST)
                return

            try:
                service = type(self)._get_image_service()
            except Exception:
                self._send_error_response(
                    "Image generation is not safely configured on this gateway",
                    "service_unavailable",
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
                return

            try:
                result = service.generate(
                    prompt=prompt,
                    model=model,
                    size=size,
                    n=int(n),
                    seed=int(seed) if seed is not None else None,
                )
            except ImageGenerationRejected as exc:
                payload, status = rejected_response(exc)
                self._send_json(payload, HTTPStatus(status))
                return
            except ImageSafetyError:
                self._send_error_response(
                    "Image moderation is temporarily unavailable",
                    "service_unavailable",
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
                return
            except ValueError as exc:
                self._send_error_response(str(exc), "invalid_request_error", HTTPStatus.BAD_REQUEST)
                return
            except Exception:
                self._send_error_response(
                    "Image generation failed",
                    "image_generation_error",
                    HTTPStatus.BAD_GATEWAY,
                )
                return

            self._send_json(
                openai_images_response(result),
                HTTPStatus.OK,
                extra_headers={
                    "X-ComputeMesh-AI-Generated": "true",
                    "X-ComputeMesh-Provenance": "computemesh-ai-origin-v1",
                    "Cache-Control": "no-store",
                },
            )

    ImageGenerationGatewayHandler.__name__ = f"ImageGeneration{base_handler_cls.__name__}"
    return ImageGenerationGatewayHandler
