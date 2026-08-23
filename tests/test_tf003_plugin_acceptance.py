"""Acceptance tests for TF-003 — the team is a plugin, not a copy.

There is no spec for TF-003. These tests are written against the roadmap line:

    Package the team as a Claude Code plugin, so a prompt fix reaches every
    product repo by version bump instead of six copy-pastes

and against `docs/adr/0001-stack.md`, which adds:

    Target repos are unmodified by installation, which is a property worth
    protecting in every future decision.

They were written before the implementation was read, from those two documents,
so they assert what a target repo must be able to observe — not what the code
happens to do. Every runtime fact they encode (components are found by
convention, `hooks.json` needs its wrapper, a plugin-declared `settings` record
is ignored) was reproduced live against Claude Code 2.1.241 in a scratch repo
before being written down here.

The live half of the validation — `claude plugin marketplace add`,
`claude plugin install`, `claude plugin details`, and a real `git push` through
the plugin-delivered guard — cannot run in CI without an authenticated CLI, so
it is recorded on the PR rather than automated here. What is automated is
everything decidable from the repo, plus the guard's own behaviour, which is a
plain script and travels as one.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

PLUGIN_MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_MANIFEST = REPO_ROOT / ".claude-plugin" / "marketplace.json"
HOOKS_MANIFEST = REPO_ROOT / "hooks" / "hooks.json"

#: Manifest fields Claude Code's schema accepts and its runtime ignores.
#: Declaring a component here instead of putting it in the directory the
#: runtime scans is the failure this feature exists to avoid: the packaging
#: validates and the component is not loaded.
INERT_MANIFEST_FIELDS = ("agents", "commands", "skills", "settings")

#: The three files the installer is allowed to write into a product repo, plus
#: the bookkeeping stamp it uses to detect drift. Anything else is a file that
#: has to be copied again on every prompt fix — the thing TF-003 removes.
EXPECTED_TARGET_FILES = {
    ".claude/TEAM.md",
    ".claude/settings.json",
    ".claude/TEAM_VERSION",
    ".github/pull_request_template.md",
}


def _load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "tf003_guard", REPO_ROOT / "hooks" / "guard_bash.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)


@pytest.fixture
def target_repo(tmp_path: Path) -> Path:
    """A clean git repo standing in for a product repo."""
    repo = tmp_path / "product"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", "."], cwd=repo, check=True)
    _git(repo, "config", "user.email", "tester@example.com")
    _git(repo, "config", "user.name", "tester")
    (repo / "README.md").write_text("# product\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


def _deploy(target: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tools.deploy", str(target), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _files(repo: Path) -> set[str]:
    return {
        str(p.relative_to(repo))
        for p in repo.rglob("*")
        if p.is_file() and ".git/" not in f"{p.relative_to(repo)}/"
    }


# --- AC1: the repo is a Claude Code plugin -------------------------------


def test_tf003_ac1_the_repo_carries_a_plugin_manifest() -> None:
    """TF-003 AC1: the team is packaged as a Claude Code plugin."""
    assert PLUGIN_MANIFEST.is_file(), (
        ".claude-plugin/plugin.json is missing. Without a manifest there is no "
        "plugin, and a target repo has nothing to install."
    )
    manifest = _load(PLUGIN_MANIFEST)
    for field in ("name", "version", "description"):
        assert manifest.get(field), f"plugin.json: `{field}` is missing or empty."


def test_tf003_ac1_the_manifest_carries_a_version_to_bump() -> None:
    """TF-003 AC1: "a prompt fix arrives by version bump" needs a version."""
    version = _load(PLUGIN_MANIFEST).get("version", "")
    parts = str(version).split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts), (
        f"plugin.json version {version!r} is not SemVer. ADR-0001 requires SemVer, "
        f"and a prompt fix that alters behaviour is a minor bump."
    )


# --- AC2: the repo is its own marketplace --------------------------------


def test_tf003_ac2_the_repo_is_its_own_marketplace() -> None:
    """TF-003 AC2: the repo is the plugin and its own marketplace."""
    assert MARKETPLACE_MANIFEST.is_file(), ".claude-plugin/marketplace.json is missing."
    marketplace = _load(MARKETPLACE_MANIFEST)
    manifest = _load(PLUGIN_MANIFEST)
    entries = marketplace.get("plugins") or []
    matching = [e for e in entries if e.get("name") == manifest["name"]]
    assert matching, (
        f"marketplace.json does not list `{manifest['name']}`. A target repo adds the "
        f"marketplace and installs by name; an absent entry installs nothing."
    )
    source = matching[0].get("source")
    assert isinstance(source, str) and (REPO_ROOT / source).is_dir(), (
        f"marketplace.json: source {source!r} is not a directory in this repo."
    )


# --- AC3: components load at runtime, by convention ----------------------


@pytest.mark.parametrize("directory", ["agents", "commands"])
def test_tf003_ac3_components_live_where_the_runtime_scans(directory: str) -> None:
    """TF-003 AC3: components are discovered by convention, not by manifest."""
    path = REPO_ROOT / directory
    assert path.is_dir(), (
        f"{directory}/ is missing at the plugin root. Claude Code discovers "
        f"components by convention; no directory means the runtime loads none."
    )
    assert list(path.glob("*.md")), f"{directory}/ holds no *.md, so the plugin loads none."


def test_tf003_ac3_every_agent_the_team_names_is_in_the_plugin() -> None:
    """TF-003 AC3: all eight roles travel, or a target repo has a partial team."""
    names = {p.stem for p in (REPO_ROOT / "agents").glob("*.md")}
    expected = {
        "architect",
        "builder-backend",
        "builder-frontend",
        "designer",
        "devops",
        "lead",
        "product-owner",
        "tester",
    }
    assert expected <= names, f"missing agents in the plugin: {sorted(expected - names)}"


def test_tf003_ac3_no_agent_or_command_is_left_in_the_old_copied_location() -> None:
    """TF-003 AC3: nothing is both copied and carried."""
    for stale in (REPO_ROOT / ".claude" / "agents", REPO_ROOT / ".claude" / "commands"):
        assert not stale.exists(), (
            f"{stale.relative_to(REPO_ROOT)} still exists. Two copies of a role drift, "
            f"which is the failure TF-003 removes."
        )


# --- AC4: no inert manifest field --------------------------------------


@pytest.mark.parametrize("field", INERT_MANIFEST_FIELDS)
def test_tf003_ac4_the_manifest_declares_no_field_the_runtime_ignores(field: str) -> None:
    """TF-003 AC4: a field that validates and loads nothing is worse than an error."""
    assert field not in _load(PLUGIN_MANIFEST), (
        f"plugin.json declares `{field}`. `claude plugin validate` accepts it and the "
        f"runtime ignores it, so the packaging looks correct while the component is "
        f"absent. Reproduced on CLI 2.1.241."
    )


# --- AC5: hooks are configured in the shape the runtime reads ------------


def test_tf003_ac5_hooks_json_wraps_its_events() -> None:
    """TF-003 AC5: without the top-level `hooks` key the file configures nothing."""
    assert HOOKS_MANIFEST.is_file(), "hooks/hooks.json is missing; the plugin has no hooks."
    data = _load(HOOKS_MANIFEST)
    assert isinstance(data.get("hooks"), dict) and data["hooks"], (
        "hooks/hooks.json needs a non-empty top-level `hooks` key wrapping the events. "
        "Without it `claude plugin details` reports Hooks (0) and the push guard is "
        "configured, valid, and absent."
    )


def test_tf003_ac5_a_bash_pretooluse_hook_is_configured() -> None:
    """TF-003 AC5: the guard the roadmap line depends on has to be wired up."""
    events = _load(HOOKS_MANIFEST)["hooks"]
    matchers = [entry.get("matcher") for entry in events.get("PreToolUse", [])]
    assert "Bash" in matchers, (
        f"no PreToolUse hook matches Bash (matchers: {matchers}). The push-to-main "
        f"guard would never run in a target repo."
    )


def test_tf003_ac5_hook_commands_resolve_against_the_plugin_root() -> None:
    """TF-003 AC5: a hook path relative to the target repo does not exist there."""
    events = _load(HOOKS_MANIFEST)["hooks"]
    for entries in events.values():
        for entry in entries:
            for hook in entry.get("hooks", []):
                command = str(hook.get("command", ""))
                if ".py" not in command and ".sh" not in command:
                    continue
                assert "CLAUDE_PLUGIN_ROOT" in command, (
                    f"hook command {command!r} does not resolve against "
                    f"${{CLAUDE_PLUGIN_ROOT}}. In a product repo it names a path that "
                    f"does not exist, and the hook fails at the moment it should protect."
                )


def test_tf003_ac5_every_script_a_hook_names_is_inside_the_plugin() -> None:
    """TF-003 AC5: the plugin carries hooks/ and nothing else."""
    events = _load(HOOKS_MANIFEST)["hooks"]
    for entries in events.values():
        for entry in entries:
            for hook in entry.get("hooks", []):
                for token in str(hook.get("command", "")).replace('"', " ").split():
                    if not token.endswith((".py", ".sh")):
                        continue
                    tail = token.split("}", 1)[-1].lstrip("/")
                    assert tail.startswith("hooks/"), (
                        f"hook names {tail!r}, outside hooks/. The plugin carries what is "
                        f"under hooks/; a script elsewhere is configured everywhere and "
                        f"present nowhere."
                    )
                    assert (REPO_ROOT / tail).is_file(), f"{tail} does not exist."


# --- AC6: tools reach a target through bin/ on PATH ----------------------


def test_tf003_ac6_every_bin_entry_can_start() -> None:
    """TF-003 AC6: bin/ is on PATH in every target; a non-executable entry is dead."""
    bin_dir = REPO_ROOT / "bin"
    if not bin_dir.is_dir():
        pytest.skip("the plugin ships no bin/")
    for entry in sorted(bin_dir.iterdir()):
        if entry.is_file():
            assert os.access(entry, os.X_OK), (
                f"bin/{entry.name} is not executable and is on PATH in every target repo."
            )


# --- AC7: the installer's footprint --------------------------------------


def test_tf003_ac7_installing_writes_only_the_agreed_files(target_repo: Path) -> None:
    """TF-003 AC7: three files plus artefact dirs, not twenty-one."""
    before = _files(target_repo)
    result = _deploy(target_repo)
    assert result.returncode == 0, result.stdout + result.stderr
    written = _files(target_repo) - before
    unexpected = {p for p in written if not p.endswith(".gitkeep")} - EXPECTED_TARGET_FILES
    assert not unexpected, (
        f"the installer wrote files outside the agreed set: {sorted(unexpected)}. "
        f"Every extra file is one more thing a prompt fix has to copy again."
    )


def test_tf003_ac7_installing_touches_nothing_the_target_already_had(
    target_repo: Path,
) -> None:
    """TF-003 AC7 / ADR-0001: "target repos are unmodified by installation"."""
    before = {p: (target_repo / p).read_bytes() for p in _files(target_repo)}
    assert _deploy(target_repo).returncode == 0
    for path, content in before.items():
        assert (target_repo / path).read_bytes() == content, (
            f"the installer modified {path}, which belonged to the target repo. "
            f"ADR-0001: target repos are unmodified by installation."
        )


def test_tf003_ac7_no_agent_or_command_file_is_copied_into_a_target(
    target_repo: Path,
) -> None:
    """TF-003 AC7: the roles arrive by plugin, so no role is a file in the target."""
    assert _deploy(target_repo).returncode == 0
    copied = {p for p in _files(target_repo) if "/agents/" in p or "/commands/" in p}
    assert not copied, (
        f"role or command files were copied into the target: {sorted(copied)}. "
        f"A copied prompt is a prompt that drifts; TF-003 delivers them by version bump."
    )


def test_tf003_ac7_the_target_gets_the_two_keys_that_install_the_plugin(
    target_repo: Path,
) -> None:
    """TF-003 AC7: without both keys the target has settings and no team."""
    assert _deploy(target_repo).returncode == 0
    settings = _load(target_repo / ".claude" / "settings.json")
    manifest = _load(PLUGIN_MANIFEST)
    marketplace_name = _load(MARKETPLACE_MANIFEST)["name"]
    assert marketplace_name in settings.get("extraKnownMarketplaces", {}), (
        f"the target does not know the {marketplace_name} marketplace, so it cannot "
        f"resolve the plugin."
    )
    assert settings.get("enabledPlugins", {}).get(f"{manifest['name']}@{marketplace_name}") is True


def test_tf003_ac7_the_permission_list_survives_installation(target_repo: Path) -> None:
    """TF-003 AC7: the deny list cannot travel in the manifest, so it must be here.

    Measured on CLI 2.1.241: a plugin-declared `permissions.deny` did not block
    the command it named, while an identical deny in `.claude/settings.json`
    did. A target that gets the plugin but not this list is unguarded.
    """
    assert _deploy(target_repo).returncode == 0
    deny = _load(target_repo / ".claude" / "settings.json").get("permissions", {}).get("deny", [])
    assert deny, "the installed settings carry no deny list."
    assert any("push" in rule and "main" in rule for rule in deny), (
        f"no rule in the installed deny list names a push to main: {deny}"
    )


# --- AC8: installing twice, and --check ---------------------------------


def test_tf003_ac8_installing_a_second_time_changes_nothing(target_repo: Path) -> None:
    """TF-003 AC8: an installer that is not idempotent cannot be run from CI."""
    assert _deploy(target_repo).returncode == 0
    _git(target_repo, "add", "-A")
    _git(target_repo, "commit", "-qm", "install the team")
    after_first = {p: (target_repo / p).read_bytes() for p in _files(target_repo)}
    assert _deploy(target_repo).returncode == 0
    assert {p: (target_repo / p).read_bytes() for p in _files(target_repo)} == after_first
    assert not _git(target_repo, "status", "--porcelain").stdout.strip(), (
        "a second install left the target's working tree dirty."
    )


def test_tf003_ac8_check_reports_a_target_that_has_never_been_installed(
    target_repo: Path,
) -> None:
    """TF-003 AC8: --check must be usable as a CI gate, so it must exit non-zero."""
    result = _deploy(target_repo, "--check")
    assert result.returncode != 0, (
        "--check exited 0 on a target with no team installed. CI would report the repo as current."
    )


def test_tf003_ac8_check_passes_on_a_current_target(target_repo: Path) -> None:
    """TF-003 AC8: --check must not cry wolf on a repo that is up to date."""
    assert _deploy(target_repo).returncode == 0
    result = _deploy(target_repo, "--check")
    assert result.returncode == 0, result.stdout + result.stderr


def test_tf003_ac8_dry_run_writes_nothing(target_repo: Path) -> None:
    """TF-003 AC8: a dry run that writes is not a dry run."""
    before = _files(target_repo)
    assert _deploy(target_repo, "--dry-run").returncode == 0
    assert _files(target_repo) == before


# --- AC9: a target that already has its own settings --------------------


def test_tf003_ac9_a_targets_own_settings_are_not_silently_replaced(
    target_repo: Path,
) -> None:
    """TF-003 AC9 / ADR-0001: installation does not destroy the target's config."""
    (target_repo / ".claude").mkdir(exist_ok=True)
    theirs = {
        "permissions": {"allow": ["Bash(make build:*)"], "deny": ["Read(./secrets/**)"]},
        "env": {"THEIR_KEY": "keep-me"},
    }
    settings = target_repo / ".claude" / "settings.json"
    settings.write_text(json.dumps(theirs, indent=2), encoding="utf-8")
    _git(target_repo, "add", "-A")
    _git(target_repo, "commit", "-qm", "our own settings")

    result = _deploy(target_repo)
    assert result.returncode != 0, (
        "the installer replaced a target's own .claude/settings.json and exited 0. "
        "Their permissions and env would be gone with no signal."
    )
    assert _load(settings) == theirs, "the target's own settings were modified anyway."


