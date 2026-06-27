# Slack adapter — setup & verification (draft)

The Slack adapter (`SlackTagAdapter`) is additive to the `hermes-tag` plugin: it registers a `slack` platform
alongside `feishu`, reusing the same tag engine (Tier-0/Tier-1 context, `/tag` commands, ContextSelector).
It is **code-complete and unit-verified**. Live workspace smoke evidence is tracked in `docs/slack-e2e.md`.

## 1. Create the Slack app (api.slack.com)

Sign in to Slack in a browser, go to **https://api.slack.com/apps → Create New App → From an app manifest**,
pick the test workspace. After `hermes-tag` is installed/enabled, prefer generating the full manifest from Hermes so plugin slash commands are included:

```sh
hermes slack manifest --write /tmp/hermes-slack-manifest.json --name "Hermes Tag"
python docs/slack-manifest-add-tag.py /tmp/hermes-slack-manifest.json
grep '"/tag"' /tmp/hermes-slack-manifest.json
```

Paste `/tmp/hermes-slack-manifest.json` into **Features → App Manifest → Edit**. If you need a bootstrap manifest before Hermes is installed, use this minimal one and replace it with the generated manifest after plugin install:

```yaml
display_information:
  name: Hermes Tag
features:
  bot_user:
    display_name: Hermes Tag
    always_online: true
oauth_config:
  scopes:
    bot:
      - app_mentions:read
      - channels:history
      - channels:read
      - chat:write
      - commands
      - files:read
      - groups:history
      - groups:read
      - im:history
      - im:read
      - mpim:history
      - reactions:read
      - reactions:write
      - users:read
settings:
  event_subscriptions:
    bot_events:
      - app_mention
      - message.channels
      - message.groups
      - message.im
      - message.mpim
      - file_shared
      - reaction_added
      - reaction_removed
  socket_mode_enabled: true
  org_deploy_enabled: false
  token_rotation_enabled: false
```

Then:
1. **Save the generated manifest** and reinstall if Slack prompts. Confirm it contains `/tag`; otherwise native `/tag` never reaches Hermes. Restart the gateway afterward so Socket Mode rebuilds its native command matcher with plugin commands.
2. **Install to Workspace** → copy the **Bot User OAuth Token** (`xoxb-…`) = `SLACK_BOT_TOKEN`.
3. **Basic Information → App-Level Tokens → Generate Token and Scopes** → add scope `connections:write` →
   copy the token (`xapp-…`) = `SLACK_APP_TOKEN`.
4. In the test workspace, create a channel (e.g. `#hermes-tag-test`) and **invite the bot**: `/invite @Hermes Tag`.
   Copy the channel ID (channel name → About → bottom, `C…`). Copy your own Slack user ID for admin (Profile → ⋮ → Copy member ID, `U…`).

## 2. Configure + deploy on the box (192.168.10.78, profile shiling-pm)

Set the tokens in the same place the gateway reads `FEISHU_APP_ID`/`FEISHU_APP_SECRET`, then add the slack
platform to the profile config and update the plugin to the slack branch (or to `main` once PR #3 is merged):

```sh
# 1) tokens (same mechanism as FEISHU_*)
export SLACK_BOT_TOKEN=xoxb-...    # or wherever FEISHU_* lives for the gateway
export SLACK_APP_TOKEN=xapp-...

# 2) update the plugin code (PRE-merge: the branch; POST-merge: main)
cd ~/.hermes/plugins/hermes-tag && git fetch origin && git checkout feat/slack-adapter   # or: git checkout main && git pull

# 3) restart + verify BOTH platforms connect (FEISHU MUST STILL WORK)
hermes --profile shiling-pm gateway restart
hermes --profile shiling-pm gateway list
grep -iE "connected|platform" ~/.hermes/profiles/shiling-pm/logs/gateway.log | tail
```

Add to `~/.hermes/profiles/shiling-pm/config.yaml` under `platforms:` (sibling of the existing `feishu:` block):

```yaml
  slack:
    enabled: true
    require_mention: false   # so ambient channel messages reach the adapter for Tier-0
    extra:
      slack_tag:
        enabled: true
        enabled_chats:
          - C_TEST_CHANNEL_ID     # the #hermes-tag-test channel ID
        admins:
          - U_YOUR_USER_ID
        encryption_posture: plaintext-db-on-local-disk
        db_path: /Users/february/.hermes/profiles/shiling-pm/slack-tag.sqlite3
        media_cache_dir: /Users/february/.hermes/profiles/shiling-pm/slack-tag-media
```

`plugins.enabled` already lists `hermes-tag` (it now registers both `feishu` and `slack`). A healthy start logs
`connected` for Feishu **and** a Slack Socket Mode connection, and `Gateway running with 2 platform(s)`.

## 3. Verify (in #hermes-tag-test)

- `@Hermes Tag hello` → main-channel reply when `platforms.slack.reply_in_thread: false`.
- Post `Background: the deadline is Friday.` (no mention) → then `@Hermes Tag when is the deadline?` → answer uses Friday (Tier-0 ingest + context selection).
- Reply to a message, then `@Hermes Tag ...` → answer anchored to your message, parent as evidence.
- `/tag admin count` (as an admin) → metrics. If Slackbot says `/tag` is invalid, regenerate/save the Hermes Slack manifest after plugin install. If Slack accepts `/tag` but says the app did not respond, restart the gateway with the current `hermes-tag` plugin loaded.
- Confirm Feishu pilot still works (send a `/tag status` in the Feishu pilot group).

## Rollback (if anything regresses Feishu)

```sh
cd ~/.hermes/plugins/hermes-tag && git checkout main && hermes --profile shiling-pm gateway restart
```

## Known v1 limitations
- Reply/parent **media** on Slack is stubbed (`_fetch_reply_media_refs` returns `[]`). Text, mentions, Tier-0
  context, main-channel replies, and `/tag` commands are wired. Slack file/thread media is a follow-up.
- `receive_all` is hardcoded `True`; gate via `channels:history` scope + `require_mention: false`.
- Native Slack slash commands require saving the generated Hermes Slack manifest after plugin install; Socket Mode handles delivery after Slack accepts the command.
