from __future__ import annotations

from pathlib import Path

SERVICE = Path(__file__).resolve().parents[2] / "deploy" / "systemd" / "computemesh-node.service"
ENV_EXAMPLE = SERVICE.with_name("provider.env.example")


def test_provider_systemd_template_keeps_supervision_and_hardening() -> None:
    service = SERVICE.read_text(encoding="utf-8")
    assert "EnvironmentFile=-/etc/computemesh/provider.env" in service
    assert "Restart=on-failure" in service
    assert "RestartSec=5s" in service
    assert "NoNewPrivileges=true" in service
    assert "PrivateTmp=true" in service
    assert "ProtectSystem=strict" in service
    assert "ProtectHome=read-only" in service
    assert "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6" in service
    assert "--private-key ${COMPUTEMESH_NODE_PRIVATE_KEY}" in service
    assert "--inference-endpoint=${COMPUTEMESH_NODEOS_INFERENCE_ENDPOINT}" in service
    assert "--inference-auth-token=${COMPUTEMESH_NODEOS_INFERENCE_AUTH_TOKEN}" in service
    assert "--model-preparation-manifest=${COMPUTEMESH_MODEL_PREPARATION_MANIFEST}" in service
    assert "--environment-root=${COMPUTEMESH_NODEOS_ENVIRONMENT_ROOT}" in service


def test_provider_environment_example_contains_paths_only_not_credential_values() -> None:
    example = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "COMPUTEMESH_NODE_PRIVATE_KEY=/var/lib/computemesh/node-ed25519.pem" in example
    assert "-----BEGIN" not in example
    assert "Bearer " not in example
    assert "PRIVATE KEY" not in example
