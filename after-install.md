# Hermes Tag after install

Hermes installs this plugin by cloning the repo; it does not install Python dependencies from `pyproject.toml`.

## Required env

Set these in the same environment as Hermes:

- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `SLACK_BOT_TOKEN` (only when enabling Slack)
- `SLACK_APP_TOKEN` (only when enabling Slack Socket Mode)

`lark-oapi==1.6.9` is expected from the pinned Hermes Feishu environment.

## Minimal config

```yaml
plugins:
  enabled:
    - hermes-tag

platforms:
  feishu:
    require_mention: false  # required so Feishu delivers unmentioned group messages to the adapter
    extra:
      feishu_tag:
        enabled: true
        enabled_chats:
          - oc_xxx_pilot_chat
          - oc_xxx_second_pilot_chat
        bot_open_id: ou_xxx_bot_open_id
        granted_scopes:
          - im:message.group_msg
        admins:
          - ou_xxx_admin_open_id
        encryption_posture: plaintext-db-on-local-disk
        max_context_chars: 4000
```

The plugin also accepts the legacy top-level `extra.feishu_tag` shape and bridges it into the Feishu platform config at load time. Without `feishu_tag.enabled: true`, the adapter factory falls back to the built-in Feishu-equivalent adapter so enabling the plugin does not brick Feishu.

## Slack config

After installing/enabling `hermes-tag`, generate the Slack App Manifest from the same Hermes install so plugin slash commands such as `/tag` are included:

```bash
hermes slack manifest --write /tmp/hermes-slack-manifest.json --name "Hermes Tag"
python docs/slack-manifest-add-tag.py /tmp/hermes-slack-manifest.json
grep '"/tag"' /tmp/hermes-slack-manifest.json
```

In Slack, open **api.slack.com/apps → your app → Features → App Manifest → Edit**, paste the generated manifest, save, and reinstall the app if Slack prompts. Socket Mode still delivers command events over the app token; the manifest `url` field is only required by Slack's schema. Restart the gateway after saving so the Slack Socket Mode handler rebuilds its native command matcher with plugin commands such as `/tag`.

Then add Slack as a sibling of `feishu` in the target profile:

```yaml
platforms:
  slack:
    enabled: true
    require_mention: false   # required so ambient messages reach Tier-0 context
    reply_in_thread: false   # group replies stay in the main channel
    extra:
      slack_tag:
        enabled: true
        enabled_chats:
          - C_TEST_CHANNEL_ID
        admins:
          - U_YOUR_USER_ID
        encryption_posture: plaintext-db-on-local-disk
        db_path: /Users/february/.hermes/profiles/PROFILE/slack-tag.sqlite3
        media_cache_dir: /Users/february/.hermes/profiles/PROFILE/slack-tag-media
```

Native `/tag ...` works only after the Slack App manifest contains `/tag` and the gateway has restarted with the `hermes-tag` plugin loaded. Before the manifest save, Slackbot rejects `/tag` before Hermes sees it; before the gateway restart, Slack may accept `/tag` but report that the app did not respond. Use a leading space (` /tag admin count`) only as a temporary smoke fallback.

## Scope/privacy status

- `im:message.group_msg` is required for receive-all Tier-0/L2 behavior.
- If that scope is missing, unmentioned background context degrades; @-driven Tier-1 memory still works.
- Tell pilot groups: all messages in `enabled_chats` may be stored locally for short-term context; only @ interactions create long-term memory.
- Add every approved pilot chat to `enabled_chats`; keep non-approved groups out of this list so their traffic passes through without plugin storage.

## Feishu onboarding and live verification

Run this sequence for each profile that enables the plugin. Replace
`PROFILE`, `CHAT_ID`, `BOT_OPEN_ID`, and `ADMIN_OPEN_ID` with the target
profile and Feishu IDs.

1. Install and enable the plugin.

   ```bash
   hermes --profile PROFILE plugins list --plain --no-bundled
   ```

   The plugin should appear as enabled. If it is installed globally but not
   visible to the profile, link or install it into that profile's plugin path
   before restarting the gateway.

2. Confirm the config boundary.

   ```yaml
   platforms:
     feishu:
       require_mention: false
       extra:
         feishu_tag:
           enabled: true
           enabled_chats:
             - CHAT_ID
             # Add one line per approved pilot group.
           bot_open_id: BOT_OPEN_ID
           granted_scopes:
             - im:message.group_msg
           admins:
             - ADMIN_OPEN_ID
   ```

   `enabled_chats` is the storage and processing boundary. Messages from other
   chats pass through the built-in Feishu adapter and must not be stored by this
   plugin.

3. Restart the gateway and check that Feishu is connected.

   ```bash
   hermes --profile PROFILE gateway restart
   hermes --profile PROFILE gateway list
   tail -n 80 ~/.hermes/profiles/PROFILE/logs/gateway.log
   ```

   A healthy start includes `Connected in websocket mode (feishu)` and
   `Gateway running with 1 platform(s)`.

4. Verify mention gating.

   In the pilot group, send:

   ```text
   /tag admin count
   ```

   Expected: no reply.

   Then send:

   ```text
   /tag admin count @BOT_NAME
   ```

   Expected: `tier0=... tier1=... standing_jobs=...`.

   This guards against plugin commands accidentally bypassing the normal group
   mention requirement.

