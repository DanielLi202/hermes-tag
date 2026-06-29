# Hermes Tag

**Post the images, add your notes, let the thread run — then @ it. It already has everything that matters.**

Use Hermes to bring Claude-Tag-style capability to your Feishu/Lark (and Slack). Drop a few images, add a note, let other people chime in — when you finally @-mention it, it pulls *those images (the originals), your note, and the relevant replies* — not just your last line, and never your whole history. Silent until mentioned; then it retrieves exactly the few messages that matter.

[English](README.md) · [中文](README.zh-CN.md)

![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg) ![Version: 0.2.0](https://img.shields.io/badge/version-0.2.0-blue.svg) ![hermes-agent: v2026.6.19](https://img.shields.io/badge/hermes--agent-v2026.6.19-blue.svg) ![Python: 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)

<p align="center"><img src="docs/demo.en.gif" alt="In a Feishu/Lark group you post three charts, add a few notes, drop an unrelated 'Lunch at 12?' line, then @ Hermes Tag last — it answers in-thread with numbered key takeaways drawn from the charts' originals, your notes, and the relevant discussion, and flags the unrelated line as not a conclusion." width="760"></p>

<p align="center"><sub>Real screen recording · <a href="docs/demo.en.mp4">HD MP4</a></sub></p>

## What it is

Hermes Tag is a Claude-Tag-style **context-selection layer** for Hermes on Feishu/Lark (and Slack). It overrides Hermes's built-in Feishu platform — it is not a new platform. Each enabled chat gets one shared agent identity, and it answers only when @-mentioned.

What it uniquely adds on top of Hermes's built-in channels:

1. **Late @, full context.** You can scatter context before you ever invoke it — images, a note, other people's replies — and when you finally @-mention it, it reconstructs the right bounded evidence across time and media: the images' originals, your note, and the relevant discussion. Not just your trigger message; not the whole transcript.
2. **Per-chat memory, by design.** Long-term memory is built only from @-mention interactions and stays scoped to that chat — one chat's memory never leaks into another, and never becomes your whole account history. There is no cross-channel "workspace memory"; that isolation is the privacy promise.
3. **Auditable, and it never stores your message bodies.** `/tag admin audit` returns redacted events (scope, time, counts — never message text); `/tag admin clear|disable` removes a chat's retained data. The `enabled_chats` allowlist is the only storage and processing boundary.

The `ContextSelector` chooses bounded evidence with `focused_reply`, `thread`, `deictic_recent`, and `plain` scopes instead of dumping the transcript. That means no full-history RAG and no ambient auto-answering.

**Shipped now vs. roadmap.** Shipped: bounded multimodal evidence, Tier-0/Tier-1 memory, per-chat isolation, admin lifecycle, and redacted audit — on Feishu/Lark and Slack. DingTalk is also supported, but with **reduced capability**: DingTalk bots only receive messages that @-mention them in groups (no equivalent of Feishu's `im:message.group_msg`), so ambient group context (Tier-0) isn't available there — see [docs/dingtalk.md](docs/dingtalk.md). Roadmap: deeper connector/source-binding parity. The Claude-Tag comparison is the goal we measure against, not a claim that every Claude-Tag feature already ships.

This repository, the Python/pip package, and the manifest name are all `hermes-tag`.

## Security & Risk Warnings (Read Before Use)

- The `enabled_chats` allowlist is the storage and processing boundary.
- All messages in enabled chats may be buffered locally as Tier-0 short-term context.
- Only @-mention interactions create Tier-1 long-term memory.
- The declared `encryption_posture` is `plaintext-db-on-local-disk`.
- Admins can run `/tag admin clear` or `/tag admin disable` to remove retained plugin data for a chat, and `/tag admin audit` to inspect redacted activity.
- Audit events record startup, storage, admin, standing-job, and lifecycle actions — never message bodies.

Read [SECURITY.md](SECURITY.md) and [docs/design/](docs/design/) before enabling a pilot chat.

## Requirements / Compatibility

| Item | Requirement |
| --- | --- |
| hermes-agent | `v2026.6.19` |
| lark-oapi | `1.6.9` |
| Python | `>=3.11` |
| Required env | `FEISHU_APP_ID` + `FEISHU_APP_SECRET` |

These pins are a project convention; Hermes has no enforced compatibility mechanism.

## Quickstart (<60s)

> **Installing with an AI agent?** Point it at [llms.txt](llms.txt) and [AGENTS.md](AGENTS.md) — those are written for agent-driven install/config. This README is for humans.

```bash
hermes plugins install DanielLi202/hermes-tag
```

```yaml
plugins:
  enabled:
    - hermes-tag
platforms:
  feishu:
    require_mention: false   # so unmentioned group messages reach the adapter for Tier-0 context
    extra:
      feishu_tag:
        enabled: true
        enabled_chats: [oc_xxx_pilot_chat]
        bot_open_id: ou_xxx_bot_open_id
        granted_scopes: [im:message.group_msg]
        admins: [ou_xxx_admin_open_id]
        encryption_posture: plaintext-db-on-local-disk
```

Full onboarding + live verification: see [after-install.md](after-install.md). Slack setup: see [docs/slack-setup.md](docs/slack-setup.md). DingTalk setup + capability limits: see [docs/dingtalk.md](docs/dingtalk.md).

## Usage

In groups, `/tag` commands require @-mention.

- `/tag status`
- `/tag admin count|clear|disable|audit`
- `/tag standing add <schedule> <timezone> <description>` then `/tag standing confirm`
- `/tag standing list|cancel <id>|pause <id>|enable <id>`

| Context scope | Meaning |
| --- | --- |
| `focused_reply` | Explicit reply -> narrow to that parent as evidence. |
| `thread` | Real thread without explicit reply -> narrow to that thread as evidence. |
| `deictic_recent` | "上面那张图" / "the image above" -> nearest recent media. |
| `plain` | Bounded recent text. |

| Memory tier | Behavior |
| --- | --- |
| `Tier-0` | Short-term per-chat buffer, TTL/count evicted. |
| `Tier-1` | Long-term, @-derived, consolidated, tombstoned on delete. |

## Project Structure

- `src/hermes_tag/core.py` — config, sqlite store, TagEngine, PlatformSeam.
- `src/hermes_tag/context.py` — ContextSelector: the bounded-evidence selector.
- `src/hermes_tag/base.py` — TagAdapterMixin: the platform-agnostic orchestration.
- `src/hermes_tag/platforms/feishu.py` — Feishu binding: mention detection, media fetch/download, registration.
- `src/hermes_tag/platforms/slack.py` — Slack binding: mention detection, media buffering, registration.
- `src/hermes_tag/platforms/dingtalk.py` — DingTalk binding: `is_in_at_list` mention detection, registration (reduced capability — see [docs/dingtalk.md](docs/dingtalk.md)).
- `src/hermes_tag/i18n.py` — locale strings.
- `src/hermes_tag/adapter.py` — back-compat re-export shim.

The platform-agnostic base plus a narrow seam means each platform is a thin add; the generic policy is written once for all of them.

## Contributing · Changelog · License

- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)
- License: MIT, DanielLi202.
