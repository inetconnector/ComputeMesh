"""Unit tests for local node reachability detection and 'Node verwalten' management links."""
import json
import unittest
from services.gateway.dashboard import (
    _extract_candidate_local_urls,
    render_node_remote_dashboard_html,
)


class TestLocalNodeManagement(unittest.TestCase):
    def test_extract_candidate_local_urls_defaults(self) -> None:
        node_data = {
            "node_id": "cm-inference-node-01",
            "dashboard_port": 8080,
        }
        urls = _extract_candidate_local_urls(node_data)
        self.assertIn("http://localhost:8080", urls)
        self.assertIn("http://127.0.0.1:8080", urls)

    def test_extract_candidate_local_urls_custom_port_and_lan_ips(self) -> None:
        node_data = {
            "node_id": "cm-inference-node-01",
            "dashboard_port": 9090,
            "network": {
                "dashboard_port": 9090,
                "lan_ips": ["192.168.1.150", "10.0.0.42"],
                "interfaces": [
                    {"interface": "eth0", "ip": "192.168.1.150"},
                    {"interface": "tunnel", "ip": "mesh.inetconnector.com"},
                ],
            },
            "client_ip": "192.168.1.150",
        }
        urls = _extract_candidate_local_urls(node_data)
        self.assertIn("http://localhost:9090", urls)
        self.assertIn("http://127.0.0.1:9090", urls)
        self.assertIn("http://192.168.1.150:9090", urls)
        self.assertIn("http://10.0.0.42:9090", urls)
        # Tunnel domain must not be added as a local IP
        self.assertNotIn("http://mesh.inetconnector.com:9090", urls)

    def test_render_dashboard_contains_node_management_elements(self) -> None:
        node_data = {
            "node_id": "cm-inference-node-01",
            "dashboard_port": 8080,
            "network": {
                "lan_ips": ["192.168.1.94"],
            },
            "inventory": {
                "gpus": [{"model_name": "AMD Radeon RX 580", "vram_bytes": 8 * 1024**3}],
            },
            "telemetry": {
                "tokens_processed": 108921,
                "local_compute_tflops": 72.0,
            },
        }
        rendered = render_node_remote_dashboard_html("cm-inference-node-01", "token123", node_data)
        self.assertIn("btn-node-manage-header", rendered)
        self.assertIn("stat-pill-local", rendered)
        self.assertIn("link-node-manage-card", rendered)
        self.assertIn("Node verwalten", rendered)
        self.assertIn("http://192.168.1.94:8080", rendered)
        self.assertIn("lan-candidates-data", rendered)

    def test_render_dashboard_xss_protection(self) -> None:
        malicious_node_data = {
            "node_id": "<script>alert(1)</script>",
            "local_ip": "\"><script>steal()</script>",
            "inventory": {
                "gpus": [{"model_name": "<b onmouseover=evil()>", "vram_bytes": 0}]
            },
            "telemetry": {},
        }
        rendered = render_node_remote_dashboard_html(
            "<script>alert(1)</script>",
            "token_xyz",
            malicious_node_data,
        )
        self.assertNotIn("<script>alert(1)</script>", rendered)
        self.assertNotIn("<b onmouseover=evil()>", rendered)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)


if __name__ == "__main__":
    unittest.main()