5. Verify Tier-0/L2 background context.

   Send an unmentioned background message in the pilot group:

   ```text
   Background: the test project deadline is Friday.
   ```

   Then ask with a mention:

   ```text
   When is the test project due? @BOT_NAME
   ```

   Expected: the answer uses Friday. If it does not, check that
   `im:message.group_msg` is granted and present in `granted_scopes`.

6. Verify reply-media handling.

   Send an image in the pilot group. Reply to that image with a mentioned
   question:

   ```text
   What is in this image? @BOT_NAME
   ```

   Expected: the gateway routes native vision with the replied image attached.
   If the image is unavailable, check Feishu message history/media scopes and
   the plugin media cache path.

7. Verify control commands.

   Plugin commands are namespaced under `/tag` so they do not collide with
   Hermes core commands.

   ```text
   /tag help @BOT_NAME
   /tag status @BOT_NAME
   /tag admin count @BOT_NAME
   /tag admin clear @BOT_NAME
   /tag standing add weekly-Friday-10:00 Asia/Shanghai summary @BOT_NAME
   /tag standing confirm @BOT_NAME
   /tag standing list @BOT_NAME
   /tag standing cancel JOB_ID @BOT_NAME
   ```

   Legacy `/admin` and `/standing` aliases may still work for compatibility,
   but new runbooks and tests should use `/tag ...`.

8. Verify admin clear semantics.

   `/tag admin clear @BOT_NAME` must clear plugin storage and reset the Hermes
   gateway session for that chat/user key. The expected reply is:

   ```text
   cleared; session reset
   ```

   Then ask about information that was only present before the clear. The bot
   should not answer from the old Hermes session. If it does, inspect:

   ```bash
   sqlite3 ~/.hermes/profiles/PROFILE/feishu-tag.sqlite3 \
     "select event, chat_id, detail from audit_events order by id desc limit 20;"

   python - <<'PY'
   import json
   p = "~/.hermes/profiles/PROFILE/sessions/sessions.json"
   data = json.load(open(p.replace("~", __import__("os").path.expanduser("~"))))
   for key, value in data.items():
       if "CHAT_ID" in key:
           print(key, value.get("session_id"), value.get("updated_at"))
   PY
   ```

   The audit log should contain `hermes_session_reset` with different old and
   new session IDs.

## Slack onboarding and live verification

Run this sequence for each profile that enables Slack. Replace `PROFILE`, `CHANNEL_ID`, and `ADMIN_USER_ID`.

1. Confirm plugin enabled and `/tag` present in the generated Slack manifest.

   ```bash
   hermes --profile PROFILE plugins list --plain --no-bundled
   hermes slack manifest --write /tmp/hermes-slack-manifest.json --name "Hermes Tag"
   python docs/slack-manifest-add-tag.py /tmp/hermes-slack-manifest.json
   grep '"/tag"' /tmp/hermes-slack-manifest.json
   ```

2. Save `/tmp/hermes-slack-manifest.json` in Slack App Manifest and reinstall if prompted.

3. Confirm profile config includes Slack.

   ```yaml
   platforms:
     slack:
       enabled: true
       require_mention: false
       reply_in_thread: false
       extra:
         slack_tag:
           enabled: true
           enabled_chats:
             - CHANNEL_ID
           admins:
             - ADMIN_USER_ID
   ```

4. Restart and verify both platforms connect.

   ```bash
   hermes --profile PROFILE gateway restart
   grep -iE "slack connected|feishu connected|Gateway running" \
     ~/.hermes/profiles/PROFILE/logs/gateway.log | tail
   ```

5. In the Slack test channel, verify context and commands.

   ```text
   Background: the Slack test deadline is Friday.
   @Hermes Tag when is the Slack test deadline?
   /tag admin count
   ```

   Expected: the answer uses Friday, replies appear in the main channel, and `/tag admin count` returns `tier0=... tier1=... standing_jobs=...`.

## Troubleshooting checklist

- Default Feishu stops after installing the plugin: verify the plugin imports
  the current base adapter path, `plugins.platforms.feishu.adapter`; older
  Hermes builds used `gateway.platforms.feishu`.
- DM works but group does not respond: verify group messages include a real
  Feishu mention payload under `event.message.mentions` and that
  `bot_open_id` matches the bot.
- Background context is ignored: verify `im:message.group_msg` in the Feishu
  app permissions and in `granted_scopes`.
- Commands reply without a mention: group command gating is broken. In groups,
  `/tag ...` must require `@BOT_NAME`; only DMs may run commands without a
  mention.
- `/tag admin clear` says session reset but old facts remain: verify the audit
  event includes a real old/new Hermes session ID pair. If the gateway runner
  or `session_store` is unavailable, the plugin should say reset was skipped.

- Slackbot says `/tag` is not a valid command: regenerate `hermes slack manifest` after `hermes-tag` is enabled, save it in Slack App Manifest, and reinstall the app if prompted.
- Slackbot says `/tag` failed because the app did not respond: the manifest is saved, but the running Socket Mode matcher is stale. Restart the gateway and verify `/tag` appears after running `docs/slack-manifest-add-tag.py` on the generated manifest.
