from runtime.llama.gpu_promo_challenge import GPU_PROMO_CAPABILITY
from services.orchestrator.live_control_plane import LIVE_CONTROL_PLANE_CAPABILITIES


def test_integrated_live_control_plane_offers_gpu_promo_capability() -> None:
    assert "execution_attestation_v1" in LIVE_CONTROL_PLANE_CAPABILITIES
    assert "live_runtime_registration_v1" in LIVE_CONTROL_PLANE_CAPABILITIES
    assert GPU_PROMO_CAPABILITY in LIVE_CONTROL_PLANE_CAPABILITIES
    assert len(LIVE_CONTROL_PLANE_CAPABILITIES) == len(set(LIVE_CONTROL_PLANE_CAPABILITIES))
