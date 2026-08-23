"""Tests for the installer.

Deployment is a copy, so drift is the failure to design against. These tests
mostly check that the installer refuses to do the unsafe thing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools.deploy import (
    ARTEFACT_DIRS,
    VERSION_FILE,
    DeployError,
    install,
    plan,
    read_manifest,
)


def make_repo(tmp_path: Path, name: str = "target") -> Path:
    target = tmp_path / name
    target.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(target), *args], check=True, capture_output=True)
    (target / "README.md").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(target), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(target), "commit", "-qm", "init"], check=True, capture_output=True
    )
    return target


def commit_all(target: Path) -> None:
    subprocess.run(["git", "-C", str(target), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(target), "commit", "-qm", "installed"], check=True, capture_output=True
    )


# --- refusing to do the unsafe thing --------------------------------------


def test_a_non_git_directory_is_refused(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(DeployError, match="not a git repository"):
        install(plain)


def test_a_dirty_target_is_refused(tmp_path: Path) -> None:
    """Installing writes many files; a bad result must stay revertible."""
    target = make_repo(tmp_path)
    (target / "work-in-progress.txt").write_text("mine\n", encoding="utf-8")
    with pytest.raises(DeployError, match="uncommitted changes"):
        install(target)


def test_a_missing_directory_is_refused(tmp_path: Path) -> None:
    with pytest.raises(DeployError, match="not a directory"):
        install(tmp_path / "nope")


# --- installing -----------------------------------------------------------


def test_a_first_install_delivers_the_team(tmp_path: Path) -> None:
    target = make_repo(tmp_path)
    install(target)

    assert (target / ".claude" / "agents" / "lead.md").is_file()
    assert (target / ".claude" / "commands" / "review.md").is_file()
    assert (target / ".claude" / "TEAM.md").is_file()
    assert (target / ".github" / "pull_request_template.md").is_file()
    for directory in ARTEFACT_DIRS:
        assert (target / directory).is_dir()


def test_the_deployed_constitution_says_not_to_edit_it(tmp_path: Path) -> None:
    target = make_repo(tmp_path)
    install(target)
    text = (target / ".claude" / "TEAM.md").read_text(encoding="utf-8")
    assert "Do not edit it here" in text


def test_the_target_keeps_its_own_claude_md(tmp_path: Path) -> None:
    """The team ships roles; the project supplies stack and conventions."""
    target = make_repo(tmp_path)
    (target / "CLAUDE.md").write_text("# My project\n\nnpm test\n", encoding="utf-8")
    commit_all(target)
    install(target)
    assert (target / "CLAUDE.md").read_text(encoding="utf-8") == "# My project\n\nnpm test\n"


def test_installing_twice_changes_nothing_the_second_time(tmp_path: Path) -> None:
    target = make_repo(tmp_path)
    install(target)
    commit_all(target)
    assert install(target) == []


def test_the_manifest_records_every_installed_file(tmp_path: Path) -> None:
    target = make_repo(tmp_path)
    install(target)
    manifest = read_manifest(target)
    assert ".claude/agents/lead.md" in manifest
    assert ".claude/TEAM.md" in manifest
    assert "installed from area54" in (target / VERSION_FILE).read_text(encoding="utf-8")


# --- drift ----------------------------------------------------------------


def test_a_local_edit_is_detected_rather_than_silently_reverted(tmp_path: Path) -> None:
    """The failure this installer exists to prevent."""
    target = make_repo(tmp_path)
    install(target)
    commit_all(target)

    lead = target / ".claude" / "agents" / "lead.md"
    lead.write_text(lead.read_text(encoding="utf-8") + "\nlocal tweak\n", encoding="utf-8")
    commit_all(target)

    assert any(c.kind == "locally-edited" for c in plan(target))
    with pytest.raises(DeployError, match="edited in the target"):
        install(target)


def test_force_overwrites_a_local_edit(tmp_path: Path) -> None:
    target = make_repo(tmp_path)
    install(target)
    commit_all(target)

    lead = target / ".claude" / "agents" / "lead.md"
    lead.write_text("gutted\n", encoding="utf-8")
    commit_all(target)

    install(target, force=True)
    assert "Engineering Lead" in lead.read_text(encoding="utf-8")


def test_check_reports_a_stale_target(tmp_path: Path) -> None:
    target = make_repo(tmp_path)
    assert [c.kind for c in plan(target)].count("new") > 0


# --- permissions travel with the team -------------------------------------


def test_settings_are_installed(tmp_path: Path) -> None:
    """Without permissions the team arrives unable to run the project's tests."""
    target = make_repo(tmp_path)
    install(target)
    settings = target / ".claude" / "settings.json"
    assert settings.is_file()
    import json

    loaded = json.loads(settings.read_text(encoding="utf-8"))
    assert "Bash(gh pr merge:*)" in loaded["permissions"]["deny"]


def test_a_preexisting_target_file_is_not_clobbered(tmp_path: Path) -> None:
    """A file the target already had is not ours to replace."""
    target = make_repo(tmp_path)
    (target / ".claude").mkdir()
    (target / ".claude" / "settings.json").write_text('{"theirs": true}\n', encoding="utf-8")
    commit_all(target)

    assert any(c.kind == "conflict" for c in plan(target))
    with pytest.raises(DeployError, match="did not write them"):
        install(target)
    assert '"theirs"' in (target / ".claude" / "settings.json").read_text(encoding="utf-8")


def test_force_replaces_a_preexisting_file(tmp_path: Path) -> None:
    target = make_repo(tmp_path)
    (target / ".claude").mkdir()
    (target / ".claude" / "settings.json").write_text('{"theirs": true}\n', encoding="utf-8")
    commit_all(target)

    install(target, force=True)
    assert '"theirs"' not in (target / ".claude" / "settings.json").read_text(encoding="utf-8")
