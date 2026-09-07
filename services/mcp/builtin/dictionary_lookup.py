# SPDX-License-Identifier: Apache-2.0
"""
Dictionary, Phonetics, Etymology & Synonym Intelligence Tool.
Fetches verified dictionary definitions, parts of speech, phonetics, and synonyms via the Free Dictionary API.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, List

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComputeMesh/1.2 (https://mesh.inetconnector.com)"


def lookup_word_definition(
    word: str = "",
    query: str = "",
    timeout: float = 6.0,
) -> Dict[str, Any]:
    """
    Looks up official dictionary definitions, word types (noun, verb, adjective), phonetic pronunciation, and synonyms.
    """
    search_word = (word or query or "").strip().lower()
    if not search_word:
        return {"error": "Suchwort für das Wörterbuch darf nicht leer sein (z. B. 'serendipity', 'algorithm', 'intelligence')."}

    encoded = urllib.parse.quote(search_word)
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{encoded}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if not data or not isinstance(data, list):
            return {"error": f"Keine Definition für '{search_word}' im Wörterbuch gefunden."}

        item = data[0]
        phonetic = item.get("phonetic", "")
        meanings = item.get("meanings", [])

        formatted_meanings: List[Dict[str, Any]] = []
        summary_lines = [f"**Wörterbuch-Eintrag für '{search_word}'** {phonetic}:"]

        for m in meanings:
            part = m.get("partOfSpeech", "allgemein")
            defs = m.get("definitions", [])
            syns = m.get("synonyms", [])

            top_defs: List[str] = []
            for d in defs[:2]:
                defn = d.get("definition", "")
                example = d.get("example")
                if example:
                    top_defs.append(f"{defn} *(Beispiel: \"{example}\")*")
                else:
                    top_defs.append(defn)

            formatted_meanings.append({
                "part_of_speech": part,
                "definitions": top_defs,
                "synonyms": syns[:5],
            })

            summary_lines.append(f"\n*{part}*:")
            for td in top_defs:
                summary_lines.append(f"- {td}")
            if syns:
                summary_lines.append(f"- *Synonyme*: {', '.join(syns[:4])}")

        return {
            "word": search_word,
            "phonetic": phonetic,
            "meanings": formatted_meanings,
            "summary": "\n".join(summary_lines),
            "source": "Free Dictionary Open API",
        }
    except Exception as e:
        return {"error": f"Fehler bei Wörterbuch-Abfrage für '{search_word}': {str(e)}"}


# Backwards-compatible alias
lookup_dictionary = lookup_word_definition