def test_tf003_ac9_forcing_over_a_targets_settings_says_it_is_doing_so(
    target_repo: Path,
) -> None:
    """TF-003 AC9: --force may destroy the file, but it must name it in the change list.

    A destructive overwrite that is not listed among the changes is invisible to
    whoever ran the installer, and to whoever reviews the diff after them.
    """
    (target_repo / ".claude").mkdir(exist_ok=True)
    settings = target_repo / ".claude" / "settings.json"
    settings.write_text(
        json.dumps({"permissions": {"allow": ["Bash(make build:*)"]}}, indent=2),
        encoding="utf-8",
    )
    _git(target_repo, "add", "-A")
    _git(target_repo, "commit", "-qm", "our own settings")

    result = _deploy(target_repo, "--force")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Bash(make build:*)" not in settings.read_text(encoding="utf-8")
    assert ".claude/settings.json" in result.stdout, (
        "--force replaced the target's own .claude/settings.json without listing it as "
        f"a change. Output was:\n{result.stdout}"
    )


# --- AC10 / AC11: the guard that travels with the plugin ----------------


@pytest.mark.parametrize(
    "command",
    [
        "git push -u origin main",
        "git push origin main",
        "git push origin HEAD:main",
        "git push origin main:main",
        "git push origin +main",
        "git push --force origin feature/x",
        "cd /tmp && git push -u origin main",
        "echo ok; git push -u origin main",
    ],
)
def test_tf003_ac10_the_guard_refuses_a_push_to_a_protected_branch(command: str) -> None:
    """TF-003 AC10: the plugin-delivered guard refuses a direct push to main."""
    reason = _guard().blocks(command)
    assert reason, f"the guard allowed {command!r}. A protected branch is reachable directly."


