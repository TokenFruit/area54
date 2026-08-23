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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = REPO_ROOT / ".claude" / "settings.json"

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


def _project_relative(token: str) -> str:
    """Strip the project-dir prefix from a hook path.

    Deliberately not `lstrip("./")`: that strips a character *set*, so
    ``.claude/hooks/x.py`` becomes ``claude/hooks/x.py`` and every lookup
    misses. This function exists because that is exactly what happened.
    """
    return token.replace("$CLAUDE_PROJECT_DIR/", "").removeprefix("./")


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
        commands: list[str] = []
        for entries in self.data.get("hooks", {}).values():
            for entry in entries:
                for hook in entry.get("hooks", []):
                    if hook.get("type") == "command":
                        commands.append(str(hook.get("command", "")))
        return commands


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


def check_a_guard_backs_the_push_rules(settings: Settings) -> list[str]:
    """Return a failure if `git push` is auto-approved with no hook watching.

    Prefix matching cannot express "push anywhere except main". If the allow
    list grants `git push` at all, something that reads the whole command has
    to be watching it.
    """
    grants_push = any(
        rule.startswith(("Bash(git push", "Bash(gh pr merge")) for rule in settings.allow
    )
    if not grants_push:
        return []
    if not any("guard_bash" in command for command in settings.hook_commands):
        return [
            "settings.json: `git push` is auto-approved but no guard hook is configured. "
            "Prefix rules cannot express 'anywhere except main' — `git push -u origin main` "
            "matches an allow rule for `git push -u origin` and misses a deny rule for "
            "`git push origin main`. Configure .claude/hooks/guard_bash.py as a PreToolUse hook."
        ]
    return []


def check_referenced_files_exist(settings: Settings, root: Path = REPO_ROOT) -> list[str]:
    """Return failures for hook scripts the settings name but the repo lacks.

    A hook that is configured and missing fails at the moment it was supposed
    to protect something.
    """
    failures = []
    for command in settings.hook_commands:
        for token in command.replace('"', " ").split():
            if token.endswith(".py") or token.endswith(".sh"):
                relative = _project_relative(token)
                if not (root / relative).is_file():
                    failures.append(
                        f"settings.json: hook references {relative}, which does not exist. "
                        f"A hook that is configured and missing is worse than no hook."
                    )
    return failures


def check_referenced_files_are_deployed(settings: Settings) -> list[str]:
    """Return failures for hook scripts the installer would not carry.

    This is the defect that shipped: settings.json travelled to a target repo
    and the hook it named did not.
    """
    from tools.deploy import PAYLOAD

    sources = [src for src, _ in PAYLOAD]
    failures = []
    for command in settings.hook_commands:
        for token in command.replace('"', " ").split():
            if token.endswith(".py") or token.endswith(".sh"):
                relative = _project_relative(token)
                if not any(relative == src or relative.startswith(f"{src}/") for src in sources):
                    failures.append(
                        f"settings.json: hook references {relative}, which the deploy PAYLOAD "
                        f"does not carry. Target repos would get the setting without the script."
                    )
    return failures


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


def check_deployed_paths_have_a_reader(root: Path = REPO_ROOT) -> list[str]:
    """Return failures for deployed paths nothing accounts for.

    A hook that writes a file into a target repo is only half a feature. The
    other half is something able to read it, and that something is either in
    the payload or explicitly recorded as staying here.
    """
    from tools.deploy import PAYLOAD

    hooks_dir = root / ".claude" / "hooks"
    if not hooks_dir.is_dir():
        return []

    sources = [src for src, _ in PAYLOAD]
    failures = []
    for hook in sorted(hooks_dir.glob("*.py")):
        text = hook.read_text(encoding="utf-8")
        for path, _ in DEPLOYED_PATH_READERS.items():
            if path.rsplit("/", 1)[-1] in text:
                break
        else:
            # The hook writes nothing we track; nothing to account for.
            continue
        deployed = any(
            str(hook.relative_to(root)) == src or str(hook.relative_to(root)).startswith(f"{src}/")
            for src in sources
        )
        if not deployed:
            failures.append(f"{hook.name} writes a tracked path but is not in the deploy PAYLOAD.")
    return failures


def validate(path: Path = SETTINGS_PATH) -> list[str]:
    """Run every settings check. Returns all failures."""
    settings = load_settings(path)
    return [
        *check_required_denies_survive(settings),
        *check_a_guard_backs_the_push_rules(settings),
        *check_referenced_files_exist(settings),
        *check_referenced_files_are_deployed(settings),
        *check_deployed_paths_have_a_reader(),
    ]
