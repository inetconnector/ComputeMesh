import unittest
import tempfile
import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from services.portal.fleet_accounts import FleetAccountStore
from services.billing.owner_accounts import OwnerAccountStore
from services.mcp.agent_loop import AgentLoop
from services.mcp.tool_registry import ToolRegistry

class TestFleetMcpSettings(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "fleet_test.db"
        self.store = FleetAccountStore(self.db_path)
        self.billing_db_path = Path(self.tmp_dir.name) / "billing_test.db"
        self.billing_store = OwnerAccountStore(self.billing_db_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_default_empty_disabled_tools(self):
        # Default should be empty list (meaning all tools are enabled)
        disabled = self.store.get_mcp_disabled_tools("owner_test_123")
        self.assertEqual(disabled, [])

    def test_set_and_get_disabled_tools(self):
        tools = ["get_market_quote", "get_current_weather"]
        self.store.set_mcp_disabled_tools("owner_test_123", tools)
        
        disabled = self.store.get_mcp_disabled_tools("owner_test_123")
        self.assertEqual(disabled, tools)

        # Update with new list
        new_tools = ["search_web"]
        self.store.set_mcp_disabled_tools("owner_test_123", new_tools)
        self.assertEqual(self.store.get_mcp_disabled_tools("owner_test_123"), new_tools)

        # Clear (enable all)
        self.store.set_mcp_disabled_tools("owner_test_123", [])
        self.assertEqual(self.store.get_mcp_disabled_tools("owner_test_123"), [])

    def test_billing_owner_mcp_settings(self):
        disabled = self.billing_store.get_mcp_disabled_tools("owner_billing_456")
        self.assertEqual(disabled, [])

        self.billing_store.set_mcp_disabled_tools("owner_billing_456", ["calculate_math"])
        self.assertEqual(self.billing_store.get_mcp_disabled_tools("owner_billing_456"), ["calculate_math"])

    def test_agent_loop_disabled_tools_filtering(self):
        registry = ToolRegistry()
        all_tools = registry.get_openai_tools(is_owner=True)
        self.assertGreaterEqual(len(all_tools), 20)

        # AgentLoop with disabled tools
        disabled = ["get_market_quote", "lookup_network_host"]
        filtered_tools = [
            t for t in all_tools
            if t.get("function", {}).get("name") not in disabled
        ]
        tool_names = [t["function"]["name"] for t in filtered_tools]
        self.assertNotIn("get_market_quote", tool_names)
        self.assertNotIn("lookup_network_host", tool_names)
        self.assertIn("get_current_weather", tool_names)
        self.assertIn("calculate_math", tool_names)

if __name__ == "__main__":
    unittest.main()