@pytest.mark.parametrize(
    "command",
    [
        "git push -u origin feature/tf-003",
        "git push origin tf-003-plugin",
        "git push -u origin HEAD",
        "git push origin maintenance-notes",
        "git push origin main-menu-fix",
    ],
)
def test_tf003_ac11_the_guard_permits_a_push_to_a_feature_branch(command: str) -> None:
    """TF-003 AC11: a guard that blocks legitimate pushes stalls the pipeline silently.

    Nobody notices a guard that is too strict until the pipeline stops, so this
    direction is asserted as explicitly as the refusal.
    """
    reason = _guard().blocks(command)
    assert reason is None, f"the guard refused a legitimate push: {command!r} — {reason}"


def test_tf003_ac10_the_guard_runs_as_the_runtime_invokes_it(tmp_path: Path) -> None:
    """TF-003 AC10: the hook is a script the runtime feeds JSON on stdin.

    Asserting the module's function is not enough — the plugin ships a file that
    Claude Code executes, and a script that cannot parse its own event is a
    guard that is configured and inert.
    """
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "git push -u origin main"},
        "cwd": str(tmp_path),
    }
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "hooks" / "guard_bash.py")],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0 or "deny" in combined, (
        f"the guard script exited {result.returncode} and said nothing when handed a "
        f"push to main:\n{combined}"
    )
    assert "main" in combined, f"the refusal does not name the branch:\n{combined}"


