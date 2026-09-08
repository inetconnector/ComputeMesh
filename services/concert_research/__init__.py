"""ComputeMesh Concert Research Engine.

A persistent, first-party concert discovery/indexing service. Semantic work is
performed through ComputeMesh inference only; ordinary web/search sources are
used as data inputs.
"""

# `crawler.py` retains its small reference fetcher for compatibility, but all
# normal package imports install the hardened redirect-validating implementation
# before any ConcertCrawler instance is constructed. Keeping the hardened
# transport separate also makes it independently testable.
from . import crawler as _crawler
from .http_client import HardenedSafeFetcher

_crawler.SafeFetcher = HardenedSafeFetcher

from .engine import ConcertResearchEngine
from .models import ResearchRequest

__all__ = ["ConcertResearchEngine", "ResearchRequest"]
