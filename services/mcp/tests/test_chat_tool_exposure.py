"""Regression tests for chat-model tool exposure."""

from services.mcp.tool_registry import MODEL_HIDDEN_TOOL_NAMES, ToolRegistry


def test_custom_tool_admin_wrappers_are_not_advertised_to_chat_models():
    registry = ToolRegistry()
    advertised = {
        item.get("function", {}).get("name")
        for item in registry.get_openai_tools(is_owner=True)
    }

    assert "execute_custom_tool" in MODEL_HIDDEN_TOOL_NAMES
    assert not (advertised & MODEL_HIDDEN_TOOL_NAMES)

    # The wrappers still exist for explicit MCP/API execution; only model exposure is hidden.
    assert registry.get_tool("execute_custom_tool") is not None


def test_normal_and_persisted_tools_remain_model_visible():
    registry = ToolRegistry()
    registry.register_tool(
        "regression_visible_custom_tool",
        "A harmless custom tool used by the regression test.",
        {"type": "object", "properties": {}},
        lambda: {"ok": True},
        source="custom_store",
    )
    advertised = {
        item.get("function", {}).get("name")
        for item in registry.get_openai_tools(is_owner=True)
    }

    assert "regression_visible_custom_tool" in advertised
    assert "list_available_tools" in advertised
