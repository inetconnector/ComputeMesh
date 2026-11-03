"""Guard the retired Android publisher and independently reviewable signing proposal."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = ROOT / ".github" / "workflows" / "android-release.yml"
ARCHIVE = ROOT / "docs" / "archive" / "retired-github-actions-2026-10-28"
SIGNING_PROPOSAL = ARCHIVE / "android-release-proposed-signature-hardening-2026-11-03.yml"


def test_android_signing_proposal_is_operator_gated() -> None:
    source = SIGNING_PROPOSAL.read_text(encoding="utf-8")
    assert "INACTIVE REFERENCE ONLY" in source
    assert "if: github.event_name == 'workflow_dispatch'" in source
    assert "secrets.ANDROID_RELEASE_APPROVED_SHA" in source
    assert '"$CM_ANDROID_RELEASE_APPROVED_SHA" != "$GITHUB_SHA"' in source
    assert '"$GITHUB_REF" != "refs/heads/main"' in source
    assert source.index("CM_ANDROID_RELEASE_APPROVED_SHA") < source.index(
        "gh release upload android-latest"
    )


def test_android_signing_checks_remain_archived_not_executable() -> None:
    source = SIGNING_PROPOSAL.read_text(encoding="utf-8")
    assert ":app:assembleRelease :app:bundleRelease" in source
    assert "verify_production_signatures(" in source
    assert "secrets.ANDROID_SIGNING_CERT_SHA256" in source
    # main archives the legacy workflow; the PR merge snapshot must not revive it.
    if (ARCHIVE / "android-release.yml").is_file():
        assert not ACTIVE.exists()
