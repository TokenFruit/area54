"""Validate the packaging, because CI cannot run the packager.

area54 ships as a Claude Code plugin. `claude plugin validate --strict` is the
authority on the manifests, but it needs the CLI and an authenticated session,
and CI has neither. What is checked here is the part that breaks silently: a
plugin whose manifests are valid JSON, pass the CLI's own validator, and load
**nothing**.

Every rule below was established by installing the plugin and reading
`claude plugin details` — not from the schema, which accepts several shapes the
runtime ignores:

* Components are found by **convention**, not by manifest. An ``agents`` field
  listing files validates and loads zero agents; a top-level ``agents/``
  directory with no manifest field loads all eight.
* ``hooks/hooks.json`` must wrap its events in a top-level ``hooks`` key.
  Without the wrapper the file is read and configures nothing.
* A ``settings`` record in ``plugin.json`` validates and is ignored at load
  time, so the permission list cannot travel that way.

The one warning `--strict` reports here is known and accepted: ``CLAUDE.md`` at
the plugin root is not loaded as project context. area54's repo root *is* the
plugin root, and area54 needs its own constitution as project context. The
constitution that travels is ``team/TEAM.md``, which the installer writes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

PLUGIN_MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_MANIFEST = REPO_ROOT / ".claude-plugin" / "marketplace.json"
HOOKS_MANIFEST = REPO_ROOT / "hooks" / "hooks.json"

#: Directories Claude Code discovers by convention, and what each must contain.
#: The count is not pinned — adding a role should not need this file edited —
#: but an empty directory means the component type silently vanished.
COMPONENT_DIRS = {"agents": "*.md", "commands": "*.md"}

#: Fields the manifest must carry. `version` is the whole distribution story:
#: "a prompt fix reaches every product repo by version bump" is false without
#: something to bump.
REQUIRED_FIELDS = ("name", "version", "description", "author")

#: The CLI these measurements were taken against. They are properties of a
#: version, not of the format, and the format is young — ADR-0001 says so. When
#: this no longer matches `claude --version`, the failure message says to
#: re-measure rather than leaving someone to argue with a rule whose reason
#: expired two releases ago. Re-measure by declaring the field, installing into
#: a scratch repo, and reading `claude plugin details`.
MEASURED_AGAINST = "2.1.241"

#: Manifest fields that validate but do nothing, with what to do instead.
#: Each was measured, not assumed.
INERT_FIELDS = {
    "agents": "components are discovered from the agents/ directory; a file list loads none",
    "commands": "components are discovered from the commands/ directory",
    "skills": "components are discovered from the skills/ directory",
    "settings": (
        "accepted by `claude plugin validate` and ignored at load time — a plugin-declared "
        "deny did not block the command it named on CLI 2.1.241. Permissions belong in "
        ".claude/settings.json, which tools/deploy.py writes"
    ),
}


class PluginError(Exception):
    """The plugin manifests are missing or malformed."""


def _relative(path: Path) -> str:
    """Return *path* relative to the repo when it is inside it, else as given."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise PluginError(f"{_relative(path)} is missing. area54 is the plugin.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PluginError(f"{path.name}: not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise PluginError(f"{path.name}: not a mapping.")
    return data


def load_plugin(path: Path = PLUGIN_MANIFEST) -> dict[str, Any]:
    """Return the parsed plugin manifest."""
    return _load(path)


def load_marketplace(path: Path = MARKETPLACE_MANIFEST) -> dict[str, Any]:
    """Return the parsed marketplace manifest."""
    return _load(path)


def check_required_fields(manifest: dict[str, Any]) -> list[str]:
    """Return failures for manifest fields the distribution story needs."""
    return [
        f"plugin.json: `{field}` is missing."
        for field in REQUIRED_FIELDS
        if not manifest.get(field)
    ]


def check_no_inert_fields(manifest: dict[str, Any]) -> list[str]:
    """Return failures for fields that validate but change nothing.

    These are worse than errors. `claude plugin validate` passes them, so the
    packaging looks correct while the component it claims to declare is not
    loaded at all.
    """
    return [
        f"plugin.json: `{field}` has no effect — {why}. Measured on CLI "
        f"{MEASURED_AGAINST}; if the CLI has moved on, re-measure before deleting this "
        f"rule, and re-measure before working around it."
        for field, why in INERT_FIELDS.items()
        if field in manifest
    ]


def check_components_exist(root: Path = REPO_ROOT) -> list[str]:
    """Return failures for component directories that are missing or empty."""
    failures = []
    for directory, pattern in COMPONENT_DIRS.items():
        path = root / directory
        if not path.is_dir():
            failures.append(
                f"{directory}/ is missing. Claude Code discovers components by convention; "
                f"no directory means no {directory}."
            )
        elif not any(path.glob(pattern)):
            failures.append(f"{directory}/ contains no {pattern}, so the plugin loads none.")
    return failures


def check_hooks_are_wrapped(path: Path = HOOKS_MANIFEST) -> list[str]:
    """Return a failure if hooks.json omits its top-level ``hooks`` key.

    Measured: without the wrapper `claude plugin details` reports ``Hooks (0)``
    and nothing else complains. The guard that stops a push to main would be
    configured, valid, and absent.
    """
    if not path.is_file():
        return [f"{_relative(path)} is missing; the plugin configures no hooks."]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"hooks.json: not valid JSON: {exc}"]
    if not isinstance(data, dict) or not isinstance(data.get("hooks"), dict):
        return [
            "hooks.json: needs a top-level `hooks` key wrapping the events. Without it the "
            "file parses, loads, and configures nothing — measured, not theorised."
        ]
    if not data["hooks"]:
        return ["hooks.json: the `hooks` object is empty."]
    return []


