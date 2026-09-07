# SPDX-License-Identifier: Apache-2.0
"""
Autonomous Agent Tool-Calling Execution Loop.
Iteratively executes model tool calls, appends results, and synthesizes final response.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .config import MCPConfig, get_mcp_config
from .tool_registry import ToolRegistry

XML_TOOL_CALL_RE = re.compile(r"<tool_call>\s*({.*?})(?:\s*</tool_call>|\s*$)", re.DOTALL)
JSON_CODE_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{\s*\"(?:name|tool|function)\"\s*:\s*\"[a-zA-Z0-9_-]+\".*?\})\s*```", re.DOTALL)


@dataclass
class ToolCallRecord:
    id: str
    name: str
    arguments: Dict[str, Any]
    result: Any


@dataclass
class AgentExecutionResult:
    final_content: str
    messages: List[Dict[str, Any]]
    tool_calls_executed: List[ToolCallRecord] = field(default_factory=list)
    iterations: int = 1
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class AgentLoop:
    def __init__(self, registry: Optional[ToolRegistry] = None, config: Optional[MCPConfig] = None):
        self.config = config or get_mcp_config()
        self.registry = registry or ToolRegistry(self.config)

    def run(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        llm_caller: Callable[[List[Dict[str, Any]], List[Dict[str, Any]]], Dict[str, Any]],
        is_owner: bool = True,
        max_iterations: Optional[int] = None,
    ) -> AgentExecutionResult:
        """
        Executes the agent tool calling loop.
        
        :param messages: Initial chat message list.
        :param model: Target model name.
        :param llm_caller: Function receiving (messages, tools) and returning OpenAI-compatible completion dict.
        :param is_owner: Whether the caller is authenticated with an Owner Key.
        :param max_iterations: Maximum loop iterations.
        """
        max_iter = max_iterations or self.config.max_agent_iterations
        curr_messages = [dict(m) for m in messages]
        tools = self.registry.get_openai_tools(is_owner=is_owner)

        executed_records: List[ToolCallRecord] = []
        total_prompt_tok = 0
        total_comp_tok = 0

        for iteration in range(1, max_iter + 1):
            # Call LLM with current conversation and active tools
            response = llm_caller(curr_messages, tools if tools else [])

            usage = response.get("usage", {})
            total_prompt_tok += usage.get("prompt_tokens", 0)
            total_comp_tok += usage.get("completion_tokens", 0)

            choices = response.get("choices", [])
            if not choices:
                break

            choice = choices[0]
            msg = choice.get("message", {})
            content = msg.get("content") or ""
            tool_calls = msg.get("tool_calls") or []

            # Also parse XML and JSON fallback tool calls from text if model formatted as markdown/text
            if not tool_calls:
                # 1. XML <tool_call> tags
                if "<tool_call>" in content:
                    for match in XML_TOOL_CALL_RE.finditer(content):
                        try:
                            parsed = json.loads(match.group(1))
                            fn_name = parsed.get("name") or parsed.get("tool") or parsed.get("function")
                            if fn_name:
                                tool_calls.append({
                                    "id": f"call_xml_{len(tool_calls)+1}",
                                    "type": "function",
                                    "function": {
                                        "name": fn_name,
                                        "arguments": json.dumps(parsed.get("arguments", parsed.get("parameters", {}))),
                                    },
                                })
                        except Exception:
                            pass

                # 2. Markdown ```json code blocks with {"name": "..."}
                if not tool_calls and ("```json" in content or "```" in content):
                    for match in JSON_CODE_BLOCK_RE.finditer(content):
                        try:
                            clean_json_str = re.sub(r"//.*", "", match.group(1))
                            parsed = json.loads(clean_json_str)
                            fn_name = parsed.get("name") or parsed.get("tool") or parsed.get("function")
                            if fn_name and self.registry.get_tool(fn_name):
                                tool_calls.append({
                                    "id": f"call_json_{len(tool_calls)+1}",
                                    "type": "function",
                                    "function": {
                                        "name": fn_name,
                                        "arguments": json.dumps(parsed.get("arguments", parsed.get("parameters", {}))),
                                    },
                                })
                        except Exception:
                            pass

            # If no tools were called, this is the final answer
            if not tool_calls:
                curr_messages.append({"role": "assistant", "content": content})
                return AgentExecutionResult(
                    final_content=content,
                    messages=curr_messages,
                    tool_calls_executed=executed_records,
                    iterations=iteration,
                    model=model,
                    prompt_tokens=total_prompt_tok,
                    completion_tokens=total_comp_tok,
                    total_tokens=total_prompt_tok + total_comp_tok,
                )

            # Append assistant message with tool_calls
            assistant_msg: Dict[str, Any] = {"role": "assistant"}
            if content:
                assistant_msg["content"] = content
            assistant_msg["tool_calls"] = tool_calls
            curr_messages.append(assistant_msg)

            # Execute all tool calls
            for tc in tool_calls:
                call_id = tc.get("id", f"call_{len(executed_records)+1}")
                fn = tc.get("function", {})
                fn_name = fn.get("name", "")
                raw_args = fn.get("arguments", "{}")

                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args)
                    except Exception:
                        args = {}
                elif isinstance(raw_args, dict):
                    args = raw_args
                else:
                    args = {}

                # Execute in registry
                tool_output = self.registry.execute_tool(fn_name, args, is_owner=is_owner)
                executed_records.append(
                    ToolCallRecord(
                        id=call_id,
                        name=fn_name,
                        arguments=args,
                        result=tool_output,
                    )
                )

                # Format tool response message
                output_str = json.dumps(tool_output, ensure_ascii=False) if not isinstance(tool_output, str) else tool_output
                curr_messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": fn_name,
                    "content": output_str,
                })

        # If loop reached max_iterations, return the latest content
        last_content = curr_messages[-1].get("content", "") if curr_messages else ""
        return AgentExecutionResult(
            final_content=last_content,
            messages=curr_messages,
            tool_calls_executed=executed_records,
            iterations=max_iter,
            model=model,
            prompt_tokens=total_prompt_tok,
            completion_tokens=total_comp_tok,
            total_tokens=total_prompt_tok + total_comp_tok,
        )
