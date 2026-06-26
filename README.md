# Feishu Tag
A channel-scoped AI teammate for Feishu/Lark group chats, on the Hermes agent framework. @-mention it in a group and it answers in-thread with that chat's own memory and the right context — not your whole history.

[English](README.md) · [中文](README.zh-CN.md)

![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg) ![Version: 0.2.0](https://img.shields.io/badge/version-0.2.0-blue.svg) ![hermes-agent: v2026.6.19](https://img.shields.io/badge/hermes--agent-v2026.6.19-blue.svg) ![Python: 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)

<!-- TODO: add docs/demo.gif — sanitized @-mention -> focused_reply clip -->
*The demo will show a group @-mention, bounded evidence selection, and one focused in-thread reply.*

## Why / What

Feishu Tag is a claude-tag-style Feishu/Lark plugin for Hermes: like Anthropic's Claude Tag, or Dust / Glean in Slack — but for Feishu/Lark. It overrides Hermes's built-in Feishu platform; it is not a new Hermes platform.

Each enabled chat gets one shared agent identity. The agent answers only when @-mentioned, and long-term memory is built only from those @-mention interactions, so one chat's working memory does not become your whole account history.

The `ContextSelector` chooses bounded evidence with `focused_reply`, `deictic_recent`, and `plain` scopes instead of dumping the transcript. That means no full-history RAG and no ambient auto-answering; admins keep audit and lifecycle control over retained memory.

This repository is `hermes-plugin-feishu`; the Python/pip package and manifest name are `hermes-plugin-feishu-tag`.

## Security & Risk Warnings (Read Before Use)

- The `enabled_chats` allowlist is the storage and processing boundary.
- All messages in enabled chats may be buffered locally as Tier-0 short-term context.
- Only @-mention interactions create Tier-1 long-term memory.
- The declared `encryption_posture` is `plaintext-db-on-local-disk`.
- Admins can run `/tag admin clear` or `/tag admin disable` to remove retained plugin data for a chat.
- Audit events record startup, storage, admin, standing-job, and lifecycle actions.

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

```bash
hermes plugins install DanielLi202/hermes-plugin-feishu
```

```yaml
plugins:
  enabled:
    - hermes-plugin-feishu-tag
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

Full onboarding + live verification: see [after-install.md](after-install.md).

## Usage

In groups, `/tag` commands require @-mention.

- `/tag status`
- `/tag admin count|clear|disable`
- `/tag standing add <schedule> <timezone> <description>` then `/tag standing confirm`
- `/tag standing list|cancel <id>|pause <id>|enable <id>`

| Context scope | Meaning |
| --- | --- |
| `focused_reply` | Explicit reply -> narrow to that parent as evidence. |
| `deictic_recent` | "上面那张图" / "the image above" -> nearest recent media. |
| `plain` | Bounded recent text. |

| Memory tier | Behavior |
| --- | --- |
| `Tier-0` | Short-term per-chat buffer, TTL/count evicted. |
| `Tier-1` | Long-term, @-derived, consolidated, tombstoned on delete. |

## Project Structure

- `src/hermes_plugin_feishu/core.py` — config, sqlite store, TagEngine, PlatformSeam.
- `src/hermes_plugin_feishu/context.py` — ContextSelector: the bounded-evidence selector.
- `src/hermes_plugin_feishu/base.py` — TagAdapterMixin: the platform-agnostic orchestration.
- `src/hermes_plugin_feishu/platforms/feishu.py` — Feishu binding: mention detection, media fetch/download, registration.
- `src/hermes_plugin_feishu/i18n.py` — locale strings.
- `src/hermes_plugin_feishu/adapter.py` — back-compat re-export shim.

The platform-agnostic base plus narrow seam means new platforms (Slack is planned) are a thin add.

## Contributing · Changelog · License

- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)
- License: MIT, lidongyuan.
