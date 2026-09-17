# SPDX-License-Identifier: Apache-2.0
"""
Conversational Context & Deictic Reference Resolver.
Resolves relative pronouns and follow-up references ('da', 'dort', 'der Vorfall', 'zuletzt passiert')
into canonical, grounded entities from the preceding conversation dialogue.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

DEICTIC_PATTERNS = [
    r"\b(?:da|dort|hier|das|es|dies|dieses|jenes|darin|daraus|darüber|darueber|damit)\b",
    r"\b(?:als\s+letztes|als\s+naechstes|als\s+nächstes|zuletzt|neues|neu|passiert|geschehen|los|vorgefallen|passiert\s+ist)\b",
    r"\b(?:der\s+vorfall|das\s+ereignis|der\s+konflikt|die\s+situation|der\s+streit|das\s+thema|die\s+sache|die\s+krise)\b",
]

DEICTIC_RE = re.compile("|".join(DEICTIC_PATTERNS), re.IGNORECASE)


def extract_dominant_topic(messages: List[Dict[str, Any]], max_lookback: int = 4) -> Optional[str]:
    """
    Extracts the most salient topic/entity from recent conversation history.
    """
    if not messages:
        return None

    # Scan previous assistant and user messages in reverse
    for msg in reversed(messages[-max_lookback:]):
        if not isinstance(msg, dict):
            continue
        content = str(msg.get("content") or "").strip()
        if not content or len(content) < 5:
            continue

        # Check for bold entity headers like **Thema** or ### Thema
        m_header = re.search(r"(?:###|##|\*\*)\s*([A-Za-z0-9äöüÄÖÜß\s\-]{3,40})(?:\*\*|:|\n)", content)
        if m_header:
            candidate = m_header.group(1).strip()
            if candidate.lower() not in ("gedankengang", "hinweis", "quelle", "ergebnis", "antwort"):
                return candidate

        # Check for capitalized named entities / topics in assistant text
        m_entity = re.search(r"(?:über|ueber|zu|in|für|fuer|von|betreffend)\s+([A-ZÄÖÜ][a-zA-Z0-9äöüÄÖÜß\s\-]{2,35})(?:[,.\n]|\s+ist|\s+hat|\s+wurde)", content)
        if m_entity:
            candidate = m_entity.group(1).strip()
            if candidate.lower() not in ("diesem", "dieser", "dieses", "einem", "einer", "allen", "weitere"):
                return candidate

        # Check first sentence subject
        first_line = content.split("\n", 1)[0]
        m_first = re.search(r"^[#*\s]*([A-ZÄÖÜ][a-zA-Z0-9äöüÄÖÜß\s\-]{2,35})(?:\s+ist|\s+war|\s+wird|:)", first_line)
        if m_first:
            candidate = m_first.group(1).strip()
            if candidate.lower() not in ("hallo", "guten tag", "antwort", "hinweis"):
                return candidate

    return None


def resolve_contextual_query(
    user_query: str,
    messages: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[str, Optional[str], bool]:
    """
    Resolves conversational follow-up references.
    Returns (resolved_query, dominant_entity, was_resolved).
    """
    cleaned = user_query.strip()
    if not messages or len(messages) <= 1:
        return cleaned, None, False

    # Guard: Do not resolve context on user corrections, negations, or explicit site/portal directives
    if re.search(r"^(?:nein|nicht|falsch|stopp|stop|halt|ich meine|ich meinte|du sollst|schau|guck|sieh|öffne|lies)\b", cleaned, re.IGNORECASE):
        return cleaned, None, False

    if any(w in cleaned.lower() for w in ("taz", "spiegel", "zeit", "tagesschau", "heise", "golem", "faz", "welt", "focus", "sueddeutsche", "seite", "webseite", "website", "homepage", "http://", "https://", ".de", ".com", ".org", ".net")):
        return cleaned, None, False

    has_deictic = bool(DEICTIC_RE.search(cleaned))
    is_short_followup = len(cleaned.split()) <= 7

    if has_deictic or is_short_followup:
        # Exclude the very last message if it's the current user query itself
        history = messages[:-1] if messages and messages[-1].get("content") == user_query else messages
        dominant_topic = extract_dominant_topic(history)
        if dominant_topic:
            if dominant_topic.lower() in cleaned.lower():
                return cleaned, dominant_topic, True

            # Construct enriched, grounded query
            if any(w in cleaned.lower() for w in ("passiert", "letztes", "geschehen", "neu", "aktuell", "stand")):
                resolved = f"{dominant_topic} aktuelle Ereignisse und letzte Entwicklungen"
            elif any(w in cleaned.lower() for w in ("wer", "beteiligt", "akteure", "personen")):
                resolved = f"{dominant_topic} beteiligte Personen und Akteure"
            elif any(w in cleaned.lower() for w in ("warum", "ursache", "grund", "hintergrund")):
                resolved = f"{dominant_topic} Ursachen und Hintergrund"
            elif len(cleaned.split()) <= 4:
                resolved = f"{dominant_topic} {cleaned}"
            else:
                return cleaned, None, False
            return resolved.strip(), dominant_topic, True

    return cleaned, None, False
