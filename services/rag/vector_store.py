# SPDX-License-Identifier: Apache-2.0
"""Persistent Vector Database and Hybrid Search Engine for ComputeMesh RAG."""

from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from .chunker import DocumentChunk, chunk_text
from .embeddings import cosine_similarity, get_text_embedding

log = logging.getLogger("computemesh.rag.vector_store")

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "vector_store"


class SearchResult(dict):
    """Dictionary subclass providing both attribute and key access for search results."""

    def __getattr__(self, name: str) -> Any:
        if name in self:
            return self[name]
        if name == "document_id":
            return self.get("doc_id")
        raise AttributeError(f"'SearchResult' object has no attribute '{name}'")

    @property
    def document_id(self) -> str:
        return self.get("doc_id", "")


class VectorStore:
    """Thread-safe persistent vector database with dense cosine search and BM25 hybrid ranking."""

    def __init__(
        self,
        collection_name: str = "default",
        persist_dir: Optional[Path | str] = None,
        storage_dir: Optional[Path | str] = None,
    ):
        self.collection_name = collection_name
        target_dir = storage_dir or persist_dir or DATA_DIR
        self.persist_dir = Path(target_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.persist_file = self.persist_dir / f"{collection_name}.json"
        self._lock = threading.RLock()
        self._chunks: Dict[str, Dict[str, Any]] = {}
        self._load()


    def _load(self) -> None:
        with self._lock:
            if self.persist_file.exists():
                try:
                    with open(self.persist_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        self._chunks = data.get("chunks", {})
                    log.info(f"Loaded {len(self._chunks)} vector chunks for collection '{self.collection_name}'")
                except Exception as exc:
                    log.warning(f"Error loading vector store '{self.collection_name}': {exc}")
                    self._chunks = {}
            else:
                self._chunks = {}

    def _save(self) -> None:
        with self._lock:
            try:
                temp_file = self.persist_dir / f"{self.collection_name}.tmp"
                payload = {
                    "collection": self.collection_name,
                    "updated_at": int(time.time()),
                    "total_chunks": len(self._chunks),
                    "chunks": self._chunks,
                }
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False)
                if temp_file.exists():
                    temp_file.replace(self.persist_file)
            except Exception as exc:
                log.error(f"Error saving vector store '{self.collection_name}': {exc}")

    def add_document(
        self,
        text: str,
        doc_id: str,
        filename: str = "document.txt",
        metadata: Optional[Dict[str, Any]] = None,
        chunk_size: int = 800,
        chunk_overlap: int = 150,
    ) -> Dict[str, Any]:
        """Chunks, embeds, and stores a document in the vector database."""
        clean_text = str(text or "").strip()
        if not clean_text:
            return {"error": "Dokumententext darf nicht leer sein", "chunks_added": 0}

        meta = dict(metadata or {})
        meta["filename"] = filename
        meta["doc_id"] = doc_id
        meta["added_at"] = int(time.time())

        chunks = chunk_text(clean_text, doc_id=doc_id, chunk_size=chunk_size, chunk_overlap=chunk_overlap, metadata=meta)
        if not chunks:
            return {"error": "Keine Chunks aus Dokument extrahiert", "chunks_added": 0}

        with self._lock:
            # Remove any existing chunks for this doc_id
            keys_to_remove = [k for k, v in self._chunks.items() if v.get("doc_id") == doc_id]
            for k in keys_to_remove:
                del self._chunks[k]

            # Embed and insert new chunks
            for ch in chunks:
                vec = get_text_embedding(ch.text)
                self._chunks[ch.chunk_id] = {
                    "chunk_id": ch.chunk_id,
                    "doc_id": ch.doc_id,
                    "text": ch.text,
                    "chunk_index": ch.chunk_index,
                    "total_chunks": ch.total_chunks,
                    "metadata": ch.metadata,
                    "vector": vec,
                }
            self._save()

        return {
            "success": True,
            "doc_id": doc_id,
            "filename": filename,
            "total_chunks": len(chunks),
            "char_count": len(clean_text),
            "message": f"Dokument '{filename}' erfolgreich mit {len(chunks)} Vektor-Chunks indexiert.",
        }

    def index_text(
        self,
        document_id: str,
        text: str,
        filename: str = "document.txt",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Convenience alias for add_document."""
        return self.add_document(text=text, doc_id=document_id, filename=filename, metadata=metadata)


    def search(
        self,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.05,
        filter_doc_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Executes dense vector search with BM25 keyword boosting across stored chunks."""
        clean_query = str(query or "").strip()
        if not clean_query or not self._chunks:
            return []

        q_vec = get_text_embedding(clean_query)
        q_terms = set(re.sub(r"[^\w\s]", " ", clean_query.lower()).split())

        scored_results: List[Tuple[float, Dict[str, Any]]] = []

        with self._lock:
            for c_id, chunk in self._chunks.items():
                if filter_doc_id and chunk.get("doc_id") != filter_doc_id:
                    continue

                c_vec = chunk.get("vector")
                if not c_vec:
                    continue

                # Dense semantic cosine similarity
                cos_score = max(0.0, cosine_similarity(q_vec, c_vec))

                # Keyword BM25 overlap boost
                c_text = chunk.get("text", "").lower()
                stop_words = {"wie", "und", "oder", "der", "die", "das", "in", "von", "zu", "mit", "den", "dem", "des", "ein", "eine", "ist", "sind", "für", "auf", "the", "and", "or", "is", "of", "to", "in", "a", "an"}
                meaningful_q_terms = [t for t in q_terms if t not in stop_words and len(t) >= 2]
                if not meaningful_q_terms:
                    meaningful_q_terms = list(q_terms)

                matched_terms = sum(1 for term in meaningful_q_terms if term in c_text)
                keyword_boost = 0.0
                if meaningful_q_terms:
                    keyword_boost = (matched_terms / len(meaningful_q_terms)) * 0.5

                total_score = round(min(1.0, cos_score * 0.5 + keyword_boost * 0.6 + (0.1 if cos_score > 0.1 else 0.0)), 4)


                if total_score >= score_threshold:
                    scored_results.append((
                        total_score,
                        {
                            "chunk_id": c_id,
                            "doc_id": chunk.get("doc_id"),
                            "score": total_score,
                            "cosine_similarity": round(cos_score, 4),
                            "text": chunk.get("text"),
                            "filename": chunk.get("metadata", {}).get("filename", "document.txt"),
                            "chunk_index": chunk.get("chunk_index"),
                            "total_chunks": chunk.get("total_chunks"),
                            "metadata": chunk.get("metadata", {}),
                        }
                    ))

        # Sort descending by relevance score
        scored_results.sort(key=lambda x: x[0], reverse=True)
        return [SearchResult(item[1]) for item in scored_results[:top_k]]


    def list_documents(self) -> List[Dict[str, Any]]:
        """Returns metadata summary of all documents currently indexed."""
        docs: Dict[str, Dict[str, Any]] = {}
        with self._lock:
            for chunk in self._chunks.values():
                d_id = chunk.get("doc_id", "unknown")
                meta = chunk.get("metadata", {})
                if d_id not in docs:
                    docs[d_id] = {
                        "doc_id": d_id,
                        "filename": meta.get("filename", "document.txt"),
                        "added_at": meta.get("added_at"),
                        "total_chunks": 0,
                        "total_chars": 0,
                    }
                docs[d_id]["total_chunks"] += 1
                docs[d_id]["total_chars"] += len(chunk.get("text", ""))

        return list(docs.values())

    def delete_document(self, doc_id: str) -> bool:
        """Deletes all chunks belonging to a document ID."""
        with self._lock:
            keys = [k for k, v in self._chunks.items() if v.get("doc_id") == doc_id]
            if not keys:
                return False
            for k in keys:
                del self._chunks[k]
            self._save()
            return True

    def clear(self) -> None:
        """Clears all indexed documents from this collection."""
        with self._lock:
            self._chunks.clear()
            self._save()


# Singleton collection manager
_STORES: Dict[str, VectorStore] = {}
_STORES_LOCK = threading.Lock()


def get_default_vector_store(collection_name: str = "default") -> VectorStore:
    """Returns singleton VectorStore instance for the specified collection."""
    with _STORES_LOCK:
        if collection_name not in _STORES:
            _STORES[collection_name] = VectorStore(collection_name=collection_name)
        return _STORES[collection_name]
