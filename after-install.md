# Feishu Tag after install

Hermes installs this plugin by cloning the repo; it does not install Python dependencies from `pyproject.toml`.

## Required env

Set these in the same environment as Hermes:

- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`

`lark-oapi==1.6.9` is expected from the pinned Hermes Feishu environment.

## Minimal config

```yaml
plugins:
  enabled:
    - hermes-plugin-feishu-tag

platforms:
  feishu:
    require_mention: false  # required so Feishu delivers unmentioned group messages to the adapter

extra:
  feishu_tag:
    enabled: true
    enabled_chats:
      - oc_xxx_single_pilot_chat
    bot_open_id: ou_xxx_bot_open_id
    granted_scopes:
      - im:message.group_msg
    admins:
      - ou_xxx_admin_open_id
    encryption_posture: plaintext-db-on-local-disk
    max_context_chars: 4000
```

Without `extra.feishu_tag.enabled: true`, the adapter factory falls back to the built-in Feishu-equivalent adapter so enabling the plugin does not brick Feishu.

## Scope/privacy status

- `im:message.group_msg` is required for receive-all Tier-0/L2 behavior.
- If that scope is missing, unmentioned background context degrades; @-driven Tier-1 memory still works.
- Tell pilot groups: all messages in `enabled_chats` may be stored locally for short-term context; only @ interactions create long-term memory.
- Use a single pilot chat until R5 scope approval and retention review are complete.
