"""ComputeMesh Central Configuration Module.

Single source of truth for domain endpoints, cluster settings, API URLs,
and network parameters across the entire ComputeMesh ecosystem.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any


@dataclass
class MeshEndpoints:
    """Core domain and public endpoint configurations."""
    # Main domain (changeable in one place, or overridden via COMPUTEMESH_DOMAIN env var)
    domain: str = os.environ.get("COMPUTEMESH_DOMAIN", "mesh.inetconnector.com")
    scheme: str = os.environ.get("COMPUTEMESH_SCHEME", "https")

    @property
    def host(self) -> str:
        return self.domain

    @property
    def base_url(self) -> str:
        return f"{self.scheme}://{self.domain}"

    @property
    def api_base_url(self) -> str:
        return f"{self.base_url}/api/v1"

    @property
    def api_url(self) -> str:
        return f"{self.base_url}/v1"

    @property
    def portal_url(self) -> str:
        return self.base_url

    @property
    def update_manifest_url(self) -> str:
        return f"{self.base_url}/updates/version.json"

    @property
    def heartbeat_url(self) -> str:
        return f"{self.base_url}/api/v1/node/heartbeat"

    def get_node_tunnel_url(self, node_id: str, auth_token: str = "") -> str:
        url = f"{self.base_url}/node/{node_id}"
        if auth_token:
            url += f"?auth={auth_token}"
        return url

    def get_download_url(self, filename: str) -> str:
        return f"{self.base_url}/downloads/{filename}"


@dataclass
class TeaserConfig:
    """Free teaser playground configuration without upfront registration."""
    max_free_requests: int = int(os.environ.get("COMPUTEMESH_TEASER_MAX_REQUESTS", "20"))
    max_free_tokens: int = int(os.environ.get("COMPUTEMESH_TEASER_MAX_TOKENS", "8192"))
    window_seconds: int = int(os.environ.get("COMPUTEMESH_TEASER_WINDOW_SECONDS", "14400"))
    initial_grant_micro_units: int = int(os.environ.get("COMPUTEMESH_TEASER_INITIAL_GRANT", "20000000"))
    enabled: bool = os.environ.get("COMPUTEMESH_TEASER_ENABLED", "1").strip().lower() in ("1", "true", "yes")


@dataclass
class PortConfig:
    """Configures default networking ports."""
    gateway: int = int(os.environ.get("COMPUTEMESH_GATEWAY_PORT", "8000"))
    portal: int = int(os.environ.get("COMPUTEMESH_PORTAL_PORT", "3000"))
    appliance_dashboard: int = int(os.environ.get("COMPUTEMESH_DASHBOARD_PORT", "8080"))


# Semantic alias
EndpointConfig = MeshEndpoints


@dataclass
class ComputeMeshConfig:
    """Master configuration class containing all primary subsystem configurations."""
    endpoints: MeshEndpoints = field(default_factory=MeshEndpoints)
    ports: PortConfig = field(default_factory=PortConfig)
    teaser: TeaserConfig = field(default_factory=TeaserConfig)
    appliance_version: str = "1.2.22"
    default_dashboard_port: int = 8080
    default_gateway_port: int = 8000
    default_cluster_peers: list[str] = field(default_factory=lambda: [
        p.strip() for p in os.environ.get("COMPUTEMESH_CLUSTER_PEERS", "http://192.168.1.27:8080").split(",") if p.strip()
    ])

    @classmethod
    def from_env(cls) -> ComputeMeshConfig:
        return cls(
            endpoints=MeshEndpoints(),
            ports=PortConfig(),
            teaser=TeaserConfig(),
            appliance_version=os.environ.get("COMPUTEMESH_VERSION", "1.2.22"),
            default_dashboard_port=int(os.environ.get("COMPUTEMESH_DASHBOARD_PORT", "8080")),
            default_gateway_port=int(os.environ.get("COMPUTEMESH_GATEWAY_PORT", "8000")),
        )


# Global singleton instance
CONFIG = ComputeMeshConfig.from_env()