def test_tf003_ac11_the_guard_script_stays_out_of_the_way_of_ordinary_work(
    tmp_path: Path,
) -> None:
    """TF-003 AC11: the same script, on a permitted command, must not block."""
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "git push -u origin feature/tf-003"},
        "cwd": str(tmp_path),
    }
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "hooks" / "guard_bash.py")],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, (
        f"the guard blocked a push to a feature branch:\n{result.stdout}{result.stderr}"
    )
    assert "deny" not in result.stdout, f"the guard denied a feature-branch push: {result.stdout}"


@pytest.mark.parametrize(
    "payload",
    ["", "not json at all", "[]", '{"tool_name": "Bash"}', '{"tool_input": null}'],
)
def test_tf003_ac11_the_guard_survives_malformed_input(payload: str, tmp_path: Path) -> None:
    """TF-003 AC11: a guard that crashes on a surprising event blocks every command."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "hooks" / "guard_bash.py")],
        input=payload,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode in (0, 2), (
        f"the guard exited {result.returncode} on input {payload!r}:\n{result.stderr}"
    )
    assert "Traceback" not in result.stderr, f"the guard crashed on {payload!r}:\n{result.stderr}"


# --- AC12: a prompt fix arrives by version bump -------------------------


def test_tf003_ac12_the_marketplace_version_does_not_contradict_the_plugin() -> None:
    """TF-003 AC12: a marketplace pinning a stale version ships a stale team."""
    manifest = _load(PLUGIN_MANIFEST)
    for entry in _load(MARKETPLACE_MANIFEST).get("plugins", []):
        if entry.get("name") != manifest["name"]:
            continue
        if "version" in entry:
            assert entry["version"] == manifest["version"], (
                f"marketplace.json pins {entry['version']}, plugin.json says "
                f"{manifest['version']}. `claude plugin tag` refuses this."
            )


def test_tf003_ac12_a_target_records_which_area54_it_installed(target_repo: Path) -> None:
    """TF-003 AC12: "reaches every repo by version bump" needs a before to compare."""
    assert _deploy(target_repo).returncode == 0
    stamp = target_repo / ".claude" / "TEAM_VERSION"
    assert stamp.is_file(), (
        ".claude/TEAM_VERSION is missing, so nothing in the target says which area54 "
        "it holds and --check cannot tell current from stale."
    )
    assert stamp.read_text(encoding="utf-8").strip(), "TEAM_VERSION is empty."


# --- AC13: area54 runs the team it ships --------------------------------


def test_tf003_ac13_area54_installs_its_own_plugin() -> None:
    """TF-003 AC13: area54 builds itself using itself, per CLAUDE.md."""
    settings = _load(REPO_ROOT / ".claude" / "settings.json")
    manifest = _load(PLUGIN_MANIFEST)
    marketplace = _load(MARKETPLACE_MANIFEST)["name"]
    assert settings.get("enabledPlugins", {}).get(f"{manifest['name']}@{marketplace}") is True, (
        "area54 does not enable its own plugin, so this repo runs with no team at all."
    )
    source = settings.get("extraKnownMarketplaces", {}).get(marketplace, {}).get("source", {})
    assert source.get("path") and not str(source["path"]).startswith("/"), (
        f"the marketplace source {source!r} is not a relative path, so it is "
        f"machine-specific and cannot be committed."
    )


def test_tf003_ac13_no_agent_prompt_names_a_repo_relative_script() -> None:
    """TF-003 AC13: a path an agent spells only exists in area54's own checkout."""
    offenders = []
    for prompt in sorted((REPO_ROOT / "agents").glob("*.md")):
        text = prompt.read_text("utf-8")
        for path in sorted(set(re.findall(r"\.claude/[\w./-]+\.(?:py|sh)", text))):
            offenders.append(f"{prompt.name} names {path!r}")
    assert not offenders, (
        f"{offenders} — in a product repo that path does not exist. Tools reach a "
        f"target through the plugin's bin/ on PATH."
    )


