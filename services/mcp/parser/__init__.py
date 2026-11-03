# SPDX-License-Identifier: Apache-2.0
"""Tool-call parsing package."""

from .tool_call_parser import (
    JSON_CODE_BLOCK_RE,
    MAX_TOOL_CALLS_PER_ITERATION,
    RAW_JSON_TOOL_RE,
    XML_TOOL_CALL_RE,
    _canonical_name,
    _decode_arguments,
    _fallback_tool_calls,
    canonical_name,
    decode_tool_arguments,
    parse_fallback_tool_calls,
)

__all__ = [
    "JSON_CODE_BLOCK_RE",
    "MAX_TOOL_CALLS_PER_ITERATION",
    "RAW_JSON_TOOL_RE",
    "XML_TOOL_CALL_RE",
    "_canonical_name",
    "_decode_arguments",
    "_fallback_tool_calls",
    "canonical_name",
    "decode_tool_arguments",
    "parse_fallback_tool_calls",
]
