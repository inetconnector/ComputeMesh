# SPDX-License-Identifier: Apache-2.0
"""Formatting utilities for LLM reasoning and thinking accordions."""

from __future__ import annotations

import re

THINKING_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)


def format_reasoning_and_thinking_blocks(content: str) -> str:
    """Formats <think>...</think> reasoning blocks into interactive collapsible HTML accordions."""
    if not content or "<think>" not in content.lower():
        return content

    def _replace_think(match: re.Match) -> str:
        thought_text = match.group(1).strip()
        if not thought_text:
            return ""
        return (
            f'<details class="cm-thinking-block">\n'
            f'  <summary>🧠 <strong>Gedankengang anzeigen</strong> <em>(Deep Reasoning)</em></summary>\n'
            f'  <div class="cm-thinking-body">\n'
            f'{thought_text}\n'
            f'  </div>\n'
            f'</details>\n\n'
        )

    formatted = THINKING_RE.sub(_replace_think, content)
    return formatted.strip()
