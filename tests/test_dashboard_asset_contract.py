"""Static contracts for dashboard-hosted images and protected QR rendering."""

from pathlib import Path


INDEX = Path(__file__).resolve().parents[1] / "services" / "appliance_dashboard" / "static" / "index.html"


def test_dashboard_does_not_depend_on_third_party_qr_images():
    source = INDEX.read_text(encoding="utf-8")
    assert "api.qrserver.com" not in source
    assert "/api/v1/qr?data=" in source
    assert "X-Node-Auth-Token" in source


def test_dashboard_qr_markup_has_accessible_fallback():
    source = INDEX.read_text(encoding="utf-8")
    assert 'id="remote-qr-code"' in source
    assert 'alt="QR-Code wird nach der Anmeldung geladen"' in source
    assert "updateLocalQrImage" in source
