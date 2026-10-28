# AGENTS.md — install & configure Hermes Tag (for AI agents)

You are installing the `hermes-tag` plugin into a Hermes install. This file is the deterministic
recipe; `README.md` is the human-facing surface. The plugin overrides Hermes's built-in Feishu
platform (and supports Slack); it is not a new platform.

## TL;DR
- Install: `hermes plugins install DanielLi202/hermes-tag`
- You can do almost all of the setup. **Exactly one step needs a human with Feishu org-admin rights:**
  granting the sensitive scope `im:message.group_msg`. If the user already runs Hermes on Feishu, that
  scope grant is the *only* manual step left — do everything else yourself.

## 1. What you (the agent) can do autonomously

_Precondition: this targets Hermes >=`0.22.5` (tested at `v0.22.5`) with **Python 3.14**. If `hermes plugins install` or the
adapter path errors, check `hermes --version` before debugging further._

1. Run the install command.
2. Write the config block into the target profile config (template in §3). Fill only the keys marked
   `AGENT-SET` — but **do not write `granted_scopes` until the human confirms the §2 scope grant is approved.**
3. Restart the gateway: `hermes --profile PROFILE gateway restart`.
4. Run the acceptance checks in §4 and report the actual output. Do not claim success without them.

## 2. What you MUST get from the human — never invent these
| Value | Source | Why you cannot set it |
| --- | --- | --- |
| `FEISHU_APP_ID`, `FEISHU_APP_SECRET` | the Feishu 开放平台 custom app | secrets |
| `enabled_chats` (`oc_...`) | the target Feishu group(s) | you cannot read their group ids |
| `bot_open_id` (`ou_...`) | the app's bot | per-tenant id you cannot derive |
| `admins` (`ou_...`) | the human's Feishu open_id | identity decision |
| `im:message.group_msg` **granted + approved** | Feishu 权限管理, org-admin approval | only an org admin can approve a sensitive scope |

If any are missing, **stop and ask the human**. Do not guess `oc_...`/`ou_...` ids, do not fabricate
secrets, and do not proceed as if the scope is granted — without it, unmentioned background context
silently degrades (the bot still answers @-mentions, so a quick `/tag admin count` will look fine and
hide the problem).

## 3. Config template (Feishu)
Place under the target profile. Comments mark provenance.

```yaml
plugins:
  enabled:
    - hermes-tag                       # AGENT-SET
platforms:
  feishu:
    require_mention: false             # AGENT-SET — so unmentioned group messages reach Tier-0
    extra:
      feishu_tag:
        enabled: true                  # AGENT-SET
        enabled_chats:                 # HUMAN-PROVIDED
          - oc_xxx_pilot_chat
        bot_open_id: ou_xxx_bot        # HUMAN-PROVIDED
        granted_scopes:                # AGENT-SET — but ONLY after the human confirms the §2 grant is approved
          - im:message.group_msg
        admins:                        # HUMAN-PROVIDED
          - ou_xxx_admin
        encryption_posture: plaintext-db-on-local-disk   # AGENT-SET
        max_context_chars: 4000        # AGENT-SET (optional)
```

Slack is optional and additive — see `after-install.md` → "Slack config" (it needs a generated app
manifest step that also can't be skipped).

## 4. Acceptance checks (run these; report real output)
1. Plugin loaded: `hermes --profile PROFILE plugins list --plain --no-bundled` → `hermes-tag` shows enabled.
2. Gateway connected: restart, then the gateway log shows `Connected in websocket mode (feishu)` and
   `Gateway running with N platform(s)`.
3. Mention gating: in a pilot group, `/tag admin count` (no mention) → **no reply**;
   `/tag admin count @BOT_NAME` → `tier0=... tier1=... standing_jobs=...`.
4. **(MUST PASS) Scope actually works — the real test for the human step:** post an unmentioned message
   `Background: the test project deadline is Friday.`, then `When is the test project due? @BOT_NAME`
   → the answer must use **Friday**. If it does not, `im:message.group_msg` is not truly granted/approved.

**A green check 3 with a failing check 4 means STOP, not ship.** The config can look fully provisioned
(you wrote `granted_scopes`) while the scope is not actually approved — and check 3 (mention gating)
passes without it. Do not claim success until check 4 passes; tell the human, do not work around it.

## 5. If Hermes + Feishu is not set up yet
Then the human must first do the full Feishu console flow (create app, enable bot, add scopes, event
subscription, publish, add the bot to the group). That is human-only — point them at
`after-install.md` → "Feishu console setup (from scratch)", then come back to §1.
