# DingTalk (钉钉)

Hermes Tag supports DingTalk by wrapping Hermes's built-in DingTalk adapter (Stream Mode), the same
mixin pattern used for Slack. Enable it with a `dingtalk_tag` block (mirrors `feishu_tag` / `slack_tag`):

```yaml
platforms:
  dingtalk:
    extra:
      dingtalk_tag:
        enabled: true
        enabled_chats:            # DingTalk conversationId (cid...) of each enabled group
          - cidXXXX
        admins:                   # DingTalk senderId of each admin (NOT staffId)
          - <senderId>
        db_path: dingtalk-tag.sqlite3
        encryption_posture: plaintext-db-on-local-disk
```

Credentials are the base adapter's `DINGTALK_CLIENT_ID` / `DINGTALK_CLIENT_SECRET` (run `hermes ... setup`,
QR or manual). For cron / standing-job delivery, also set `DINGTALK_WEBHOOK_URL` — DingTalk replies use a
per-message session webhook that expires, so proactive sends to an idle chat need the static robot webhook.

## Capability limit (read this before deploying)

**DingTalk has no equivalent of Feishu's `im:message.group_msg`.** A DingTalk bot only receives messages
that **@-mention it** in a group (plus all 1:1 chats); non-@ group messages are never delivered to the
bot. (DingTalk's full "user message event" exists but is whitelisted to a few DingTalk-internal
enterprises — not available to normal apps.)

Consequence: on DingTalk the plugin degrades to **@-only long-term memory (Tier-1)**, the same as Feishu
*without* the `im:message.group_msg` scope. **Ambient group context (Tier-0) is not available on DingTalk** —
the bot cannot see the unmentioned messages that precede an @, so it can't fold prior group discussion into
its answer. What still works: per-chat Tier-1 memory built from @-interactions, multimodal evidence on the
@-mentioned message itself, `/tag` commands (require @ or DM), and standing jobs.

钉钉机器人在群里只能收到 @ 它的消息，没有飞书 `im:message.group_msg` 的等价权限，因此**群内环境上下文
（Tier-0）在钉钉上不可用**，插件退化为「仅 @ 的 Tier-1 长期记忆」。这是平台能力差距，无法通过配置解决。

Other platform notes: DingTalk events carry no thread / reply-target, so context selection only uses the
`deictic_recent` / `plain` scopes. Recalled media (referring to an earlier image) is not buffered in v0.3.0
because DingTalk media arrives as remote download URLs, not local files; current-message media still works.
