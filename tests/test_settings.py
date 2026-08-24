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


# --- what a hook tells an agent to run, in a target repo ------------------


def test_nothing_shipped_names_a_command_that_exists_only_here() -> None:
    """Found twice: the guard's merge refusal, then `/status`.

    There is no `tools` package in a target repo. The first fix closed the class
    over hooks and agents and left it standing in the seven `commands/` prompts,
    where `/status` reached it on a branch that is *always* taken — the plugin's
    own hook writes the telemetry file the branch tests for.
    """
    from tools.settings import check_instructions_name_a_command_that_exists

    assert check_instructions_name_a_command_that_exists() == []


@pytest.mark.parametrize(
    ("directory", "name", "body"),
    [
        ("hooks", "guard.py", 'print("Run `python -m tools.merge_gate 1` first.")'),
        ("hooks", "guard.py", 'print("Run `python3 -m tools.merge_gate 1` first.")'),
        ("hooks", "guard.py", 'print("Run `uv run -m tools.orchestrate next` first.")'),
        ("hooks", "guard.py", 'print("Run `tools/merge_gate.py 1` first.")'),
        ("commands", "status.md", "Run `python -m tools.telemetry` and show the last run."),
        ("agents", "devops.md", "Run `python3 -m tools.merge_gate <pr>` before merging."),
    ],
)
def test_each_area54_only_spelling_is_caught(
    directory: str, name: str, body: str, tmp_path: Path
) -> None:
    """The first fix matched one literal string — the one already corrected.

    `python3` is the likeliest of these rather than the contrived one:
    `bin/merge-gate` execs `python3` itself.
    """
    from tools.settings import check_instructions_name_a_command_that_exists

    (tmp_path / directory).mkdir()
    (tmp_path / directory / name).write_text(body + "\n", encoding="utf-8")
    failures = check_instructions_name_a_command_that_exists(tmp_path)
    assert len(failures) == 1, failures
    assert "does not exist in a target repo" in failures[0]


def test_a_mention_that_says_which_repo_it_applies_to_is_allowed(tmp_path: Path) -> None:
    """Two shipped mentions are correct because they scope themselves."""
    from tools.settings import check_instructions_name_a_command_that_exists

    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "devops.md").write_text(
        "Run `merge-gate <pr>`.\n\n*(In area54 itself, that is\n"
        "`python -m tools.merge_gate <pr>`.)*\n",
        encoding="utf-8",
    )
    assert check_instructions_name_a_command_that_exists(tmp_path) == []


def test_a_hook_comment_is_not_an_instruction(tmp_path: Path) -> None:
    """A comment documenting a constant never reaches an agent.

    A check that cries wolf about its own source comments gets its rule widened
    until it catches nothing.
    """
    from tools.settings import check_instructions_name_a_command_that_exists

    (tmp_path / "hooks").mkdir()
    (tmp_path / "hooks" / "guard.py").write_text(
        "#: Must match tools/merge_gate.TOKEN_TTL_SECONDS.\nTTL = 600\n", encoding="utf-8"
    )
    assert check_instructions_name_a_command_that_exists(tmp_path) == []


def test_the_guard_refusal_actually_names_the_bin_command() -> None:
    """End to end, not just the absence of the wrong spelling."""
    refusal = guard.blocks("gh pr merge 12 --squash")
    assert refusal is not None
    assert "merge-gate 12 --repo" in refusal


# --- a tool that travels and is not permitted stops the pipeline ----------


def test_every_bin_tool_an_agent_is_told_to_run_is_permitted() -> None:
    """Invisible in area54: `Bash(python -m tools:*)` covers the source spelling."""
    from tools.settings import check_agent_commands_are_permitted

    assert check_agent_commands_are_permitted(load_settings(SETTINGS_PATH)) == []


def test_prose_mentioning_a_tool_name_does_not_demand_a_permission(tmp_path: Path) -> None:
    """`entry.name in prompts` asked whether the characters appear anywhere.

    A tool named `status` fired on the words "to see status", and the remedy it
    named — add an allow rule — widens the permission list on a coincidence.
    """
    from tools.settings import check_agent_commands_are_permitted

    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "status").write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "devops.md").write_text("Read the board to see status.\n", "utf-8")
    s = settings_from({"permissions": {"allow": [], "deny": []}}, tmp_path)
    assert check_agent_commands_are_permitted(s, tmp_path) == []


def test_a_longer_rule_name_does_not_satisfy_the_permission_check(tmp_path: Path) -> None:
    """`Bash(merge-gateway:*)` permits nothing that `merge-gate` needs."""
    from tools.settings import check_agent_commands_are_permitted

    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "merge-gate").write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "devops.md").write_text("Run `merge-gate <pr>`.\n", "utf-8")
    s = settings_from({"permissions": {"allow": ["Bash(merge-gateway:*)"]}}, tmp_path)
    assert len(check_agent_commands_are_permitted(s, tmp_path)) == 1


def test_a_dated_log_path_still_needs_a_reader(tmp_path: Path) -> None:
    """The shape a quoted-path pattern cannot see is the shape a real log takes."""
    from tools.settings import check_deployed_paths_have_a_reader

    (tmp_path / "hooks").mkdir()
    (tmp_path / "hooks" / "writer.py").write_text(
        'LOG = Path(".claude") / f"costs-{today}.jsonl"\n', encoding="utf-8"
    )
    failures = check_deployed_paths_have_a_reader(tmp_path)
    assert len(failures) == 1
    assert "does not say what reads it" in failures[0]


