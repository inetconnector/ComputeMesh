from services.orchestrator.live_control_plane import (
    CAPACITY_RESERVATION_CAPABILITY,
    INFERENCE_CAPABILITY,
    LIVE_CONTROL_PLANE_CAPABILITIES,
)


def test_live_control_plane_offers_provider_execution_capabilities() -> None:
    assert "execution_attestation_v1" in LIVE_CONTROL_PLANE_CAPABILITIES
    assert "live_runtime_registration_v1" in LIVE_CONTROL_PLANE_CAPABILITIES
    assert CAPACITY_RESERVATION_CAPABILITY in LIVE_CONTROL_PLANE_CAPABILITIES
    assert INFERENCE_CAPABILITY in LIVE_CONTROL_PLANE_CAPABILITIES
