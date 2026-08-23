"""Install the team into a target repository.

area54 is not yet packaged as a Claude Code plugin (TF-003), so deployment is a
copy. That makes drift the thing to design against: a copied file can be edited
in the target, and then the next deployment silently reverts it, or worse does
not and the two repos quietly disagree about how the team works.

Three defences. Every installed file is recorded with the area54 commit it came
from, so `--check` can tell you what is stale. Local edits are detected and
reported rather than overwritten without comment. And the installed constitution
opens by saying it is deployed and must not be edited here.

    python -m tools.deploy /path/to/repo --dry-run
    python -m tools.deploy /path/to/repo
    python -m tools.deploy /path/to/repo --check
"""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: What a target repo receives. Everything else stays in area54.
PAYLOAD: tuple[tuple[str, str], ...] = (
    (".claude/agents", ".claude/agents"),
    (".claude/commands", ".claude/commands"),
    ("team/TEAM.md", ".claude/TEAM.md"),
    (".github/pull_request_template.md", ".github/pull_request_template.md"),
)

#: Created empty so the team has somewhere to put its artefacts.
ARTEFACT_DIRS = ("docs/specs", "docs/adr", "docs/design")

VERSION_FILE = ".claude/TEAM_VERSION"


class DeployError(Exception):
    """The target is not in a state where installing would be safe."""


@dataclass(frozen=True)
class Change:
    """One file the installer would write."""

    path: str
    kind: str  # "new" | "update" | "unchanged" | "locally-edited"


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


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


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


def _file_pairs() -> list[tuple[Path, str]]:
    """Return every (source file, target-relative path) the payload expands to."""
    pairs: list[tuple[Path, str]] = []
    for src_rel, dst_rel in PAYLOAD:
        src = REPO_ROOT / src_rel
        if src.is_dir():
            for path in sorted(src.rglob("*")):
                if path.is_file():
                    pairs.append((path, f"{dst_rel}/{path.relative_to(src)}"))
        elif src.is_file():
            pairs.append((src, dst_rel))
        else:
            raise DeployError(f"payload entry missing from area54: {src_rel}")
    return pairs


def plan(target: Path) -> list[Change]:
    """Return what an installation would do, without doing it."""
    manifest = read_manifest(target)
    changes: list[Change] = []
    for src, rel in _file_pairs():
        dst = target / rel
        if not dst.exists():
            changes.append(Change(rel, "new"))
        elif filecmp.cmp(src, dst, shallow=False):
            changes.append(Change(rel, "unchanged"))
        elif rel in manifest and manifest[rel] != _digest(dst):
            changes.append(Change(rel, "locally-edited"))
        else:
            changes.append(Change(rel, "update"))
    return changes


def install(target: Path, force: bool = False) -> list[Change]:
    """Install the team into *target*. Returns what changed."""
    ensure_target_is_safe(target)
    changes = plan(target)

    edited = [c for c in changes if c.kind == "locally-edited"]
    if edited and not force:
        raise DeployError(
            "these files were edited in the target since the last install:\n  "
            + "\n  ".join(c.path for c in edited)
            + "\n\nThe team is maintained in area54, not here. Move the change there and "
            "redeploy, or pass --force to discard the local edits."
        )

    for src, rel in _file_pairs():
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    for directory in ARTEFACT_DIRS:
        (target / directory).mkdir(parents=True, exist_ok=True)
        keep = target / directory / ".gitkeep"
        if not keep.exists():
            keep.write_text("", encoding="utf-8")

    lines = [
        f"# The Token Fruit engineering team, installed from area54 @ {source_version()}",
        "# Do not edit these files here. Change them in area54 and redeploy.",
        "# Regenerate with: python -m tools.deploy <this repo>",
    ]
    lines += [f"{_digest(target / rel)} {rel}" for _, rel in _file_pairs()]
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
    print(f"Review the diff and commit it in {target.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
