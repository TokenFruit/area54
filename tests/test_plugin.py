"""Tests for the packaging.

CI has no `claude` CLI, so none of these rules can lean on it. Two of them could
not lean on it anyway: a manifest that is valid, passes the CLI's own validator,
and loads **nothing**. Every rule asserted here was established by installing
the plugin into a scratch repo and reading `claude plugin details`, because the
schema accepts shapes the runtime ignores.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.plugin import (
    HOOKS_MANIFEST,
    INERT_FIELDS,
    PluginError,
    check_bin_is_executable,
    check_components_exist,
    check_hook_commands_use_the_plugin_root,
    check_hooks_are_wrapped,
    check_marketplace_agrees,
    check_no_inert_fields,
    check_required_fields,
    load_marketplace,
    load_plugin,
    validate,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


# --- what is actually shipped ---------------------------------------------


def test_the_shipped_packaging_validates() -> None:
    assert validate() == []


def test_the_repo_is_the_plugin() -> None:
    """area54 builds itself using itself, so its root is the plugin root."""
    manifest = load_plugin()
    assert manifest["name"] == "area54"
    assert (REPO_ROOT / ".claude-plugin" / "plugin.json").is_file()


def test_the_plugin_has_a_version_to_bump() -> None:
    """The whole distribution story is "a fix arrives by version bump"."""
    version = str(load_plugin()["version"])
    assert version.count(".") == 2
    assert all(part.isdigit() for part in version.split("."))


def test_the_marketplace_lists_the_plugin() -> None:
    """A marketplace that does not list it is a marketplace that installs nothing."""
    assert check_marketplace_agrees(load_plugin(), load_marketplace()) == []


def test_every_component_directory_is_where_the_runtime_looks() -> None:
    """Measured: an `agents` field listing files validates and loads zero agents.

    A top-level `agents/` directory with no manifest field loads all eight. The
    manifest is not how components are declared; convention is.
    """
    assert check_components_exist() == []
    assert len(list((REPO_ROOT / "agents").glob("*.md"))) == 8
    assert len(list((REPO_ROOT / "commands").glob("*.md"))) == 7


def test_the_manifest_declares_no_components() -> None:
    """Declaring them is worse than an error: it validates and loads nothing."""
    assert check_no_inert_fields(load_plugin()) == []


def test_the_shipped_hooks_are_wrapped() -> None:
    assert check_hooks_are_wrapped() == []


def test_the_shipped_hooks_resolve_against_the_plugin_root() -> None:
    assert check_hook_commands_use_the_plugin_root() == []


def test_the_shipped_bin_is_executable() -> None:
    assert check_bin_is_executable() == []


# --- the failures these checks exist to catch -----------------------------


def test_a_manifest_without_a_version_is_caught() -> None:
    failures = check_required_fields({"name": "x", "description": "d", "author": {"name": "a"}})
    assert len(failures) == 1
    assert "version" in failures[0]


@pytest.mark.parametrize("field", sorted(INERT_FIELDS))
def test_each_inert_field_is_caught(field: str) -> None:
    """These pass `claude plugin validate` and change nothing at load time."""
    failures = check_no_inert_fields({"name": "x", field: ["./whatever"]})
    assert len(failures) == 1
    assert "no effect" in failures[0]


def test_the_settings_field_is_called_out_with_where_permissions_go_instead() -> None:
    """It validates. A plugin-declared deny did not block the command it named."""
    assert "settings" in INERT_FIELDS
    assert ".claude/settings.json" in INERT_FIELDS["settings"]


def test_a_missing_component_directory_is_caught(tmp_path: Path) -> None:
    failures = check_components_exist(tmp_path)
    assert len(failures) == 2
    assert all("discovers components by convention" in f or "loads none" in f for f in failures)


def test_an_empty_component_directory_is_caught(tmp_path: Path) -> None:
    """The directory survives; the files in it do not. Nothing else notices."""
    (tmp_path / "agents").mkdir()
    (tmp_path / "commands").mkdir()
    (tmp_path / "commands" / "review.md").write_text("x", encoding="utf-8")
    failures = check_components_exist(tmp_path)
    assert len(failures) == 1
    assert "agents/ contains no *.md" in failures[0]


def test_an_unwrapped_hooks_file_is_caught(tmp_path: Path) -> None:
    """Measured: without the wrapper, `claude plugin details` reports Hooks (0).

    The guard that stops a push to main would be configured and absent. The CLI
    does catch this one when pointed at the plugin manifest — but CI has no CLI,
    and `claude plugin validate .` here resolves to the marketplace manifest and
    never reads the hooks.
    """
    path = tmp_path / "hooks.json"
    path.write_text(json.dumps({"PreToolUse": [{"matcher": "Bash"}]}), encoding="utf-8")
    failures = check_hooks_are_wrapped(path)
    assert len(failures) == 1
    assert "top-level `hooks` key" in failures[0]


def test_an_empty_hooks_object_is_caught(tmp_path: Path) -> None:
    path = tmp_path / "hooks.json"
    path.write_text(json.dumps({"hooks": {}}), encoding="utf-8")
    assert check_hooks_are_wrapped(path) == ["hooks.json: the `hooks` object is empty."]


def test_a_hook_written_against_the_project_dir_is_caught(tmp_path: Path) -> None:
    """`$CLAUDE_PROJECT_DIR` is the customer's repo, not the plugin's checkout."""
    path = tmp_path / "hooks.json"
    path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": 'python3 "$CLAUDE_PROJECT_DIR/hooks/guard.py"',
                                }
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    failures = check_hook_commands_use_the_plugin_root(path)
    assert len(failures) == 1
    assert "CLAUDE_PLUGIN_ROOT" in failures[0]


def test_a_marketplace_that_does_not_list_the_plugin_is_caught() -> None:
    failures = check_marketplace_agrees(
        {"name": "area54", "version": "0.1.0"},
        {"plugins": [{"name": "something-else", "source": "./"}]},
    )
    assert len(failures) == 1
    assert "does not list `area54`" in failures[0]


def test_a_version_disagreement_is_caught() -> None:
    """`claude plugin tag` refuses this — but only if somebody runs it."""
    failures = check_marketplace_agrees(
        {"name": "area54", "version": "0.2.0"},
        {"plugins": [{"name": "area54", "source": "./", "version": "0.1.0"}]},
    )
    assert len(failures) == 1
    assert "disagrees with plugin.json" in failures[0]


def test_a_bin_entry_without_the_executable_bit_is_caught(tmp_path: Path) -> None:
    """On PATH, and it refuses to start. To an agent that reads as not found."""
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "merge-gate").write_text("#!/bin/sh\n", encoding="utf-8")
    failures = check_bin_is_executable(tmp_path)
    assert len(failures) == 1
    assert "not executable" in failures[0]


def test_a_missing_manifest_is_a_hard_error(tmp_path: Path) -> None:
    with pytest.raises(PluginError, match="is missing"):
        load_plugin(tmp_path / "plugin.json")


def test_a_malformed_manifest_is_a_hard_error(tmp_path: Path) -> None:
    path = tmp_path / "plugin.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(PluginError, match="not valid JSON"):
        load_plugin(path)


# --- the packaging and the code agree -------------------------------------


def test_the_hook_scripts_the_manifest_names_exist() -> None:
    """Configured and missing is the failure that already shipped once."""
    data = json.loads(HOOKS_MANIFEST.read_text(encoding="utf-8"))
    named = [
        token.strip('"')
        for entries in data["hooks"].values()
        for entry in entries
        for hook in entry["hooks"]
        for token in hook["command"].replace('"', " ").split()
        if token.endswith(".py")
    ]
    assert named
    for path in named:
        assert (REPO_ROOT / path.replace("${CLAUDE_PLUGIN_ROOT}/", "")).is_file(), path


def test_the_inert_rule_says_what_it_was_measured_against() -> None:
    """A rule whose reason expired should say so, not just refuse.

    `check_no_inert_fields` fails on the presence of the key. When the CLI
    starts honouring plugin `settings`, moving the permission list there is the
    correct move — and this validator would refuse it, citing a measurement two
    versions old, with nothing telling anyone the reason had expired.
    """
    from tools.plugin import MEASURED_AGAINST

    failures = check_no_inert_fields({"settings": {"permissions": {}}})
    assert len(failures) == 1
    assert MEASURED_AGAINST in failures[0]
    assert "re-measure" in failures[0]


def test_the_bin_check_is_not_duplicated_in_the_roll_up() -> None:
    """It ran twice and reported every failure twice."""
    import tools.settings

    assert not hasattr(tools.settings, "check_plugin_bin_is_executable")
