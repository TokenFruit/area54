"""Validate the configuration that can actually hurt you.

Every other validator in this package checks agent markdown. The one defect
that mattered most so far did not live there: the permission list allowed
`Bash(git push -u origin:*)` and denied `Bash(git push origin main:*)`, and
because rules match command *prefixes*, `git push -u origin main` was
auto-approved. Nothing checked it. A Lead reviewing an unrelated feature found
it by reading.

Three things go wrong in this file and none were caught by a test:

1. A permission rule that reaches somewhere it should not.
2. Settings that reference a file the deployment does not carry — the hook was
   configured and missing after its first install.
3. A deny rule quietly dropped, leaving no record that it ever existed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = REPO_ROOT / ".claude" / "settings.json"

#: Where the hooks are configured now. They moved out of settings.json when the
#: team became a plugin: a plugin's hooks travel with it, a settings file's do
#: not. Both files are still read here, because a hook configured in either
#: place fires, and one configured in both fires twice.
HOOKS_PATH = REPO_ROOT / "hooks" / "hooks.json"

#: The plugin directory the hook scripts live in. A hook command pointing
#: anywhere else is configured in every target repo and present in none.
HOOKS_DIR = REPO_ROOT / "hooks"

#: Commands that must never be auto-approved, whatever the allow list says.
#:
#: Each is a real spelling, not a category. The bypass that shipped was a real
#: spelling that no category would have described.
MUST_BE_BLOCKED = (
    "git push origin main",
    "git push -u origin main",
    "git push --set-upstream origin main",
    "git push origin HEAD:main",
    "git push origin main:main",
    "git push origin +main",
    "git push origin master",
    "git push --force origin feature",
    "git push -f origin feature",
    "gh pr merge 1 --squash",
    "gh pr merge --admin 1",
    "git reset --hard HEAD~1",
    "npm test && git push -u origin main",
)

#: Commands the team cannot work without. A guard that blocks these is broken
#: in the direction nobody notices until the pipeline stalls.
MUST_BE_ALLOWED = (
    "npm test",
    "npx tsc --noEmit",
    "git push -u origin tf-001-metadata",
    "git push origin feature/maintenance",
    "git push origin domain-fix",
    "git commit -m 'fix'",
    "gh pr create --title x --body y",
)

#: Deny rules that must survive any edit to this file.
#: Merging is deliberately absent. It is no longer denied outright, because
#: tools/merge_gate.py decides and the guard hook enforces that decision — a
#: blanket deny would short-circuit the gate and no merge could ever happen,
#: authorised or not. What must hold instead is that the guard is configured,
#: which :func:`check_a_guard_backs_the_push_rules` enforces.
REQUIRED_DENY = ("Bash(git push --force:*)",)


#: The variables a hook command may be written against. ``CLAUDE_PLUGIN_ROOT``
#: is the plugin's own checkout and is what plugin hooks use;
#: ``CLAUDE_PROJECT_DIR`` is the repo being worked on and is what a settings
#: file's hooks use. Both spellings, braced and bare.
_ROOT_VARS = (
    "${CLAUDE_PLUGIN_ROOT}/",
    "$CLAUDE_PLUGIN_ROOT/",
    "${CLAUDE_PROJECT_DIR}/",
    "$CLAUDE_PROJECT_DIR/",
)


def _project_relative(token: str) -> str:
    """Strip the root-variable prefix from a hook path.

    Deliberately not `lstrip("./")`: that strips a character *set*, so
    ``.claude/hooks/x.py`` becomes ``claude/hooks/x.py`` and every lookup
    misses. This function exists because that is exactly what happened.
    """
    for var in _ROOT_VARS:
        token = token.replace(var, "")
    return token.removeprefix("./")


def load_hook_commands(path: Path = HOOKS_PATH) -> list[str]:
    """Return every command string configured in the plugin's ``hooks.json``.

    The file wraps its events in a ``hooks`` key. That wrapper is not
    decoration: without it Claude Code loads the file and finds no hooks, which
    is how this one was written the first time.
    """
    if not path.is_file():
        raise SettingsError(f"hooks file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SettingsError(f"{path.name}: not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or "hooks" not in data:
        raise SettingsError(
            f"{path.name}: must be a mapping with a top-level `hooks` key. Without the "
            f"wrapper the file parses, loads, and configures nothing."
        )
    return _commands_in(data["hooks"])


def _commands_in(events: Any) -> list[str]:
    commands: list[str] = []
    if not isinstance(events, dict):
        return commands
    for entries in events.values():
        for entry in entries:
            for hook in entry.get("hooks", []):
                if hook.get("type") == "command":
                    commands.append(str(hook.get("command", "")))
    return commands


class SettingsError(Exception):
    """The settings file is malformed."""


@dataclass(frozen=True)
class Settings:
    """A parsed settings file."""

    path: Path
    data: dict[str, Any]

    @property
    def allow(self) -> list[str]:
        return [str(r) for r in self.data.get("permissions", {}).get("allow", [])]

    @property
    def deny(self) -> list[str]:
        return [str(r) for r in self.data.get("permissions", {}).get("deny", [])]

    @property
    def hook_commands(self) -> list[str]:
        return _commands_in(self.data.get("hooks", {}))


def load_settings(path: Path = SETTINGS_PATH) -> Settings:
    """Parse the settings file."""
    if not path.is_file():
        raise SettingsError(f"settings file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SettingsError(f"{path.name}: not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SettingsError(f"{path.name}: not a mapping.")
    return Settings(path=path, data=data)


def check_required_denies_survive(settings: Settings) -> list[str]:
    """Return failures for non-negotiable deny rules that were dropped."""
    missing = [rule for rule in REQUIRED_DENY if rule not in settings.deny]
    if missing:
        return [
            f"settings.json: deny rules {missing} are gone. They are not optional: "
            f"no agent merges its own work, and a force push destroys work another "
            f"agent is holding."
        ]
    return []


def check_a_guard_backs_the_push_rules(
    settings: Settings, hook_commands: list[str] | None = None
) -> list[str]:
    """Return a failure if `git push` is auto-approved with no hook watching.

    Prefix matching cannot express "push anywhere except main". If the allow
    list grants `git push` at all, something that reads the whole command has
    to be watching it.
    """
    if hook_commands is None:
        hook_commands = load_hook_commands()
    grants_push = any(
        rule.startswith(("Bash(git push", "Bash(gh pr merge")) for rule in settings.allow
    )
    if not grants_push:
        return []
    if not any("guard_bash" in command for command in [*hook_commands, *settings.hook_commands]):
        return [
            "settings.json: `git push` is auto-approved but no guard hook is configured. "
            "Prefix rules cannot express 'anywhere except main' — `git push -u origin main` "
            "matches an allow rule for `git push -u origin` and misses a deny rule for "
            "`git push origin main`. Configure hooks/guard_bash.py as a PreToolUse hook in "
            "hooks/hooks.json."
        ]
    return []


def check_referenced_files_exist(
    hook_commands: list[str] | None = None, root: Path = REPO_ROOT
) -> list[str]:
    """Return failures for hook scripts the configuration names but the repo lacks.

    A hook that is configured and missing fails at the moment it was supposed
    to protect something.
    """
    if hook_commands is None:
        hook_commands = load_hook_commands()
    failures = []
    for command in hook_commands:
        for token in command.replace('"', " ").split():
            if token.endswith(".py") or token.endswith(".sh"):
                relative = _project_relative(token)
                if not (root / relative).is_file():
                    failures.append(
                        f"hooks.json: hook references {relative}, which does not exist. "
                        f"A hook that is configured and missing is worse than no hook."
                    )
    return failures


def check_hook_scripts_travel_with_the_plugin(
    hook_commands: list[str] | None = None, root: Path = REPO_ROOT
) -> list[str]:
    """Return failures for hook scripts that would not arrive in a target repo.

    This is the defect that shipped once already, in its earlier form: the
    settings file travelled to a target repo and the hook it named did not. The
    installer no longer copies hooks at all — the plugin carries them, and it
    carries exactly what is under ``hooks/``. A command naming a script outside
    that directory is configured everywhere and present nowhere.
    """
    if hook_commands is None:
        hook_commands = load_hook_commands()
    failures = []
    for command in hook_commands:
        for token in command.replace('"', " ").split():
            if token.endswith(".py") or token.endswith(".sh"):
                relative = _project_relative(token)
                if not relative.startswith("hooks/"):
                    failures.append(
                        f"hooks.json: hook references {relative}, which is outside hooks/ and "
                        f"so is not carried by the plugin. Target repos would get the "
                        f"configuration without the script."
                    )
    return failures


def check_hooks_are_configured_once(settings: Settings) -> list[str]:
    """Return a failure if the same hook is configured in both files.

    Settings hooks and plugin hooks both fire. A hook listed in both runs twice
    per event, which for the event recorder means every pipeline step is
    counted twice and the telemetry silently doubles.
    """
    plugin_scripts = {
        _project_relative(token)
        for command in load_hook_commands()
        for token in command.replace('"', " ").split()
        if token.endswith((".py", ".sh"))
    }
    settings_scripts = {
        _project_relative(token)
        for command in settings.hook_commands
        for token in command.replace('"', " ").split()
        if token.endswith((".py", ".sh"))
    }
    both = sorted(plugin_scripts & settings_scripts)
    if both:
        return [
            f"{both} are configured in both hooks/hooks.json and settings.json. Both fire, "
            f"so each event is handled twice. The plugin owns the hooks; remove them from "
            f"settings.json."
        ]
    return []


def check_the_repo_installs_its_own_plugin(settings: Settings) -> list[str]:
    """Return a failure if area54 stopped loading the team it ships.

    The agents, commands and hooks live in the plugin now, not in ``.claude/``.
    Claude Code will not pick them up here unless this repo enables its own
    plugin — and area54 builds itself using itself, so a repo that quietly
    stopped doing that has lost its whole team without any test noticing.
    """
    from tools.deploy import plugin_reference

    reference = plugin_reference()
    if settings.data.get("enabledPlugins", {}).get(reference) is not True:
        return [
            f"settings.json: {reference} is not enabled. The agents, commands and hooks are "
            f"in the plugin now — without this key area54 runs with no team at all."
        ]
    marketplace = reference.split("@", 1)[1]
    if marketplace not in settings.data.get("extraKnownMarketplaces", {}):
        return [
            f"settings.json: {reference} is enabled but the `{marketplace}` marketplace is "
            f"not declared, so there is nowhere to install it from."
        ]
    return []


#: Paths a deployed repo will contain, and the module in area54 that reads or
#: writes each. A deployed artefact whose counterpart stays here is fine — but
#: it has to be a decision, recorded, rather than an oversight.
#:
#: This exists because the first version of the payload check only looked at
#: hooks *referenced by settings*. The telemetry reader is referenced by
#: nothing, so target repos collected events they had no way to read.
DEPLOYED_PATH_READERS: dict[str, str] = {
    ".claude/telemetry.jsonl": "tools/telemetry.py reads it, and stays in area54 "
    "deliberately: `python -m tools.telemetry <repo>` reports on any target, so "
    "the toolchain does not have to ship into every repo it touches.",
}


#: A path under `.claude/` that a hook writes into whichever repo it runs in.
#: Matched from the hook's source, so adding a new one is what triggers the
#: check rather than remembering to register it.
_WRITES_INTO_TARGET = re.compile(r"[\"\']((?:\.claude/)?[\w.-]+\.jsonl)[\"\']")


def check_deployed_paths_have_a_reader(root: Path = REPO_ROOT) -> list[str]:
    """Return failures for paths written into a target that nothing accounts for.

    A hook that writes a file into a target repo is only half a feature. The
    other half is something able to read it, and that something is either
    carried to the target or explicitly recorded as staying here.
    """
    hooks_dir = root / "hooks"
    if not hooks_dir.is_dir():
        return []

    failures = []
    for hook in sorted(hooks_dir.glob("*.py")):
        text = hook.read_text(encoding="utf-8")
        for match in _WRITES_INTO_TARGET.findall(text):
            if match not in DEPLOYED_PATH_READERS:
                failures.append(
                    f"{hook.name} writes {match} into every target repo, and "
                    f"DEPLOYED_PATH_READERS does not say what reads it. Half a feature: "
                    f"targets collect data nobody can open. Name the reader, or stop "
                    f"writing the file."
                )
    return failures


#: Executables the plugin puts on PATH. Claude Code appends a plugin's ``bin/``
#: to PATH, which is the only way an agent can name a tool of ours without
#: knowing where the plugin was checked out — ``${CLAUDE_PLUGIN_ROOT}`` is not
#: exported to the Bash tool, and an absolute path is wrong the moment the
#: plugin moves.
PLUGIN_BIN = REPO_ROOT / "bin"


def check_agent_commands_are_deployed(root: Path = REPO_ROOT) -> list[str]:
    """Return failures for tools an agent is told to run but would not have.

    An agent prompt naming a command is a promise that the command exists where
    the agent runs. devops was told to run the merge gate in a target repo
    while the gate stayed here, so the instruction resolved to
    ModuleNotFoundError at the moment of the merge.

    The installer no longer delivers scripts at all, so a repo-relative path in
    an agent prompt is now always broken: it can only resolve in area54. Tools
    reach a target through ``bin/``.
    """
    agents_dir = root / "agents"
    if not agents_dir.is_dir():
        return []

    referenced = re.compile(r"(\.claude/[\w./-]+\.(?:py|sh))")
    failures = []
    for agent in sorted(agents_dir.glob("*.md")):
        for path in sorted(set(referenced.findall(agent.read_text(encoding="utf-8")))):
            failures.append(
                f"{agent.name}: tells the agent to run {path}. The installer does not copy "
                f"scripts any more — put the tool in bin/ and name it, so it resolves on "
                f"PATH in every repo the plugin is installed in."
            )
    return failures


#: The spelling of a tool that only resolves inside area54. A target repo has no
#: `tools` package, so anything telling an agent to run one of these is telling
#: it to fail — and the failure reads as the tool refusing rather than the
#: instruction being wrong.
AREA54_ONLY = "python -m tools."


def check_hook_messages_name_a_command_that_exists(root: Path = REPO_ROOT) -> list[str]:
    """Return failures for hook text telling an agent to run an area54-only tool.

    A hook runs in the target repo, and what it prints is an instruction the
    agent follows. The shell guard refused a merge and told the agent to run
    `python -m tools.merge_gate` — correct here, `No module named tools` there,
    at the one irreversible step in the pipeline.

    :func:`check_agent_commands_are_deployed` could not have caught it: that one
    reads agent prompts, and this was a string inside a hook.
    """
    hooks_dir = root / "hooks"
    if not hooks_dir.is_dir():
        return []
    return [
        f"hooks/{hook.name}: names `{AREA54_ONLY}...`, which does not exist in a target "
        f"repo. Hook output is an instruction the agent follows — name the bin/ command."
        for hook in sorted(hooks_dir.glob("*.py"))
        if AREA54_ONLY in hook.read_text(encoding="utf-8")
    ]


def check_agent_commands_are_permitted(settings: Settings, root: Path = REPO_ROOT) -> list[str]:
    """Return failures for bin/ tools an agent is told to run but cannot.

    Half the pipeline's autonomy is the permission list. A tool that travels,
    resolves on PATH, and is not auto-approved stops a headless run dead — and
    only in a target repo, because in area54 the source spelling is covered by
    a different rule. That asymmetry is what makes it invisible here.
    """
    bin_dir = root / "bin"
    agents_dir = root / "agents"
    if not bin_dir.is_dir() or not agents_dir.is_dir():
        return []

    prompts = "\n".join(a.read_text(encoding="utf-8") for a in sorted(agents_dir.glob("*.md")))
    failures = []
    for entry in sorted(bin_dir.iterdir()):
        if not entry.is_file() or entry.name not in prompts:
            continue
        if not any(rule.startswith(f"Bash({entry.name}") for rule in settings.allow):
            failures.append(
                f"settings.json: an agent is told to run `{entry.name}`, and no allow rule "
                f"covers it. Prefix matching cannot reach it from any other rule, so a "
                f"headless run in a target repo refuses the call and stops."
            )
    return failures


def validate(path: Path = SETTINGS_PATH) -> list[str]:
    """Run every settings check. Returns all failures."""
    settings = load_settings(path)
    hook_commands = load_hook_commands()
    return [
        *check_required_denies_survive(settings),
        *check_a_guard_backs_the_push_rules(settings, hook_commands),
        *check_referenced_files_exist(hook_commands),
        *check_hook_scripts_travel_with_the_plugin(hook_commands),
        *check_hooks_are_configured_once(settings),
        *check_the_repo_installs_its_own_plugin(settings),
        *check_deployed_paths_have_a_reader(),
        *check_agent_commands_are_deployed(),
        *check_hook_messages_name_a_command_that_exists(),
        *check_agent_commands_are_permitted(settings),
    ]
