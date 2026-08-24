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
    kind: str  # new | update | unchanged | locally-edited | conflict | superseded[-edited]


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


#: Where Claude Code records marketplaces. The key is the marketplace **name**,
#: globally, and the first registration wins — a second repo declaring the same
#: name with a different source is dropped without a message.
KNOWN_MARKETPLACES = Path.home() / ".claude" / "plugins" / "known_marketplaces.json"


def registered_source(name: str, registry: Path = KNOWN_MARKETPLACES) -> dict[str, str] | None:
    """Return the source already registered under *name* on this machine."""
    try:
        data = json.loads(registry.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    entry = data.get(name)
    if not isinstance(entry, dict) or not isinstance(entry.get("source"), dict):
        return None
    return {str(k): str(v) for k, v in entry["source"].items()}


def marketplace_collision(registry: Path = KNOWN_MARKETPLACES) -> str | None:
    """Return a warning if this machine already means something else by the name.

    ``extraKnownMarketplaces`` does not create a per-project marketplace. area54
    registers `tokenfruit` as its own working copy so it can run the team it is
    editing; a target repo asks for the same name and gets the working copy
    instead of GitHub — silently, and only on this machine.

    That is not hypothetical: it is why the first live verification of this
    installer was served from the previous commit rather than from the branch it
    was verifying. The collision is a property of the platform and cannot be
    designed away here — two marketplace names would need two marketplace roots,
    and a plugin source may not contain "..". So it is detected and said out
    loud instead.
    """
    name = str(marketplace_manifest()["name"])
    existing = registered_source(name, registry)
    if existing is None or existing == MARKETPLACE_SOURCE:
        return None
    described = existing.get("path") or existing.get("repo") or str(existing)
    return (
        f"`{name}` is already registered on this machine as {existing.get('source')} "
        f"{described}, and the first registration wins. A session in the target will load "
        f"the team from there, not from {MARKETPLACE_SOURCE['repo']} — so "
        f"`claude plugin update` will not update it, and uncommitted edits in that checkout "
        f"are live in the target.\n"
        f"  On a machine that only consumes the team, run "
        f"`claude plugin marketplace remove {name}` once and it will resolve to GitHub.\n"
        f"  On this one, where area54 is being developed, that is the intended behaviour — "
        f"but the target is running your working copy. Say so before trusting a result."
    )


def _one_line(message: str) -> str:
    """Escape newlines for a GitHub Actions annotation.

    `::warning::` is parsed up to the first newline, so a multi-line message
    arrives as its first sentence with the remedy scattered into plain log text
    below it — which is where the advice is needed and where nobody looks.
    """
    return message.replace("\n", "%0A")


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
    for rel in superseded(target):
        # The payload path refuses to overwrite a file the target edited, at
        # length. A file that is going away deserves the same answer: "we refuse
        # to discard your edit" and "we discard your edit silently" should not
        # both be true of one command.
        edited = manifest.get(rel) != _digest(target / rel)
        changes.append(Change(rel, "superseded-edited" if edited else "superseded"))
    return changes


def superseded(target: Path) -> list[str]:
    """Return files a previous installation wrote that this one no longer writes.

    Every already-deployed repo has eighteen of them: the agents, commands and
    hooks that used to be copied. Leaving them is not merely untidy —
    ``.claude/agents/`` is a directory Claude Code discovers by convention, so a
    frozen copy of all eight prompts keeps loading alongside the plugin's, and
    the repo runs two teams that can disagree. Migrating those repos is what
    TF-003 is for, so the migration is part of installing rather than a note in
    a README.

    Only paths the recorded manifest claims are removed, and only paths that
    resolve inside the target. Anything this installer did not write is not ours
    to delete — and ``.claude/TEAM_VERSION`` lives in the target, so however it
    got there it is not trusted input. A line reading ``../victim.txt`` would
    otherwise escape, and the directory walk that follows would climb above the
    target root removing whatever it emptied.
    """
    ours = set(read_manifest(target))
    current = {rel for _, rel in _file_contents()}
    return sorted(rel for rel in ours - current if _contained(target, rel))


def _contained(target: Path, rel: str) -> bool:
    """Return whether *rel* names an existing file inside *target*.

    Containment by resolved path, not by inspecting the string for ``..``:
    a symlink, an absolute path and an encoded traversal all have to fail the
    same test, and only resolution catches all three.
    """
    root = target.resolve()
    path = (target / rel).resolve()
    if path == root or root not in path.parents:
        return False
    # `is_file`, not `exists`: a manifest entry naming a directory reached
    # `_digest` and raised IsADirectoryError out of `plan()`, so `--check` and
    # `--dry-run` crashed on a target nobody could have known was malformed.
    # Fail-safe — the target was unmodified — but a crash is not a diagnosis.
    return (target / rel).is_file()


def _prune(target: Path, paths: list[str]) -> None:
    """Delete *paths* and any directory they leave empty.

    Containment is re-checked here rather than trusted from the caller. Mutation
    testing found the guard that was here unreachable — `_contained` filtered
    everything at the single call site, so this function deleted whatever it was
    handed, and `_contained` was a single point of failure. A second caller
    would have reintroduced the traversal with no test to catch it.

    The upward walk stops by containment rather than by equality with the
    target: an equality test cannot terminate on a parent that is already
    outside it.
    """
    root = target.resolve()
    for rel in paths:
        if not _contained(target, rel):
            continue
        path = target / rel
        path.unlink(missing_ok=True)
        parent = path.parent
        # An empty `.claude/agents` still loads as a component directory, so the
        # directory has to go too — but never the target, and never above it.
        while (
            parent.resolve() != root
            and root in parent.resolve().parents
            and parent.is_dir()
            and not any(parent.iterdir())
        ):
            parent.rmdir()
            parent = parent.parent


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

    edited = [c for c in changes if c.kind in ("locally-edited", "superseded-edited")]
    if edited and not force:
        raise DeployError(
            "these files were edited in the target since the last install:\n  "
            + "\n  ".join(c.path for c in edited)
            + "\n\nThe team is maintained in area54, not here. Move the change there and "
            "redeploy, or pass --force to discard the local edits."
        )

    _prune(target, [c.path for c in changes if c.kind.startswith("superseded")])

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
        collision = marketplace_collision()
        if collision:
            print(f"::warning::{_one_line(collision)}")
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
    collision = marketplace_collision()
    if collision:
        print(f"\n::warning::{_one_line(collision)}")
    print(f"\nReview the diff and commit it in {target.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
