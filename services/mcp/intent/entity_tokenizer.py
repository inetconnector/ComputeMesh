# SPDX-License-Identifier: Apache-2.0
"""Multi-entity tokenization and normalization utilities for intent routing."""

from __future__ import annotations

import re
from typing import List, Optional, Set

DEFAULT_STOPWORDS: Set[str] = {
    "bitte", "jetzt", "aktuell", "gerade", "heute", "morgen", "mal", "zeige", "mir",
    "gib", "und", "sowie", "auch", "in", "um", "ab", "von", "nach", "für", "der", "die", "das",
    "please", "now", "current", "today", "show", "me", "and", "as", "well", "for"
}

PUNCTUATION_CHARS = ".,;:!?\"'`()[]{}"


def split_multi_entities(raw_query: str) -> List[str]:
    """Splits multi-entity query strings by commas, conjunctions ('und', 'sowie', 'and', '+', '&')."""
    if not raw_query:
        return []
    # Replace conjunctions with commas
    normalized = re.sub(r"\s+(?:und|sowie|and|&|\+)\s+", ",", raw_query, flags=re.IGNORECASE)
    parts = [p.strip() for p in normalized.split(",") if p.strip()]
    return parts


def clean_entity_token(token: str, stopwords: Optional[Set[str]] = None) -> str:
    """Removes filler words and punctuation from an entity token."""
    if not token:
        return ""
    stops = stopwords or DEFAULT_STOPWORDS
    cleaned = token.strip().strip(PUNCTUATION_CHARS)
    words = [w for w in cleaned.split() if w.lower() not in stops]
    return " ".join(words) if words else cleaned
