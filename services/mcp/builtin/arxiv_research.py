# SPDX-License-Identifier: Apache-2.0
"""
arXiv Scientific Paper & Academic Research Tool.
Searches and retrieves verified scientific papers, preprints, abstracts, and citations from arXiv.org.
"""

from __future__ import annotations

import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComputeMesh/1.2 ResearchAgent"


def search_arxiv_papers(
    query: str = "",
    topic: str = "",
    author: str = "",
    category: str = "",
    max_results: int = 5,
    timeout: float = 8.0,
) -> Dict[str, Any]:
    """
    Searches arXiv for scientific research papers, academic studies, preprints, authors, and abstracts.
    """
    search_q = (query or topic or "").strip()
    if not search_q and not author and not category:
        return {"error": "Suchbegriff, Thema oder Autor für arXiv darf nicht leer sein (z. B. 'mixture of experts', 'deepseek', 'quantum error correction')."}

    # Build search query
    query_parts: List[str] = []
    if search_q:
        query_parts.append(f"all:{search_q}")
    if author:
        query_parts.append(f"au:{author}")
    if category:
        query_parts.append(f"cat:{category}")

    full_query = " AND ".join(query_parts)
    encoded_query = urllib.parse.quote(full_query)
    limit = max(1, min(int(max_results), 10))

    url = f"https://export.arxiv.org/api/query?search_query={encoded_query}&start=0&max_results={limit}&sortBy=submittedDate&sortOrder=descending"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/atom+xml"})

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            xml_data = resp.read()

        root = ET.fromstring(xml_data)
        ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

        entries = root.findall("atom:entry", ns)
        papers: List[Dict[str, Any]] = []

        for entry in entries:
            title_elem = entry.find("atom:title", ns)
            summary_elem = entry.find("atom:summary", ns)
            published_elem = entry.find("atom:published", ns)
            id_elem = entry.find("atom:id", ns)

            title = " ".join(title_elem.text.split()) if title_elem is not None and title_elem.text else "Ohne Titel"
            summary = " ".join(summary_elem.text.split()) if summary_elem is not None and summary_elem.text else ""
            published = published_elem.text[:10] if published_elem is not None and published_elem.text else ""
            arxiv_url = id_elem.text.strip() if id_elem is not None and id_elem.text else ""
            pdf_url = arxiv_url.replace("/abs/", "/pdf/") + ".pdf" if "/abs/" in arxiv_url else arxiv_url

            authors: List[str] = []
            for a in entry.findall("atom:author", ns):
                name_elem = a.find("atom:name", ns)
                if name_elem is not None and name_elem.text:
                    authors.append(name_elem.text.strip())

            papers.append({
                "title": title,
                "authors": authors,
                "published_date": published,
                "abstract": summary[:600] + ("..." if len(summary) > 600 else ""),
                "arxiv_url": arxiv_url,
                "pdf_url": pdf_url,
            })

        if not papers:
            return {
                "query": search_q,
                "papers_found": 0,
                "message": f"Keine wissenschaftlichen Paper auf arXiv für '{search_q}' gefunden.",
            }

        return {
            "query": search_q,
            "papers_found": len(papers),
            "papers": papers,
            "source": "arXiv.org Open Access API",
        }
    except Exception as e:
        return {"error": f"Fehler bei arXiv-Suche nach '{search_q}': {str(e)}"}


# Backwards-compatible alias
lookup_academic_papers = search_arxiv_papers
