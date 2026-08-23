"""Install the team into a target repository.

The team travels as a **Claude Code plugin** (`.claude-plugin/plugin.json`), so
the agents, the slash commands, the hooks and the merge gate are no longer
copied anywhere. A target repo names the marketplace and enables the plugin;
a prompt fix reaches every repo by version bump.

What still has to be written into the target, and why each one resists the
plugin mechanism:

* ``.claude/settings.json`` — the permission allow-list. `plugin.json` accepts a
  ``settings`` record and `claude plugin validate` passes it, but the runtime
  ignores it: on CLI 2.1.241 a plugin-declared ``deny`` did not block the
  command it named. Half the pipeline's autonomy lives in this list, so it is
  written as a settings file, not trusted to the manifest. The same file carries
  the two keys that install the plugin.
* ``.claude/TEAM.md`` — the constitution. A plugin cannot ship project context;
  `claude plugin validate` says as much and points at skills instead, which load
  on demand rather than always. Until that is designed, the constitution is a
  file.
* ``.github/pull_request_template.md`` — GitHub reads it from the repo.

That leaves eighteen files that used to be copied and are not any more. Drift is
still the thing to design against for the three that remain: every written file
is recorded with the area54 commit it came from, local edits are reported rather
than overwritten, and the constitution opens by saying it is deployed.

    python -m tools.deploy /path/to/repo --dry-run
    python -m tools.deploy /path/to/repo
    python -m tools.deploy /path/to/repo --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The marketplace a target repo installs the team from, and the plugin in it.
#: Both names are read back out of the checked-in manifests rather than spelled
#: twice — a marketplace whose name drifts from its manifest installs nothing.
MARKETPLACE_SOURCE = {"source": "github", "repo": "TokenFruit/area54"}

#: Files copied verbatim. Everything the plugin can carry is not in this list.
PAYLOAD: tuple[tuple[str, str], ...] = (
    ("team/TEAM.md", ".claude/TEAM.md"),
    (".github/pull_request_template.md", ".github/pull_request_template.md"),
)

#: Created empty so the team has somewhere to put its artefacts.
ARTEFACT_DIRS = ("docs/specs", "docs/adr", "docs/design")

VERSION_FILE = ".claude/TEAM_VERSION"
SETTINGS_FILE = ".claude/settings.json"

PLUGIN_MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_MANIFEST = REPO_ROOT / ".claude-plugin" / "marketplace.json"


class DeployError(Exception):
    """The target is not in a state where installing would be safe."""


@dataclass(frozen=True)
class Change:
    """One file the installer would write."""

    path: str
    kind: str  # "new" | "update" | "unchanged" | "locally-edited" | "conflict"


def plugin_manifest() -> dict[str, object]:
    """Return the plugin manifest area54 ships as."""
    try:
        data = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:  # pragma: no cover - the file is committed
        raise DeployError(f"plugin manifest missing: {PLUGIN_MANIFEST}") from exc
    if not isinstance(data, dict):
        raise DeployError(f"{PLUGIN_MANIFEST.name}: not a mapping.")
    return data


def marketplace_manifest() -> dict[str, object]:
    """Return the marketplace manifest area54 publishes itself through."""
    try:
        data = json.loads(MARKETPLACE_MANIFEST.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:  # pragma: no cover - the file is committed
        raise DeployError(f"marketplace manifest missing: {MARKETPLACE_MANIFEST}") from exc
    if not isinstance(data, dict):
        raise DeployError(f"{MARKETPLACE_MANIFEST.name}: not a mapping.")
    return data


def plugin_reference() -> str:
    """Return the ``plugin@marketplace`` id a target repo enables."""
    return f"{plugin_manifest()['name']}@{marketplace_manifest()['name']}"


def target_settings() -> str:
    """Return the settings file a target repo receives.

    Generated rather than copied. area54's own settings install the plugin from
    the working copy — a relative directory source, so the file is
    machine-independent and can be committed. A target repo installs the same
    plugin from GitHub. The permission list is identical in both, and that is
    the point: the rules an agent runs under here are the rules it runs under
    anywhere.
    """
    ours = json.loads((REPO_ROOT / SETTINGS_FILE).read_text(encoding="utf-8"))
    marketplace = str(marketplace_manifest()["name"])
    settings = {
        "$schema": ours["$schema"],
        "extraKnownMarketplaces": {marketplace: {"source": MARKETPLACE_SOURCE}},
        "enabledPlugins": {plugin_reference(): True},
        "permissions": ours["permissions"],
    }
    return json.dumps(settings, indent=2) + "\n"


def source_version() -> str:
    """Return the area54 commit being deployed, or a marker if unknown."""
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"
    return result.stdout.strip()


def _digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _digest(path: Path) -> str:
    return _digest_bytes(path.read_bytes())


def read_manifest(target: Path) -> dict[str, str]:
    """Return ``{relative path: digest}`` recorded by the last installation."""
    manifest = target / VERSION_FILE
    if not manifest.is_file():
        return {}
    entries: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or " " not in line:
            continue
        digest, _, path = line.partition(" ")
        entries[path.strip()] = digest.strip()
    return entries


def ensure_target_is_safe(target: Path) -> None:
    """Refuse to install over uncommitted work.

    Installing writes several files at once. If the target has uncommitted
    changes, an unwanted result cannot be undone with `git checkout .` without
    destroying whatever else was in progress.
    """
    if not target.is_dir():
        raise DeployError(f"{target} is not a directory.")
    if not (target / ".git").exists():
        raise DeployError(f"{target} is not a git repository. Refusing to install.")
    result = subprocess.run(  # noqa: S603
        ["git", "-C", str(target), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stdout.strip():
        raise DeployError(
            f"{target} has uncommitted changes. Commit or stash them first — installing "
            f"writes several files, and a bad result should be revertible without "
            f"destroying other work in progress."
        )


def _file_contents() -> list[tuple[bytes, str]]:
    """Return every (content, target-relative path) the installation writes."""
    contents: list[tuple[bytes, str]] = []
    for src_rel, dst_rel in PAYLOAD:
        src = REPO_ROOT / src_rel
        if src.is_dir():
            for path in sorted(src.rglob("*")):
                if path.is_file():
                    contents.append((path.read_bytes(), f"{dst_rel}/{path.relative_to(src)}"))
        elif src.is_file():
            contents.append((src.read_bytes(), dst_rel))
        else:
            raise DeployError(f"payload entry missing from area54: {src_rel}")
    contents.append((target_settings().encode("utf-8"), SETTINGS_FILE))
    return contents


def plan(target: Path) -> list[Change]:
    """Return what an installation would do, without doing it."""
    manifest = read_manifest(target)
    changes: list[Change] = []
    for data, rel in _file_contents():
        dst = target / rel
        if not dst.exists():
            changes.append(Change(rel, "new"))
        elif dst.read_bytes() == data:
            changes.append(Change(rel, "unchanged"))
        elif rel not in manifest:
            # Present, different, and not ours: the target had its own before we
            # ever ran. Overwriting it discards work nobody asked us to touch.
            changes.append(Change(rel, "conflict"))
        elif manifest[rel] != _digest(dst):
            changes.append(Change(rel, "locally-edited"))
        else:
            changes.append(Change(rel, "update"))
    return changes


def install(target: Path, force: bool = False) -> list[Change]:
    """Install the team into *target*. Returns what changed."""
    ensure_target_is_safe(target)
    changes = plan(target)

    conflicts = [c for c in changes if c.kind == "conflict"]
    if conflicts and not force:
        raise DeployError(
            "the target already has these files, and this installer did not write them:\n  "
            + "\n  ".join(c.path for c in conflicts)
            + "\n\nThey belong to the target repo. Merge what you need by hand, then "
            "re-run — or pass --force to replace them, which discards their contents."
        )

    edited = [c for c in changes if c.kind == "locally-edited"]
    if edited and not force:
        raise DeployError(
            "these files were edited in the target since the last install:\n  "
            + "\n  ".join(c.path for c in edited)
            + "\n\nThe team is maintained in area54, not here. Move the change there and "
            "redeploy, or pass --force to discard the local edits."
        )

    for data, rel in _file_contents():
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)

    for directory in ARTEFACT_DIRS:
        (target / directory).mkdir(parents=True, exist_ok=True)
        keep = target / directory / ".gitkeep"
        if not keep.exists():
            keep.write_text("", encoding="utf-8")

    version = str(plugin_manifest()["version"])
    lines = [
        f"# The Token Fruit engineering team, installed from area54 @ {source_version()}",
        f"# The team itself is the {plugin_reference()} plugin, version {version}.",
        "# Update it with: claude plugin update area54",
        "# Do not edit these files here. Change them in area54 and redeploy.",
        "# Regenerate with: python -m tools.deploy <this repo>",
    ]
    lines += [f"{_digest_bytes(data)} {rel}" for data, rel in _file_contents()]
    (target / VERSION_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")

    return [c for c in changes if c.kind != "unchanged"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools.deploy", description=__doc__)
    parser.add_argument("target", help="path to the target repository")
    parser.add_argument("--dry-run", action="store_true", help="show the plan, change nothing")
    parser.add_argument("--check", action="store_true", help="exit 1 if the target is out of date")
    parser.add_argument("--force", action="store_true", help="overwrite files edited in the target")
    args = parser.parse_args(argv)

    target = Path(args.target).expanduser().resolve()

    try:
        if args.dry_run or args.check:
            if not target.is_dir():
                raise DeployError(f"{target} is not a directory.")
            changes = plan(target)
        else:
            changes = install(target, force=args.force)
    except DeployError as exc:
        print(f"::error::{exc}")
        return 1

    pending = [c for c in changes if c.kind != "unchanged"]
    if args.dry_run or args.check:
        for change in sorted(pending, key=lambda c: (c.kind, c.path)):
            print(f"  {change.kind:15} {change.path}")
        if not pending:
            print(f"{target.name} is up to date with area54 @ {source_version()}.")
            return 0
        print(f"\n{len(pending)} file(s) would change.")
        return 1 if args.check else 0

    for change in sorted(pending, key=lambda c: (c.kind, c.path)):
        print(f"  {change.kind:15} {change.path}")
    print(f"\nInstalled the team into {target.name} from area54 @ {source_version()}.")
    print(
        f"The team arrives as the {plugin_reference()} plugin. Start a session in "
        f"{target.name} and run `claude plugin details area54` to confirm it loaded."
    )
    print(f"Review the diff and commit it in {target.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
