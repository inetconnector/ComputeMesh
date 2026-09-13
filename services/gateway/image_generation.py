"""Mandatory-safe image generation pipeline for ComputeMesh.

No image backend should be called directly from HTTP handlers. Requests must go
through ImageGenerationService so prompt moderation, output moderation,
provenance metadata and audit-safe reason codes are always applied.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import hashlib
import json
from typing import Any, Protocol

from services.gateway.image_safety import (
    ImageSafetyError,
    ImageSafetyOrchestrator,
    SafetyAction,
    SafetyDecision,
)


class ImageBackend(Protocol):
    def generate(
        self,
        *,
        prompt: str,
        model: str,
        size: str,
        n: int,
        seed: int | None = None,
    ) -> list[tuple[bytes, str]]:
        """Return [(image_bytes, mime_type), ...]."""


@dataclass(frozen=True)
class GeneratedImage:
    mime_type: str
    b64_json: str
    sha256: str
    provenance: dict[str, Any]


@dataclass(frozen=True)
class ImageGenerationResult:
    created: int
    model: str
    images: tuple[GeneratedImage, ...]
    moderation: dict[str, Any]


class ImageGenerationRejected(RuntimeError):
    def __init__(self, decision: SafetyDecision) -> None:
        self.decision = decision
        super().__init__("image generation request rejected by safety policy")


class ImageGenerationService:
    MAX_IMAGES = 4
    ALLOWED_SIZES = {"512x512", "768x768", "1024x1024", "1024x1536", "1536x1024"}

    def __init__(self, *, backend: ImageBackend, safety: ImageSafetyOrchestrator) -> None:
        if backend is None:
            raise ValueError("image backend is required")
        if safety is None:
            raise ValueError("image safety orchestrator is required")
        self.backend = backend
        self.safety = safety

    @staticmethod
    def _decision_payload(decision: SafetyDecision) -> dict[str, Any]:
        return {
            "action": decision.action.value,
            "reason_codes": [f.reason_code for f in decision.findings],
            "categories": [f.category.value for f in decision.findings],
        }

    @staticmethod
    def _provenance(*, model: str, prompt: str, image_bytes: bytes) -> dict[str, Any]:
        # Machine-readable provenance returned with every image. This is kept
        # provider-neutral; deployments can additionally embed C2PA credentials
        # in the image file when a signing implementation is configured.
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return {
            "generated_by_ai": True,
            "generator": "ComputeMesh",
            "model": model,
            "created_at": now,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "asset_sha256": hashlib.sha256(image_bytes).hexdigest(),
            "provenance_version": "computemesh-ai-origin-v1",
        }

    def generate(
        self,
        *,
        prompt: str,
        model: str,
        size: str = "1024x1024",
        n: int = 1,
        seed: int | None = None,
    ) -> ImageGenerationResult:
        clean_prompt = (prompt or "").strip()
        if not clean_prompt:
            raise ValueError("prompt is required")
        if size not in self.ALLOWED_SIZES:
            raise ValueError("unsupported image size")
        if not isinstance(n, int) or n < 1 or n > self.MAX_IMAGES:
            raise ValueError(f"n must be between 1 and {self.MAX_IMAGES}")

        prompt_decision = self.safety.moderate_prompt(clean_prompt)
        # Public endpoint is fail-closed for both BLOCK and REVIEW. A future
        # authenticated human-review workflow can separately resolve REVIEW.
        if prompt_decision.action is not SafetyAction.ALLOW:
            raise ImageGenerationRejected(prompt_decision)

        generated = self.backend.generate(
            prompt=clean_prompt,
            model=model,
            size=size,
            n=n,
            seed=seed,
        )
        if len(generated) != n:
            raise RuntimeError("image backend returned unexpected image count")

        images: list[GeneratedImage] = []
        output_decisions: list[dict[str, Any]] = []
        for image_bytes, mime_type in generated:
            decision = self.safety.moderate_output(image_bytes, mime_type=mime_type)
            output_decisions.append(self._decision_payload(decision))
            if decision.action is not SafetyAction.ALLOW:
                # Do not leak rejected model output to the caller.
                raise ImageGenerationRejected(decision)

            digest = hashlib.sha256(image_bytes).hexdigest()
            images.append(GeneratedImage(
                mime_type=mime_type,
                b64_json=base64.b64encode(image_bytes).decode("ascii"),
                sha256=digest,
                provenance=self._provenance(
                    model=model,
                    prompt=clean_prompt,
                    image_bytes=image_bytes,
                ),
            ))

        return ImageGenerationResult(
            created=int(datetime.now(timezone.utc).timestamp()),
            model=model,
            images=tuple(images),
            moderation={
                "prompt": self._decision_payload(prompt_decision),
                "outputs": output_decisions,
                "public_policy": "fail_closed",
            },
        )


def openai_images_response(result: ImageGenerationResult) -> dict[str, Any]:
    """Serialize to an OpenAI-style image-generation response."""
    return {
        "created": result.created,
        "model": result.model,
        "data": [
            {
                "b64_json": image.b64_json,
                "mime_type": image.mime_type,
                "sha256": image.sha256,
                "provenance": image.provenance,
            }
            for image in result.images
        ],
        "moderation": result.moderation,
    }


def rejected_response(exc: ImageGenerationRejected) -> tuple[dict[str, Any], int]:
    decision = exc.decision
    return (
        {
            "error": {
                "message": "The image request cannot be generated under the ComputeMesh public safety policy.",
                "type": "image_safety_policy_violation",
                "code": "image_safety_rejected",
                "reason_codes": [f.reason_code for f in decision.findings],
                "categories": [f.category.value for f in decision.findings],
            }
        },
        400,
    )
