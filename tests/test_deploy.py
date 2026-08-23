"""Tests for the installer.

The team travels as a plugin now, so most of what used to be copied is not
installed at all. What is left is three files and two settings keys, and drift
is still the failure to design against: these tests mostly check that the
installer refuses to do the unsafe thing, and that the plugin is what actually
carries the team.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools.deploy import (
    ARTEFACT_DIRS,
    REPO_ROOT,
    VERSION_FILE,
    DeployError,
    install,
    plan,
    plugin_manifest,
    plugin_reference,
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

    assert (target / ".claude" / "TEAM.md").is_file()
    assert (target / ".claude" / "settings.json").is_file()
    assert (target / ".github" / "pull_request_template.md").is_file()
    for directory in ARTEFACT_DIRS:
        assert (target / directory).is_dir()


def test_the_team_itself_is_not_copied(tmp_path: Path) -> None:
    """The whole of TF-003: a prompt fix arrives by version bump, not by copy.

    Eighteen files used to be written here. If any of them come back, the
    target has two copies of the team that can disagree, and the version bump
    stops being how a fix travels.
    """
    target = make_repo(tmp_path)
    install(target)
    for gone in (
        ".claude/agents",
        ".claude/commands",
        ".claude/hooks",
        ".claude/tools",
    ):
        assert not (target / gone).exists(), f"{gone} is copied again"


def test_the_target_is_told_where_the_team_comes_from(tmp_path: Path) -> None:
    """Two keys instead of eighteen files: the marketplace, and the plugin."""
    target = make_repo(tmp_path)
    install(target)
    settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert settings["enabledPlugins"] == {plugin_reference(): True}
    marketplace = plugin_reference().split("@", 1)[1]
    source = settings["extraKnownMarketplaces"][marketplace]["source"]
    # A directory source is how area54 loads its own copy, and is meaningless
    # anywhere else: a target repo has to fetch it.
    assert source["source"] == "github"
    assert source["repo"] == "TokenFruit/area54"


def test_the_version_file_records_the_plugin_version(tmp_path: Path) -> None:
    """ "Fixed by version bump" needs the target to say which version it has."""
    target = make_repo(tmp_path)
    install(target)
    recorded = (target / VERSION_FILE).read_text(encoding="utf-8")
    assert f"version {plugin_manifest()['version']}" in recorded
    assert "claude plugin update area54" in recorded


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
    assert ".claude/TEAM.md" in manifest
    assert ".claude/settings.json" in manifest
    assert "installed from area54" in (target / VERSION_FILE).read_text(encoding="utf-8")


# --- drift ----------------------------------------------------------------


def test_a_local_edit_is_detected_rather_than_silently_reverted(tmp_path: Path) -> None:
    """The failure this installer exists to prevent."""
    target = make_repo(tmp_path)
    install(target)
    commit_all(target)

    constitution = target / ".claude" / "TEAM.md"
    constitution.write_text(
        constitution.read_text(encoding="utf-8") + "\nlocal tweak\n", encoding="utf-8"
    )
    commit_all(target)

    assert any(c.kind == "locally-edited" for c in plan(target))
    with pytest.raises(DeployError, match="edited in the target"):
        install(target)


def test_force_overwrites_a_local_edit(tmp_path: Path) -> None:
    target = make_repo(tmp_path)
    install(target)
    commit_all(target)

    constitution = target / ".claude" / "TEAM.md"
    constitution.write_text("gutted\n", encoding="utf-8")
    commit_all(target)

    install(target, force=True)
    assert "Do not edit it here" in constitution.read_text(encoding="utf-8")


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
    assert "Bash(git push --force:*)" in loaded["permissions"]["deny"]

    # Merging is not denied by a permission rule any more — the merge gate
    # decides and the guard enforces it. So what a target repo must receive is
    # the guard itself, and that now arrives in the plugin rather than as a
    # copied file. What has to hold is that the plugin is enabled: settings
    # permitting `gh pr merge` with no plugin behind them is an ungated merge.
    assert loaded["enabledPlugins"][plugin_reference()] is True


def test_the_permission_list_is_the_one_area54_runs_under(tmp_path: Path) -> None:
    """The rules an agent runs under here are the rules it runs under anywhere.

    Not a copied file: `plugin.json` accepts a `settings` record, passes
    validation with it, and ignores it at load time — so the list is generated
    into the target rather than shipped in the manifest.
    """
    target = make_repo(tmp_path)
    install(target)
    installed = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    ours = json.loads((REPO_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert installed["permissions"] == ours["permissions"]


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


# --- migrating a repo that has the old copied team ------------------------


def make_old_target(tmp_path: Path) -> Path:
    """A repo deployed by the copying installer, with its manifest."""
    import hashlib

    target = make_repo(tmp_path, "oldtarget")
    copied = {
        ".claude/agents/lead.md": "you are the lead\n",
        ".claude/commands/review.md": "review it\n",
        ".claude/hooks/record_event.py": "print('x')\n",
        ".claude/tools/merge_gate.py": "print('gate')\n",
    }
    lines = ["# The Token Fruit engineering team, installed from area54 @ deadbee"]
    for rel, body in copied.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        lines.append(f"{hashlib.sha256(body.encode()).hexdigest()[:16]} {rel}")
    (target / VERSION_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")
    commit_all(target)
    return target


def test_an_upgrade_removes_the_team_it_used_to_copy(tmp_path: Path) -> None:
    """Every already-deployed repo is in this state; migrating them is the point.

    A stale `.claude/agents/` is not merely untidy — Claude Code discovers it by
    convention, so eight frozen prompts keep loading beside the plugin's and the
    repo runs two teams that can disagree.
    """
    target = make_old_target(tmp_path)
    install(target)
    for gone in (
        ".claude/agents/lead.md",
        ".claude/commands/review.md",
        ".claude/hooks/record_event.py",
        ".claude/tools/merge_gate.py",
    ):
        assert not (target / gone).exists(), gone


def test_an_upgrade_leaves_no_empty_component_directory(tmp_path: Path) -> None:
    """An empty `.claude/agents` is still a component directory."""
    target = make_old_target(tmp_path)
    install(target)
    for gone in (".claude/agents", ".claude/commands", ".claude/hooks", ".claude/tools"):
        assert not (target / gone).exists(), gone


def test_the_upgrade_is_reported_rather_than_silent(tmp_path: Path) -> None:
    target = make_old_target(tmp_path)
    superseded_paths = [c.path for c in plan(target) if c.kind == "superseded"]
    assert ".claude/agents/lead.md" in superseded_paths
    assert len(superseded_paths) == 4


def test_only_files_this_installer_wrote_are_removed(tmp_path: Path) -> None:
    """Anything the manifest does not claim belongs to the target repo."""
    target = make_old_target(tmp_path)
    theirs = target / ".claude" / "their-own-notes.md"
    theirs.write_text("ours, not yours\n", encoding="utf-8")
    commit_all(target)

    install(target)
    assert theirs.read_text(encoding="utf-8") == "ours, not yours\n"


def test_a_second_upgrade_is_a_no_op(tmp_path: Path) -> None:
    target = make_old_target(tmp_path)
    install(target)
    commit_all(target)
    assert install(target) == []


# --- the marketplace name is a global key ---------------------------------


def test_a_colliding_marketplace_name_is_reported(tmp_path: Path) -> None:
    """Why the first live verification of this installer ran the wrong commit.

    `extraKnownMarketplaces` is not per-project. area54 registers `tokenfruit`
    as its own working copy; a target asking for the same name gets that copy
    rather than GitHub, silently, because the first registration wins.
    """
    from tools.deploy import marketplace_collision

    registry = tmp_path / "known_marketplaces.json"
    registry.write_text(
        json.dumps(
            {"tokenfruit": {"source": {"source": "directory", "path": "/somewhere/area-54"}}}
        ),
        encoding="utf-8",
    )
    warning = marketplace_collision(registry)
    assert warning is not None
    assert "/somewhere/area-54" in warning
    assert "first registration wins" in warning


def test_a_matching_registration_is_not_reported(tmp_path: Path) -> None:
    from tools.deploy import MARKETPLACE_SOURCE, marketplace_collision

    registry = tmp_path / "known_marketplaces.json"
    registry.write_text(json.dumps({"tokenfruit": {"source": MARKETPLACE_SOURCE}}), "utf-8")
    assert marketplace_collision(registry) is None


def test_an_unregistered_name_is_not_reported(tmp_path: Path) -> None:
    from tools.deploy import marketplace_collision

    registry = tmp_path / "known_marketplaces.json"
    registry.write_text(json.dumps({"someone-else": {"source": {"source": "npm"}}}), "utf-8")
    assert marketplace_collision(registry) is None
    assert marketplace_collision(tmp_path / "absent.json") is None
