# SPDX-License-Identifier: Apache-2.0
"""
Dictionary, Phonetics, Etymology & Synonym Intelligence Tool.
Fetches verified dictionary definitions, parts of speech, phonetics, and synonyms via the Free Dictionary API and Wiktionary REST fallback.
Supports generic single and multi-word lookups with concurrent execution.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComputeMesh/1.2 (https://mesh.inetconnector.com)"


def _split_dictionary_queries(raw: str) -> List[str]:
    """Splits dictionary queries containing multiple words."""
    cleaned = re.sub(r"^(?:definition\s+(?:von|fuer|für)\s+|was\s+bedeutet\s+|bedeutung\s+von\s+|synonyme\s+(?:fuer|für|zu)\s+|wörterbuch\s+(?:zu|für)\s+|dictionary\s+)", "", raw, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"[\?\.!]$", "", cleaned).strip()
    parts = re.split(r",|\s+und\s+|\s+sowie\s+|\s+and\s+|\s*\+\s*", cleaned, flags=re.IGNORECASE)
    results = []
    for p in parts:
        token = p.strip().strip("'\"`")
        if token and len(token) >= 2:
            results.append(token)
    return results if results else ([raw.strip().strip("'\"`")] if raw.strip() else [])


def _clean_html_tags(text: str) -> str:
    """Strips HTML tags from Wiktionary definition strings."""
    return re.sub(r"<[^>]+>", "", text).strip()


def _fetch_wiktionary_fallback(word_clean: str, timeout: float = 4.0) -> Optional[Dict[str, Any]]:
    """Fetches dictionary definitions from Wiktionary REST API."""
    for lang in ("en", "de"):
        encoded = urllib.parse.quote(word_clean)
        url = f"https://{lang}.wiktionary.org/api/rest_v1/page/definition/{encoded}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if not isinstance(data, dict):
                continue
            sections = data.get(lang, [])
            if not sections:
                # Try other language keys in data
                for k, v in data.items():
                    if isinstance(v, list) and v:
                        sections = v
                        break
            if not sections:
                continue

            formatted_meanings: List[Dict[str, Any]] = []
            summary_lines = [f"**Wörterbuch-Eintrag für '{word_clean}'** (Wiktionary):"]

            for s in sections[:4]:
                part = s.get("partOfSpeech", "allgemein")
                raw_defs = s.get("definitions", [])
                clean_defs = []
                for rd in raw_defs[:3]:
                    df_text = _clean_html_tags(rd.get("definition", ""))
                    if df_text:
                        clean_defs.append(df_text)
                if clean_defs:
                    formatted_meanings.append({
                        "part_of_speech": part,
                        "definitions": clean_defs,
                        "synonyms": [],
                    })
                    summary_lines.append(f"\n*{part}*:")
                    for cd in clean_defs:
                        summary_lines.append(f"- {cd}")

            if formatted_meanings:
                return {
                    "word": word_clean,
                    "phonetic": "",
                    "meanings": formatted_meanings,
                    "summary": "\n".join(summary_lines),
                    "source": "Wiktionary Open Access API",
                }
        except Exception:
            pass
    return None


def _fetch_single_word(search_word: str, timeout: float = 6.0) -> Dict[str, Any]:
    word_clean = search_word.strip().lower()
    encoded = urllib.parse.quote(word_clean)
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{encoded}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=min(timeout, 3.5)) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if data and isinstance(data, list) and len(data) > 0:
            item = data[0]
            phonetic = item.get("phonetic", "")
            meanings = item.get("meanings", [])

            formatted_meanings: List[Dict[str, Any]] = []
            summary_lines = [f"**Wörterbuch-Eintrag für '{word_clean}'** {phonetic}:"]

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
                "word": word_clean,
                "phonetic": phonetic,
                "meanings": formatted_meanings,
                "summary": "\n".join(summary_lines),
                "source": "Free Dictionary Open API",
            }
    except Exception:
        pass

    # Wiktionary fallback
    wiki_res = _fetch_wiktionary_fallback(word_clean, timeout=min(timeout, 3.5))
    if wiki_res:
        return wiki_res

    return {"error": f"Keine Definition für '{word_clean}' im Wörterbuch gefunden.", "word": word_clean}


def lookup_word_definition(
    word: str = "",
    query: str = "",
    timeout: float = 6.0,
) -> Dict[str, Any]:
    """
    Looks up official dictionary definitions, word types (noun, verb, adjective), phonetic pronunciation, and synonyms.
    Supports single or multiple word queries concurrently.
    """
    raw_query = (word or query or "").strip()
    if not raw_query:
        return {"error": "Suchwort für das Wörterbuch darf nicht leer sein (z. B. 'serendipity', 'algorithm', 'intelligence')."}

    words = _split_dictionary_queries(raw_query)
    if len(words) > 1:
        with ThreadPoolExecutor(max_workers=min(len(words), 6)) as pool:
            futures = [pool.submit(_fetch_single_word, w, timeout) for w in words]
            results = [f.result() for f in futures]
        return {
            "multiple_words": True,
            "query": raw_query,
            "words": results,
            "source": "Free Dictionary / Wiktionary",
        }

    return _fetch_single_word(words[0] if words else raw_query, timeout=timeout)


# Backwards-compatible alias
lookup_dictionary = lookup_word_definition
