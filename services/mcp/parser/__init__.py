# SPDX-License-Identifier: Apache-2.0
"""Tool-call parsing package."""

from .tool_call_parser import (
    XML_TOOL_CALL_RE,
    JSON_CODE_BLOCK_RE,
    RAW_JSON_TOOL_RE,
    MAX_TOOL_CALLS_PER_ITERATION,
    canonical_name,
    _canonical_name,
    parse_fallback_tool_calls,
    _fallback_tool_calls,
    decode_tool_arguments,
    _decode_arguments,
)

__all__ = [
    "XML_TOOL_CALL_RE",
    "JSON_CODE_BLOCK_RE",
    "RAW_JSON_TOOL_RE",
    "MAX_TOOL_CALLS_PER_ITERATION",
    "canonical_name",
    "_canonical_name",
    "parse_fallback_tool_calls",
    "_fallback_tool_calls",
    "decode_tool_arguments",
    "_decode_arguments",
]
