# SPDX-License-Identifier: Apache-2.0
"""ComputeMesh Built-in Tool for Document RAG & Knowledge Base Search."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from services.rag.document_parser import extract_text_from_file, parse_document_content
from services.rag.vector_store import get_default_vector_store

log = logging.getLogger("computemesh.mcp.rag_tool")


def search_knowledge_base(
    query: str,
    top_k: int = 4,
    collection: str = "default",
) -> Dict[str, Any]:
    """Searches the indexed document knowledge base for relevant passages, facts, and citations.

    Args:
        query: Search query, question, or keyword string.
        top_k: Number of most relevant passages to return (default 4).
        collection: Vector collection name (default 'default').

    Returns:
        A dictionary with matched chunks, text snippets, relevance scores, and sources.
    """
    clean_q = str(query or "").strip()
    if not clean_q:
        return {"error": "Suchanfrage darf nicht leer sein", "results": []}

    store = get_default_vector_store(collection)
    matches = store.search(clean_q, top_k=top_k)

    if not matches:
        return {
            "query": clean_q,
            "total_matches": 0,
            "results": [],
            "message": f"Keine relevanten Dokumentstellen für '{clean_q}' in der Wissensdatenbank gefunden.",
        }

    formatted_results = []
    for m in matches:
        formatted_results.append({
            "filename": m.get("filename"),
            "score": m.get("score"),
            "chunk_index": m.get("chunk_index"),
            "total_chunks": m.get("total_chunks"),
            "snippet": m.get("text"),
        })

    return {
        "query": clean_q,
        "total_matches": len(formatted_results),
        "results": formatted_results,
    }


def index_document_text(
    text: str,
    filename: str = "document.txt",
    doc_id: Optional[str] = None,
    collection: str = "default",
) -> Dict[str, Any]:
    """Indexes text content into the local vector database for fast semantic retrieval."""
    clean_text = str(text or "").strip()
    if not clean_text:
        return {"error": "Text darf nicht leer sein", "success": False}

    target_id = doc_id or f"doc_{abs(hash(filename + clean_text[:50]))}"
    store = get_default_vector_store(collection)
    return store.add_document(clean_text, doc_id=target_id, filename=filename)


def list_indexed_documents(collection: str = "default") -> Dict[str, Any]:
    """Lists all documents currently indexed in the knowledge base."""
    store = get_default_vector_store(collection)
    docs = store.list_documents()
    return {
        "collection": collection,
        "total_documents": len(docs),
        "documents": docs,
    }
