# SPDX-License-Identifier: Apache-2.0
"""Semantic and Sliding-Window Chunker for ComputeMesh RAG."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional


@dataclass
class DocumentChunk:
    chunk_id: str
    doc_id: str
    text: str
    chunk_index: int
    total_chunks: int
    char_count: int
    metadata: Dict[str, Any] = field(default_factory=dict)


def chunk_text(
    text: str,
    doc_id: str = "doc_1",
    chunk_size: int = 800,
    chunk_overlap: int = 150,
    metadata: Optional[Dict[str, Any]] = None,
) -> List[DocumentChunk]:
    """Splits a document text into overlapping chunks using paragraph and sentence boundaries.

    Args:
        text: Raw document text to partition.
        doc_id: Unique identifier of parent document.
        chunk_size: Target characters per chunk (default 800 chars ~ 150-200 tokens).
        chunk_overlap: Number of overlapping characters between adjacent chunks (default 150 chars).
        metadata: Optional metadata dictionary to attach to every chunk.

    Returns:
        A list of DocumentChunk instances.
    """
    clean_text = str(text or "").strip()
    if not clean_text:
        return []

    base_meta = dict(metadata or {})

    # Split by paragraphs first
    paragraphs = re.split(r"\n\s*\n", clean_text)
    raw_blocks: List[str] = []

    for p in paragraphs:
        p_clean = p.strip()
        if not p_clean:
            continue
        if len(p_clean) <= chunk_size:
            raw_blocks.append(p_clean)
        else:
            # Split long paragraph by sentence boundaries
            sentences = re.split(r"(?<=[.!?])\s+", p_clean)
            current_sent_block = []
            current_sent_len = 0
            for s in sentences:
                if current_sent_len + len(s) > chunk_size and current_sent_block:
                    raw_blocks.append(" ".join(current_sent_block))
                    current_sent_block = [s]
                    current_sent_len = len(s)
                else:
                    current_sent_block.append(s)
                    current_sent_len += len(s) + 1
            if current_sent_block:
                raw_blocks.append(" ".join(current_sent_block))

    # Assemble overlapping chunks from blocks
    chunks: List[str] = []
    current_chunk = ""

    for block in raw_blocks:
        if not current_chunk:
            current_chunk = block
        elif len(current_chunk) + len(block) + 2 <= chunk_size:
            current_chunk += "\n\n" + block
        else:
            chunks.append(current_chunk)
            # Apply overlap by taking trailing portion of current_chunk
            if chunk_overlap > 0 and len(current_chunk) > chunk_overlap:
                overlap_text = current_chunk[-chunk_overlap:]
                # Trim to word boundary
                space_idx = overlap_text.find(" ")
                if space_idx != -1:
                    overlap_text = overlap_text[space_idx + 1:]
                current_chunk = overlap_text + "\n\n" + block
            else:
                current_chunk = block

    if current_chunk:
        chunks.append(current_chunk)

    total = len(chunks)
    result: List[DocumentChunk] = []
    for idx, c_text in enumerate(chunks):
        c_id = f"{doc_id}_chunk_{idx+1}"
        c_meta = dict(base_meta)
        c_meta["chunk_index"] = idx + 1
        c_meta["total_chunks"] = total
        result.append(DocumentChunk(
            chunk_id=c_id,
            doc_id=doc_id,
            text=c_text.strip(),
            chunk_index=idx + 1,
            total_chunks=total,
            char_count=len(c_text.strip()),
            metadata=c_meta,
        ))

    return result