# --- AC14: what a hook says is an instruction the agent follows ---------


def test_tf003_ac14_hook_output_never_names_an_area54_only_command() -> None:
    """TF-003 AC14: a hook runs in the target repo, so its message must work there.

    The roadmap line's whole point is that what travels resolves everywhere it
    lands. `check_agent_commands_are_deployed` reads agent prompts; the same
    mistake inside a hook's own refusal text is not covered by it, and a hook's
    refusal text is an instruction the agent acts on — at the one irreversible
    step in the pipeline.
    """
    offenders = []
    for hook in sorted((REPO_ROOT / "hooks").glob("*.py")):
        for line_no, line in enumerate(hook.read_text("utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if "python -m tools." in line:
                offenders.append(f"hooks/{hook.name}:{line_no}: {line.strip()}")
    assert not offenders, (
        "a hook tells the agent to run a command that exists only in area54; a target "
        "repo has no `tools` package, so following the instruction raises "
        "ModuleNotFoundError:\n  " + "\n  ".join(offenders)
    )


def test_tf003_ac14_the_merge_refusal_names_a_command_a_target_repo_has() -> None:
    """TF-003 AC14: the refusal an agent reads must name the tool that travelled."""
    guard = _guard()
    reason = guard.blocks("gh pr merge 33 --squash")
    assert reason, "the guard permitted a merge with no authorisation."
    assert "python -m tools." not in reason, (
        f"the merge refusal tells the agent to run an area54-only command, which in a "
        f"product repo does not exist:\n  {reason}"
    )


def test_tf003_ac14_every_tool_an_agent_is_told_to_run_is_permitted() -> None:
    """TF-003 AC14: a tool that travels but is not allow-listed stops a headless run."""
    bin_dir = REPO_ROOT / "bin"
    if not bin_dir.is_dir():
        pytest.skip("the plugin ships no bin/")
    prompts = "\n".join(p.read_text("utf-8") for p in sorted((REPO_ROOT / "agents").glob("*.md")))
    allow = _load(REPO_ROOT / ".claude" / "settings.json")["permissions"]["allow"]
    for entry in sorted(bin_dir.iterdir()):
        if not entry.is_file() or entry.name not in prompts:
            continue
        assert any(rule.startswith(f"Bash({entry.name}") for rule in allow), (
            f"agents are told to run `{entry.name}` and no allow rule covers it. Prefix "
            f"matching cannot reach it from any other rule, so the call needs approval "
            f"that a headless run cannot give."
        )