def test_an_unpermitted_bin_tool_is_caught(tmp_path: Path) -> None:
    from tools.settings import check_agent_commands_are_permitted

    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "merge-gate").write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "devops.md").write_text(
        "Run `merge-gate <pr> --repo <owner/name>`.\n", encoding="utf-8"
    )
    s = settings_from({"permissions": {"allow": ["Bash(git status:*)"], "deny": []}}, tmp_path)
    failures = check_agent_commands_are_permitted(s, tmp_path)
    assert len(failures) == 1
    assert "no allow rule covers it" in failures[0]


# --- a hook that writes into every target needs a named reader ------------


def test_an_unregistered_written_path_is_caught(tmp_path: Path) -> None:
    """The check this replaced could not fail: its only branch needed a
    committed file to be missing. This is the telemetry case, re-run."""
    from tools.settings import check_deployed_paths_have_a_reader

    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "record_cost.py").write_text('LOG = ".claude/costs.jsonl"\n', encoding="utf-8")
    failures = check_deployed_paths_have_a_reader(tmp_path)
    assert len(failures) == 1
    assert "does not say what reads it" in failures[0]


def test_a_registered_written_path_passes(tmp_path: Path) -> None:
    from tools.settings import check_deployed_paths_have_a_reader

    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "record_event.py").write_text('LOG = ".claude/telemetry.jsonl"\n', encoding="utf-8")
    assert check_deployed_paths_have_a_reader(tmp_path) == []


def test_the_gate_the_launcher_runs_names_itself_by_its_reachable_name() -> None:
    """Third instance of one class: `--help` is agent-facing text too.

    `tools/merge_gate.py` is not in an instruction directory, but `bin/merge-gate`
    execs it, and it was printing `usage: tools.merge_gate` — a usage line naming
    a command that cannot run where it was printed.
    """
    import subprocess

    launcher = Path(__file__).resolve().parent.parent / "bin" / "merge-gate"
    result = subprocess.run([str(launcher), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stdout.startswith("usage: merge-gate")
    assert "python -m tools." not in result.stdout.split("In area54 itself")[0]


def test_a_bin_launched_tool_is_scanned_for_area54_only_spellings(tmp_path: Path) -> None:
    from tools.settings import check_instructions_name_a_command_that_exists

    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "gate").write_text(
        '#!/bin/sh\nexec python3 "$(dirname "$0")/../tools/gate.py" "$@"\n', encoding="utf-8"
    )
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "gate.py").write_text(
        'PROG = "usage: python -m tools.gate"\n', encoding="utf-8"
    )
    failures = check_instructions_name_a_command_that_exists(tmp_path)
    assert len(failures) == 1
    assert "does not exist in a target repo" in failures[0]


# --- the scan set is derived from what ships ------------------------------


def test_the_scan_set_covers_everything_the_installer_copies() -> None:
    """Three rounds found three instances, each one directory outside the last.

    The boundary was a hand-typed tuple sitting next to the real answer. The
    fourth instance was in `team/TEAM.md` — the constitution, which `CLAUDE.md`
    says every agent inherits, and which nothing scanned.
    """
    from tools.deploy import PAYLOAD
    from tools.settings import shipped_instruction_files

    scanned = {p.resolve() for p in shipped_instruction_files()}
    root = Path(__file__).resolve().parent.parent
    for source, _ in PAYLOAD:
        path = (root / source).resolve()
        if path.is_file():
            assert path in scanned, f"{source} is copied into every target and not scanned"


def test_the_constitution_is_scanned() -> None:
    from tools.settings import shipped_instruction_files

    root = Path(__file__).resolve().parent.parent
    assert (root / "team" / "TEAM.md").resolve() in {
        p.resolve() for p in shipped_instruction_files()
    }


def test_a_distant_string_cannot_launder_an_unscoped_instruction(tmp_path: Path) -> None:
    """ "The line before" meant "the previous string constant in walk order".

    So an unrelated banner four source lines away, in another scope, exempted a
    refusal message — latent in the one directory this class keeps returning to.
    """
    from tools.settings import check_instructions_name_a_command_that_exists

    (tmp_path / "hooks").mkdir()
    (tmp_path / "hooks" / "guard.py").write_text(
        'BANNER = "area54 shell guard"\n\n\ndef refuse() -> str:\n'
        '    return "Run `python -m tools.merge_gate 1` first."\n',
        encoding="utf-8",
    )
    failures = check_instructions_name_a_command_that_exists(tmp_path)
    assert len(failures) == 1, failures


def test_a_launcher_without_a_path_separator_does_not_crash(tmp_path: Path) -> None:
    """It raised IndexError and took `tools/validate.py` down with it.

    A validator that crashes when someone adds a launcher is worse than one that
    misses it: the traceback has no connection to what they did.
    """
    from tools.settings import check_instructions_name_a_command_that_exists

    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "g").write_text('#!/bin/sh\nexec python3 merge_gate.py "$@"\n', "utf-8")
    assert check_instructions_name_a_command_that_exists(tmp_path) == []
