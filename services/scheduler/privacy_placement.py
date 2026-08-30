"""Policy filter for global mesh candidate pools."""
from __future__ import annotations

from typing import Iterable

from services.compliance.mesh_policy import (
    JobRoutingPolicy,
    MeshFeatureFlags,
    ProviderRoutingCapabilities,
    evaluate_mesh_eligibility,
)


def filter_mesh_candidates(
    job: JobRoutingPolicy,
    candidates: Iterable[ProviderRoutingCapabilities],
    *,
    features: MeshFeatureFlags | None = None,
) -> tuple[ProviderRoutingCapabilities, ...]:
    """Return only nodes satisfying the full policy intersection.

    An empty result is terminal for this privacy class: there is no fallback to
    a weaker privacy class.
    """
    return tuple(
        candidate
        for candidate in candidates
        if evaluate_mesh_eligibility(job, candidate, features=features).eligible
    )
