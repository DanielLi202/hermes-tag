---
name: hermes-tag
description: Claude-Tag-style context-selection layer for Hermes on Feishu/Lark, Slack, and DingTalk group chats. Use when installing, configuring, or operating an @-mention group teammate that answers from bounded per-chat evidence (original images + your notes + relevant replies) instead of full-history RAG. Keywords: feishu, lark, slack, dingtalk, group chat, context selection, per-chat memory, audit.
emoji: "🏷️"
---

# Hermes Tag

A context-selection layer for Hermes group chats. @-mention it in an enabled Feishu/Lark (or Slack) group and it answers in-thread from bounded per-chat memory plus the right selected evidence — the original images, your notes, and the relevant replies. No full-history RAG, no ambient auto-answering. It overrides Hermes's built-in Feishu platform; it is not a new platform.

## Install

```bash
hermes plugins install DanielLi202/hermes-tag
```

Required env: `FEISHU_APP_ID`, `FEISHU_APP_SECRET` (Slack also needs `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`).

The one human, approval-gated step: an org admin must grant the sensitive Feishu scope `im:message.group_msg`. Everything else (install, config, restart, verify) an AI agent can do — follow [AGENTS.md](AGENTS.md) for the deterministic recipe and acceptance checks, or [after-install.md](after-install.md) for the human walkthrough.

## Key facts

- Config lives under `platforms.feishu.extra.feishu_tag` (and `platforms.slack.extra.slack_tag`). Set `require_mention: false` so unmentioned group messages reach Tier-0 buffering.
- Memory: Tier-0 = short-term per-chat buffer (TTL/count evicted); Tier-1 = long-term, built only from @-mention interactions, per-chat (never cross-chat).
- The `enabled_chats` allowlist is the storage and processing boundary. `/tag admin audit` returns redacted events (never message bodies); `/tag admin clear|disable` removes a chat's retained data.
- Group commands (require @-mention): `/tag status`, `/tag admin count|clear|disable|audit`, `/tag standing add|confirm|list|cancel|pause|enable`.
- DingTalk is supported with reduced capability (mention-only; no ambient group context) — see [docs/dingtalk.md](docs/dingtalk.md). Known limits: [docs/known-limits.md](docs/known-limits.md).

## Pointers

- [llms.txt](llms.txt) — the agent-facing index of this repo.
- [SECURITY.md](SECURITY.md) — storage boundary, redacted audit, lifecycle controls.
- [README.md](README.md) — human-facing overview and demo recordings.
