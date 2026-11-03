"""ComputeMesh Concert Research Engine.

A persistent, first-party concert discovery/indexing service. Semantic work is
performed through ComputeMesh inference only; ordinary web/search sources are
used as data inputs.
"""

# The crawler now uses the redirect-validating fetcher directly, including for
# imports that bypass this package's top-level namespace. No monkeypatching.
from .crawler import SafeFetcher
from .engine import ConcertResearchEngine
from .http_client import HardenedSafeFetcher
from .models import ResearchRequest

__all__ = ["ConcertResearchEngine", "ResearchRequest"]
