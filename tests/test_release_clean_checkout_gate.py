"""The release orchestrator must package and sign only a clean Git checkout."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from tools import build_all_releases as release


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True,
    ).strip()


def _make_checkout(root: Path) -> None:
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Clean Checkout Test")
    _git(root, "config", "user.email", "fixture@example.invalid")
    (root / "tracked.py").write_text("approved = True\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "approved release source")


def test_clean_git_root_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    _make_checkout(root)
    monkeypatch.setattr(release, "REPO_ROOT", root)
    assert release._require_clean_release_checkout() == _git(root, "rev-parse", "HEAD")


@pytest.mark.parametrize("change", ["modified", "untracked"])
def test_unapproved_source_changes_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str,
) -> None:
    root = tmp_path / "repo"
    _make_checkout(root)
    monkeypatch.setattr(release, "REPO_ROOT", root)
    filename = "tracked.py" if change == "modified" else "untracked.py"
    (root / filename).write_text("not approved\n", encoding="utf-8")
    with pytest.raises(release.ReleaseBuildError, match="modified or untracked"):
        release._require_clean_release_checkout()


def test_nested_git_directory_is_not_release_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    _make_checkout(root)
    nested = root / "some-nested-dir"
    nested.mkdir()
    monkeypatch.setattr(release, "REPO_ROOT", nested)
    with pytest.raises(release.ReleaseBuildError, match="Git checkout root"):
        release._require_clean_release_checkout()


def test_dirty_source_prevents_any_artifact_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    _make_checkout(root)
    (root / "tracked.py").write_text("modified = True\n", encoding="utf-8")
    monkeypatch.setattr(release, "REPO_ROOT", root)
    with patch.object(release, "build_linux_tarball") as tarball, pytest.raises(release.ReleaseBuildError, match="modified or untracked"):
        release.main()
    tarball.assert_not_called()
