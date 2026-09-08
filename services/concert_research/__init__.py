"""ComputeMesh Concert Research Engine.

A persistent, first-party concert discovery/indexing service. Semantic work is
performed through ComputeMesh inference only; ordinary web/search sources are
used as data inputs.
"""

from .engine import ConcertResearchEngine
from .models import ResearchRequest

__all__ = ["ConcertResearchEngine", "ResearchRequest"]