def check_hook_commands_use_the_plugin_root(path: Path = HOOKS_MANIFEST) -> list[str]:
    """Return failures for hook commands written against the wrong root.

    A plugin's hooks run from an arbitrary checkout directory.
    ``$CLAUDE_PROJECT_DIR`` is the repo being worked on, so a hook written that
    way looks for the team's own scripts inside the customer's repo and does not
    find them.
    """
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    failures = []
    for entries in data.get("hooks", {}).values():
        for entry in entries:
            for hook in entry.get("hooks", []):
                command = str(hook.get("command", ""))
                if ".py" not in command and ".sh" not in command:
                    continue
                if "CLAUDE_PLUGIN_ROOT" not in command:
                    failures.append(
                        f"hooks.json: `{command}` does not resolve against "
                        f"${{CLAUDE_PLUGIN_ROOT}}. In a target repo it points at a path that "
                        f"does not exist."
                    )
    return failures


def check_marketplace_agrees(manifest: dict[str, Any], marketplace: dict[str, Any]) -> list[str]:
    """Return failures where the marketplace entry and the plugin disagree.

    `claude plugin tag` refuses to cut a release when these drift, which is the
    right moment to find out — but only if someone runs it. This finds out on
    every push.
    """
    entries = marketplace.get("plugins", [])
    if not isinstance(entries, list) or not entries:
        return ["marketplace.json: lists no plugins."]
    names = [e.get("name") for e in entries if isinstance(e, dict)]
    if manifest.get("name") not in names:
        return [
            f"marketplace.json: does not list `{manifest.get('name')}`. It lists {names}. "
            f"The marketplace is how a target repo finds the plugin at all."
        ]
    failures = []
    for entry in entries:
        if entry.get("name") != manifest.get("name"):
            continue
        source = entry.get("source")
        if not isinstance(source, str) or not (REPO_ROOT / source).is_dir():
            failures.append(f"marketplace.json: source `{source}` is not a directory in this repo.")
        if "version" in entry and entry["version"] != manifest.get("version"):
            failures.append(
                f"marketplace.json: version {entry['version']} disagrees with plugin.json "
                f"{manifest.get('version')}. `claude plugin tag` refuses this."
            )
    return failures


def check_bin_is_executable(root: Path = REPO_ROOT) -> list[str]:
    """Return failures for tools on PATH that could not start."""
    bin_dir = root / "bin"
    if not bin_dir.is_dir():
        return []
    return [
        f"bin/{entry.name} is not executable, and is on PATH in every target repo."
        for entry in sorted(bin_dir.iterdir())
        if entry.is_file() and not os.access(entry, os.X_OK)
    ]


def validate() -> list[str]:
    """Run every packaging check. Returns all failures."""
    manifest = load_plugin()
    marketplace = load_marketplace()
    return [
        *check_required_fields(manifest),
        *check_no_inert_fields(manifest),
        *check_components_exist(),
        *check_hooks_are_wrapped(),
        *check_hook_commands_use_the_plugin_root(),
        *check_marketplace_agrees(manifest, marketplace),
        *check_bin_is_executable(),
    ]
