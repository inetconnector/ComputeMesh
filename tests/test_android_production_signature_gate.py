"""Android release signer verification must fail closed without its trusted pin."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from deploy.android import build_apk

PIN = "ab" * 32
OTHER = "cd" * 32


def _mock_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CM_ANDROID_EXPECTED_CERT_SHA256", PIN)
    monkeypatch.setattr(build_apk, "_find_apksigner", lambda: Path("/mock/apksigner"))
    monkeypatch.setattr(build_apk.shutil, "which", lambda name: "/mock/" + name)


def _run_success(commands: list[list[str]], *, apk_pin: str = PIN,
                 aab_pin: str = PIN, aab_verified: bool = True):
    def run(command, **kwargs):
        commands.append(command)
        assert kwargs["check"] is True
        assert kwargs["timeout"] == 60
        if command[0] == "/mock/apksigner":
            output = "Signer #1 certificate SHA-256 digest: " + apk_pin
        elif command[0] == "/mock/jarsigner":
            output = "jar verified." if aab_verified else "jar is unsigned."
        elif command[0] == "/mock/keytool":
            output = "Owner: test\nSHA256: " + ":".join(
                aab_pin[i:i+2] for i in range(0, len(aab_pin), 2)
            )
        else:
            raise AssertionError("unexpected verification tool")
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")
    return run


def test_missing_pin_fails_before_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CM_ANDROID_EXPECTED_CERT_SHA256", raising=False)
    with patch.object(build_apk.subprocess, "run") as run:
        with pytest.raises(RuntimeError, match="CM_ANDROID_EXPECTED_CERT_SHA256"):
            build_apk.verify_production_signatures(Path("apk"), Path("aab"))
    run.assert_not_called()


def test_missing_apksigner_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CM_ANDROID_EXPECTED_CERT_SHA256", PIN)
    monkeypatch.setattr(build_apk, "_find_apksigner", lambda: None)
    with patch.object(build_apk.subprocess, "run") as run:
        with pytest.raises(RuntimeError, match="requires apksigner"):
            build_apk.verify_production_signatures(Path("apk"), Path("aab"))
    run.assert_not_called()


@pytest.mark.parametrize(
    ("apk_pin", "aab_pin", "verified", "message"),
    [
        (OTHER, PIN, True, "APK signing certificate"),
        (PIN, OTHER, True, "AAB signing certificate"),
        (PIN, PIN, False, "App Bundle signature"),
    ],
)
def test_bad_signatures_never_pass(
    monkeypatch: pytest.MonkeyPatch,
    apk_pin: str,
    aab_pin: str,
    verified: bool,
    message: str,
) -> None:
    _mock_tools(monkeypatch)
    commands: list[list[str]] = []
    with patch.object(
        build_apk.subprocess, "run",
        side_effect=_run_success(commands, apk_pin=apk_pin,
                                 aab_pin=aab_pin, aab_verified=verified),
    ):
        with pytest.raises(RuntimeError, match=message):
            build_apk.verify_production_signatures(Path("apk"), Path("aab"))


def test_matching_apk_and_aab_certificate_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_tools(monkeypatch)
    commands: list[list[str]] = []
    with patch.object(
        build_apk.subprocess, "run", side_effect=_run_success(commands),
    ):
        assert build_apk.verify_production_signatures(Path("apk"), Path("aab")) == PIN
    assert [command[0] for command in commands] == [
        "/mock/apksigner", "/mock/jarsigner", "/mock/keytool",
    ]


def test_production_signing_environment_requires_public_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CM_ANDROID_ALLOW_DEBUG_RELEASE", raising=False)
    for key in (
        "CM_ANDROID_KEYSTORE_PASSWORD", "CM_ANDROID_KEY_ALIAS",
        "CM_ANDROID_KEY_PASSWORD",
    ):
        monkeypatch.setenv(key, "test-not-real")
    keystore = tmp_path / "test-keystore"
    keystore.write_bytes(b"test-only")
    monkeypatch.setenv("CM_ANDROID_KEYSTORE_PATH", str(keystore))
    monkeypatch.delenv("CM_ANDROID_EXPECTED_CERT_SHA256", raising=False)
    with pytest.raises(RuntimeError, match="CM_ANDROID_EXPECTED_CERT_SHA256"):
        build_apk._verify_signing_environment()
