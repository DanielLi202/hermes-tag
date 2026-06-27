import sys
import types

from hermes_tag import _ensure_slack_native_tag_command


def test_slack_native_tag_replaces_low_value_command_when_clamped(monkeypatch):
    pkg = types.ModuleType("hermes_cli")
    commands = types.ModuleType("hermes_cli.commands")
    commands._SLACK_MAX_SLASH_COMMANDS = 50

    def original():
        return [(f"cmd{i}", f"Command {i}", "") for i in range(47)] + [
            ("version", "Show Hermes Agent version", ""),
            ("usage", "Show usage", ""),
            ("insights", "Show insights", ""),
        ]

    commands.slack_native_slashes = original
    pkg.commands = commands
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.commands", commands)

    _ensure_slack_native_tag_command()

    patched = commands.slack_native_slashes()
    names = [name for name, _desc, _hint in patched]
    assert len(patched) == 50
    assert "tag" in names
    assert "version" not in names
    assert names.count("tag") == 1
    assert patched[names.index("tag")] == (
        "tag",
        "Hermes Tag commands",
        "help | status | admin count | standing ...",
    )


def test_slack_native_tag_patch_is_idempotent(monkeypatch):
    pkg = types.ModuleType("hermes_cli")
    commands = types.ModuleType("hermes_cli.commands")
    commands._SLACK_MAX_SLASH_COMMANDS = 50
    commands.slack_native_slashes = lambda: [("hermes", "Talk", ""), ("tag", "old", "")]
    pkg.commands = commands
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.commands", commands)

    _ensure_slack_native_tag_command()
    once = commands.slack_native_slashes
    _ensure_slack_native_tag_command()

    assert commands.slack_native_slashes is once
    assert commands.slack_native_slashes() == [
        ("hermes", "Talk", ""),
        ("tag", "Hermes Tag commands", "help | status | admin count | standing ..."),
    ]
