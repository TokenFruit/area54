"""Tests for the configuration validator.

The one defect that mattered most so far lived in settings.json, and nothing
checked that file. These tests exist so the same class of bug fails a build
rather than waiting for someone to read the right two lines.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from tools.settings import (
    MUST_BE_ALLOWED,
    MUST_BE_BLOCKED,
    SETTINGS_PATH,
    Settings,
    SettingsError,
    check_a_guard_backs_the_push_rules,
    check_hook_scripts_travel_with_the_plugin,
    check_referenced_files_exist,
    check_required_denies_survive,
    load_settings,
    validate,
)

_spec = importlib.util.spec_from_file_location(
    "guard_bash", Path(__file__).resolve().parent.parent / "hooks" / "guard_bash.py"
)
assert _spec and _spec.loader
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


def settings_from(data: dict[str, object], tmp_path: Path) -> Settings:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return load_settings(path)


# --- the shipped configuration --------------------------------------------


def test_the_shipped_settings_validate() -> None:
    assert validate() == []


@pytest.mark.parametrize("command", MUST_BE_BLOCKED)
def test_every_dangerous_command_is_blocked(command: str) -> None:
    """The end-to-end claim: whatever the allow list says, these do not run."""
    assert guard.blocks(command) is not None, command


@pytest.mark.parametrize("command", MUST_BE_ALLOWED)
def test_the_team_can_still_do_its_work(command: str) -> None:
    """A guard that blocks these is broken in the direction nobody notices."""
    assert guard.blocks(command) is None, command


def test_the_settings_file_is_valid_json() -> None:
    assert load_settings(SETTINGS_PATH).allow


# --- the failures this exists to catch ------------------------------------


def test_dropping_a_required_deny_is_caught(tmp_path: Path) -> None:
    s = settings_from({"permissions": {"allow": [], "deny": []}}, tmp_path)
    failures = check_required_denies_survive(s)
    assert len(failures) == 1
    assert "git push --force" in failures[0]


def test_granting_push_with_no_guard_is_caught(tmp_path: Path) -> None:
    """The exact hole that shipped: prefix rules with nothing reading the command."""
    s = settings_from(
        {"permissions": {"allow": ["Bash(git push -u origin:*)"], "deny": []}}, tmp_path
    )
    failures = check_a_guard_backs_the_push_rules(s, hook_commands=[])
    assert len(failures) == 1
    assert "prefix rules cannot express" in failures[0].lower()


def test_granting_push_with_a_guard_is_fine(tmp_path: Path) -> None:
    s = settings_from(
        {
            "permissions": {"allow": ["Bash(git push -u origin:*)"], "deny": []},
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [{"type": "command", "command": "python3 x/guard_bash.py"}],
                    }
                ]
            },
        },
        tmp_path,
    )
    assert check_a_guard_backs_the_push_rules(s, hook_commands=[]) == []


def test_a_hook_that_does_not_exist_is_caught(tmp_path: Path) -> None:
    """Configured and missing fails at the moment it should have protected you."""
    s = settings_from(
        {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {
                                "type": "command",
                                "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/gone.py"',
                            }
                        ],
                    }
                ]
            }
        },
        tmp_path,
    )
    failures = check_referenced_files_exist(s.hook_commands, root=tmp_path)
    assert len(failures) == 1
    assert "does not exist" in failures[0]


def test_a_hook_outside_the_plugin_is_caught() -> None:
    """The defect that shipped, in its current form.

    It used to be "settings travelled and the script it named did not". The
    installer no longer copies scripts at all: the plugin carries what is under
    hooks/, and a command naming anything else is configured in every target
    repo and present in none.
    """
    failures = check_hook_scripts_travel_with_the_plugin(
        ['python3 "${CLAUDE_PLUGIN_ROOT}/tools/orphan.py"']
    )
    assert len(failures) == 1
    assert "outside hooks/" in failures[0]


def test_a_hook_inside_the_plugin_is_fine() -> None:
    assert (
        check_hook_scripts_travel_with_the_plugin(
            ['python3 "${CLAUDE_PLUGIN_ROOT}/hooks/guard_bash.py"']
        )
        == []
    )


def test_a_root_variable_is_stripped_as_a_prefix() -> None:
    """`lstrip('./')` strips a character set and turns .claude into claude."""
    from tools.settings import _project_relative

    assert _project_relative('"$CLAUDE_PROJECT_DIR/.claude/hooks/g.py"'.strip('"')) == (
        ".claude/hooks/g.py"
    )
    assert _project_relative('"${CLAUDE_PLUGIN_ROOT}/hooks/g.py"'.strip('"')) == "hooks/g.py"
    assert _project_relative('"$CLAUDE_PLUGIN_ROOT/hooks/g.py"'.strip('"')) == "hooks/g.py"


def test_the_shipped_hooks_are_wrapped_and_reachable() -> None:
    """Without the `hooks` wrapper the file loads and configures nothing."""
    from tools.settings import load_hook_commands

    commands = load_hook_commands()
    assert len(commands) == 3
    assert all("CLAUDE_PLUGIN_ROOT" in c for c in commands)


def test_an_unwrapped_hooks_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "hooks.json"
    path.write_text(json.dumps({"PreToolUse": []}), encoding="utf-8")
    from tools.settings import load_hook_commands

    with pytest.raises(SettingsError, match="top-level `hooks` key"):
        load_hook_commands(path)


def test_a_hook_configured_in_both_places_fires_twice(tmp_path: Path) -> None:
    """Both fire, so every pipeline event would be recorded twice."""
    from tools.settings import check_hooks_are_configured_once

    s = settings_from(
        {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {
                                "type": "command",
                                "command": 'python3 "$CLAUDE_PROJECT_DIR/hooks/guard_bash.py"',
                            }
                        ],
                    }
                ]
            }
        },
        tmp_path,
    )
    failures = check_hooks_are_configured_once(s)
    assert len(failures) == 1
    assert "twice" in failures[0]


def test_the_shipped_settings_do_not_duplicate_the_plugin_hooks() -> None:
    from tools.settings import check_hooks_are_configured_once

    assert check_hooks_are_configured_once(load_settings(SETTINGS_PATH)) == []


# --- area54 has to keep loading the team it ships -------------------------


def test_the_repo_enables_its_own_plugin() -> None:
    """Without this key area54 runs with no agents, commands or hooks at all."""
    from tools.settings import check_the_repo_installs_its_own_plugin

    assert check_the_repo_installs_its_own_plugin(load_settings(SETTINGS_PATH)) == []


def test_dropping_the_plugin_from_settings_is_caught(tmp_path: Path) -> None:
    from tools.settings import check_the_repo_installs_its_own_plugin

    s = settings_from({"permissions": {"allow": [], "deny": []}}, tmp_path)
    failures = check_the_repo_installs_its_own_plugin(s)
    assert len(failures) == 1
    assert "no team at all" in failures[0]


def test_enabling_a_plugin_with_no_marketplace_is_caught(tmp_path: Path) -> None:
    """Enabled, with nowhere to install it from, loads nothing."""
    from tools.deploy import plugin_reference
    from tools.settings import check_the_repo_installs_its_own_plugin

    s = settings_from({"enabledPlugins": {plugin_reference(): True}}, tmp_path)
    failures = check_the_repo_installs_its_own_plugin(s)
    assert len(failures) == 1
    assert "not declared" in failures[0]


def test_malformed_settings_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SettingsError, match="not valid JSON"):
        load_settings(path)


# --- deployed artefacts need a reader somewhere ---------------------------


def test_every_deployed_path_is_accounted_for() -> None:
    """The gap that let telemetry ship with no way to read it.

    The payload check only looked at hooks *referenced by settings*. The
    telemetry reader is referenced by nothing, so target repos collected
    events they could not read.
    """
    from tools.settings import check_deployed_paths_have_a_reader

    assert check_deployed_paths_have_a_reader() == []


def test_a_tracked_path_is_documented_with_where_its_reader_lives() -> None:
    from tools.settings import DEPLOYED_PATH_READERS

    assert ".claude/telemetry.jsonl" in DEPLOYED_PATH_READERS
    # Not just present — it has to say where the reader is and why.
    assert "tools/telemetry.py" in DEPLOYED_PATH_READERS[".claude/telemetry.jsonl"]


# --- what agents are told to run must exist where they run ----------------


def test_every_tool_an_agent_is_told_to_run_is_deployed() -> None:
    """The gap that shipped: devops was told to run the merge gate in a target
    repo while the gate stayed in area54, so the instruction resolved to
    ModuleNotFoundError at the moment of the merge."""
    from tools.settings import check_agent_commands_are_deployed

    assert check_agent_commands_are_deployed() == []


def test_a_repo_relative_tool_reference_is_caught(tmp_path: Path) -> None:
    """The installer copies no scripts, so such a path resolves only in area54."""
    from tools.settings import check_agent_commands_are_deployed

    agents = tmp_path / "agents"
    agents.mkdir(parents=True)
    (agents / "devops.md").write_text(
        "Run `python3 .claude/tools/nowhere.py 1 --repo x/y` first.\n", encoding="utf-8"
    )
    failures = check_agent_commands_are_deployed(tmp_path)
    assert len(failures) == 1
    assert "put the tool in bin/" in failures[0]


def test_the_merge_gate_travels_with_the_team() -> None:
    """devops runs the gate in the target repo, so the gate has to be there.

    It travels in the plugin's bin/, which Claude Code appends to PATH. That is
    the only mechanism available: ${CLAUDE_PLUGIN_ROOT} is not exported to the
    Bash tool, so an agent cannot spell an absolute path to it.
    """
    launcher = Path(__file__).resolve().parent.parent / "bin" / "merge-gate"
    assert launcher.is_file()
    assert launcher.stat().st_mode & 0o111, "on PATH but not executable"
    assert "merge_gate.py" in launcher.read_text(encoding="utf-8")


def test_devops_is_told_to_run_the_gate_by_the_name_that_resolves() -> None:
    devops = (Path(__file__).resolve().parent.parent / "agents" / "devops.md").read_text(
        encoding="utf-8"
    )
    assert "merge-gate <pr> --repo" in devops


def test_the_launcher_runs_the_gate() -> None:
    """A wrapper that cannot start is worse than no wrapper."""
    import subprocess

    launcher = Path(__file__).resolve().parent.parent / "bin" / "merge-gate"
    result = subprocess.run([str(launcher), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "--repo" in result.stdout


def test_the_merge_gate_imports_only_the_standard_library() -> None:
    """It travels alone: a target repo has no tools package to import from."""
    source = (Path(__file__).resolve().parent.parent / "tools" / "merge_gate.py").read_text(
        encoding="utf-8"
    )
    assert "from tools." not in source
    assert "import tools" not in source


# --- the merge authorisation is never committable -------------------------


def test_a_merge_authorisation_is_never_tracked() -> None:
    """A committed authorisation would be a merge permit living in the repo.

    `tools/merge_gate.py` writes one on a pass and `guard_bash.py` reads it to
    permit exactly one `gh pr merge`. It is short-lived and machine-local. It
    showed up as untracked the first time the gate passed for real, which is
    the only reason anyone noticed it was not ignored.

    This asks git rather than reading `.gitignore`, so a rule that is present
    but ineffective still fails.
    """
    import subprocess

    from tools.merge_gate import TOKEN_DIR, TOKEN_NAME

    root = Path(__file__).resolve().parent.parent
    relative = f"{TOKEN_DIR}/{TOKEN_NAME}"
    done = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "-q", relative],
        capture_output=True,
        check=False,
    )
    assert done.returncode == 0, (
        f"{relative} is not ignored by git. The merge gate writes one on every "
        f"pass; committing it would put a merge permit in the repo and deploy it "
        f"to every target."
    )
