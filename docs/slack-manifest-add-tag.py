#!/usr/bin/env python3
"""Ensure a Hermes Slack manifest contains the /tag slash command."""
from __future__ import annotations

import json
import sys
from pathlib import Path

TAG_COMMAND = {
    "command": "/tag",
    "description": "Hermes Tag commands",
    "usage_hint": "help | status | admin count | standing ...",
    "url": "https://hermes-agent.local/slack/commands",
    "should_escape": False,
}


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/hermes-slack-manifest.json")
    manifest = json.loads(path.read_text())
    scopes = manifest.setdefault("oauth_config", {}).setdefault("scopes", {}).setdefault("bot", [])
    if "commands" not in scopes:
        scopes.append("commands")
    commands = manifest.setdefault("features", {}).setdefault("slash_commands", [])
    if not any(cmd.get("command") == "/tag" for cmd in commands):
        # ponytail: Slack caps apps at 50 slash commands; trade one low-value core command for /tag.
        for drop in ("/version", "/usage", "/insights"):
            if any(cmd.get("command") == drop for cmd in commands):
                commands[:] = [cmd for cmd in commands if cmd.get("command") != drop]
                break
        commands.append(TAG_COMMAND)
    if len(commands) > 50:
        raise SystemExit(f"too many Slack slash commands: {len(commands)}")
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"ok: /tag present, {len(commands)} slash commands, commands scope present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
