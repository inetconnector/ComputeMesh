"""Android package versions must match the public release source version."""

from pathlib import Path
from unittest.mock import patch

import pytest
from deploy.android import build_apk


def test_android_release_source_version_is_aligned() -> None:
    name, code = build_apk._read_version()
    assert name == build_apk.CONFIG.appliance_version
    assert name == "1.2.190"
    assert code == 190


@pytest.mark.parametrize(
    "version_code,version_name",
    [(189, "1.2.189"), (191, "1.2.191"), (0, "1.2.190")],
)
def test_stale_or_invalid_android_version_fails_before_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    version_code: int, version_name: str,
) -> None:
    gradle = tmp_path / "build.gradle.kts"
    gradle.write_text(
        f'versionCode = {version_code}\nversionName = "{version_name}"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(build_apk, "APP_GRADLE", gradle)
    with patch.object(
        build_apk, "_verify_signing_environment",
        side_effect=AssertionError("signing was accessed before version preflight"),
    ), pytest.raises(RuntimeError, match="does not match|must be positive"):
        build_apk.build_release()
