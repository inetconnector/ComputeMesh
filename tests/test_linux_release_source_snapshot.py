"""Linux package must contain only the attested Git commit, never a dirty tree."""

import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from tools import build_all_releases as release


def _commit(root: Path) -> str:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Git Snapshot Test"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "source snapshot"], check=True)
    return subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()


def test_linux_tarball_uses_committed_source_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "services").mkdir()
    (repo / "runtime").mkdir()
    (repo / "portal").mkdir()
    (repo / "services" / "app.py").write_text("COMMITTED = True\n", encoding="utf-8")
    (repo / "runtime" / "component.py").write_text("PINNED = True\n", encoding="utf-8")
    (repo / "README.md").write_text("source\n", encoding="utf-8")
    (repo / "portal" / "ignored.txt").write_text("not packaged\n", encoding="utf-8")
    commit = _commit(repo)
    # These modifications are intentionally NOT allowed in the release.
    (repo / "services" / "app.py").write_text("COMMITTED = False\n", encoding="utf-8")
    (repo / "services" / "untracked.py").write_text("secret = True\n", encoding="utf-8")
    downloads = repo / "portal" / "downloads"
    monkeypatch.setattr(release, "REPO_ROOT", repo)
    monkeypatch.setattr(release, "DOWNLOADS_DIR", downloads)
    monkeypatch.setattr(release, "VERSION", "1.2.189")

    package = release.build_linux_tarball()
    with tarfile.open(package, "r:gz") as archive:
        names = set(archive.getnames())
        assert "services/untracked.py" not in names
        assert "portal/ignored.txt" not in names
        assert "services/app.py" in names
        assert archive.extractfile("services/app.py").read() == b"COMMITTED = True\n"
        metadata = json.loads(archive.extractfile("computemesh-build-provenance.json").read())
    assert metadata == {
        "schema_version": 1,
        "artifact_kind": "linux-x64",
        "source_commit": commit,
        "version": "1.2.189",
    }


def test_linux_archive_is_byte_identical_for_same_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "services").mkdir()
    (repo / "services" / "app.py").write_text("SOURCE = 1\n", encoding="utf-8")
    _commit(repo)
    monkeypatch.setattr(release, "REPO_ROOT", repo)
    monkeypatch.setattr(release, "DOWNLOADS_DIR", repo / "downloads")
    one = release.build_linux_tarball().read_bytes()
    two = release.build_linux_tarball().read_bytes()
    assert one == two


def test_symlink_in_committed_release_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "services").mkdir()
    (repo / "README.md").write_text("target\n", encoding="utf-8")
    link = repo / "services" / "target"
    try:
        link.symlink_to("../README.md")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unsupported: {exc}")
    _commit(repo)
    monkeypatch.setattr(release, "REPO_ROOT", repo)
    monkeypatch.setattr(release, "DOWNLOADS_DIR", repo / "downloads")
    with pytest.raises(release.ReleaseBuildError, match="unsupported symlink"):
        release.build_linux_tarball()
    assert not (repo / "downloads" / "computemesh-linux-x86_64.tar.gz").exists()
