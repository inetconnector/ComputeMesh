"""Regression guard against accidental Android production publication on push."""

from pathlib import Path

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github" / "workflows" / "android-release.yml"
)


def test_android_publishing_is_manual_and_commit_approved() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "if: github.event_name == 'workflow_dispatch'" in source
    assert "secrets.ANDROID_RELEASE_APPROVED_SHA" in source
    assert '"$CM_ANDROID_RELEASE_APPROVED_SHA" != "$GITHUB_SHA"' in source
    assert '"$GITHUB_REF" != "refs/heads/main"' in source
    assert source.index("CM_ANDROID_RELEASE_APPROVED_SHA") < source.index(
        "gh release upload android-latest"
    )


def test_build_and_signature_checks_remain_available_on_main() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "branches: [main]" in source
    assert ":app:assembleRelease :app:bundleRelease" in source
    assert "verify_production_signatures(" in source
    assert "secrets.ANDROID_SIGNING_CERT_SHA256" in source
