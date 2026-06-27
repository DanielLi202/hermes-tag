# Live E2E Test Plan — hermes-tag phases 1–3 on real Hermes + Feishu/Slack

Status: revised after Codex review. Companion to the stub suite (100 unit/integration tests)
and the live runbooks ([../slack-e2e.md](../slack-e2e.md), [../../after-install.md](../../after-install.md)).
Concrete host/channel/profile values and **all filled-in results** live in the git-ignored
`docs/local-runtime.md` (or another git-ignored local file) — this tracked plan uses
placeholders and carries **no** transcripts, tokens, replies, IDs, or evidence rows.

## 0. Why a live plan (what stubs cannot prove)

The 100 stub tests prove all *logic* (selection, dedup, consolidation, redaction, id format,
scope ladder, **and the session-reset success vs. degraded code paths** via a stub runner) with
the platform/runner/model mocked. Live testing exists only to exercise the **real integration
seams** the stubs mock. Each live test targets a seam, not re-proven logic:

| Real seam (mocked in stubs) | Live test | Roadmap item |
| --- | --- | --- |
| Standard plugin install / no-brick | A2–A7 | install flow |
| Real Feishu/Slack mention + native-slash detection | B1 | boundary |
| Real Hermes runner + model answer uses selected evidence | B2 | F1, F3 |
| Real evicted-parent text/media fetch over the platform API | B3, B6 | F2 |
| Named thread vs explicit reply on real platform events | B4 | P1-A |
| Real Slack media (vision) + buffer-aware metric | B5 | F6 |
| Tier-1 DB/profile **persistence across a real restart** | B7 | F5, F4 |
| **Real Hermes private-runner `session_store.reset_session` seam** | B8 | F7 |
| Real cron job creation behind a standing job | B9 | F9 |
| Audit redaction over the real sqlite DB | B10 | F8/P0-C |
| Slack manifest accepted by Slack → native `/tag` delivered | B11 | P1-B |
| Standalone one-command manifest generator on the host | B11b | P1-B |

> F7 scope (corrected): the stub suite already proves both the success and degraded *code
> paths* (`tests/test_standing_privacy_observability.py:168-176`, `:211-215`). Live B8 proves only
> the thing stubs cannot: the **real private-runner seam** — that `session_store.reset_session`
> on the actual gateway produces a real old≠new session id and is reachable (not degraded).

## 1. Preconditions

All concrete handles below — `HOST`/ssh-alias, `PROFILE`, `FEISHU_GROUP`, `BOT_NAME`,
`SLACK_CHANNEL`/`CHANNEL_ID` — are recorded in the git-ignored `docs/local-runtime.md`; this
tracked plan keeps placeholders only. Replace them from `local-runtime.md` when executing.

- **Host:** `HOST` (ssh alias, IP, hermes binary path, and profile `PROFILE` in `docs/local-runtime.md`).
- **Env on the host:** `FEISHU_APP_ID`, `FEISHU_APP_SECRET` (declared in `plugin.yaml requires_env`). Slack requires `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` — registered by the Slack platform code (`src/hermes_tag/platforms/slack.py`), not by `plugin.yaml`. Confirm all present before install.
- **Feishu surface:** designated test group `FEISHU_GROUP`, agent `BOT_NAME` (names in `local-runtime.md`). Authorized for testing.
- **Slack surface:** workspace + channel `SLACK_CHANNEL` (id `CHANNEL_ID`), bot `Hermes Tag`; config uses `require_mention: false`, `reply_in_thread: false`.
- **Evidence-token convention:** every seeded message embeds a unique token `LIVE-<YYYYMMDD>-<n>` for log/DB/audit correlation. Tokens and the filled results table go in the **git-ignored** local evidence file, never here.
- **Standard install pulls GitHub `main`** (`DanielLi202/hermes-tag`), now containing phases 1–3 + the E2E suite (commit `968b483`). Do NOT rsync the local tree — this run validates the *standard* path.

## 2. Phase A — Clean reinstall via the STANDARD flow (meta-test)

Goal: prove `hermes plugins install <owner/repo>` from a clean slate yields a working
2-platform gateway and does **not** brick Feishu. All steps SSH-automatable from `HOST`.
Run each as a full command (examples assume `~/.local/bin/hermes` on PATH as `hermes`).

**A1 — Baseline + rollback capture (BEFORE removing anything):**
```bash
P=PROFILE   # set from docs/local-runtime.md
hermes --profile $P gateway status
hermes --profile $P plugins list --plain --no-bundled
# back up config and the exact current plugin ref so rollback is possible even if remove fails:
cp ~/.hermes/profiles/$P/config.yaml ~/.hermes/profiles/$P/config.yaml.pre-reinstall.bak
( cd ~/.hermes/plugins/hermes-tag && git rev-parse HEAD ) > /tmp/hermes-tag.pre-reinstall.ref 2>/dev/null || echo "no existing checkout"
# optional: archive DBs if a from-zero feature run is wanted (owner decision; default = retain)
# cp ~/.hermes/profiles/$P/{feishu,slack}-tag.sqlite3 /tmp/  2>/dev/null
```

**A2 — Disable + remove:**
```bash
hermes --profile $P plugins disable hermes-tag
hermes --profile $P plugins remove hermes-tag
hermes --profile $P plugins list --plain --no-bundled   # must NOT list hermes-tag
test ! -d ~/.hermes/plugins/hermes-tag && echo "plugin dir removed"
```

**A3 — No-brick after removal:**
```bash
hermes --profile $P gateway restart
grep -iE "feishu.*connected|Gateway running" ~/.hermes/profiles/$P/logs/gateway.log | tail
```
Pass: built-in Feishu still `Connected`; gateway runs (Feishu only). Removing the plugin must not break base Feishu.

**A4 — Standard install:**
```bash
hermes --profile $P plugins install DanielLi202/hermes-tag
hermes --profile $P plugins list --plain --no-bundled   # must list hermes-tag, enabled
```

**A5 — Config present** (config + DBs live in the profile dir and survive `plugins remove`; verify, re-add from `after-install.md` if missing):
```bash
grep -nE "feishu_tag:|slack_tag:|enabled:|enabled_chats:" ~/.hermes/profiles/$P/config.yaml
```

**A6 — Slack manifest refresh** (must run from the plugin checkout for the relative script path):
```bash
cd ~/.hermes/plugins/hermes-tag && \
  hermes slack manifest --write /tmp/hermes-slack-manifest.json --name "Hermes Tag" && \
  python3 docs/slack-manifest-add-tag.py /tmp/hermes-slack-manifest.json && \
  grep '"/tag"' /tmp/hermes-slack-manifest.json
```
Then save the manifest in **api.slack.com/apps → App Manifest → Edit**, reinstall the app if prompted.

**A7 — Restart + health:**
```bash
hermes --profile $P gateway restart
grep -iE "feishu.*connected|slack.*(socket|connected)|Gateway running with 2 platform" \
  ~/.hermes/profiles/$P/logs/gateway.log | tail
```
Pass: Feishu connected **and** Slack Socket Mode connected **and** `Gateway running with 2 platform(s)`.

**Phase-A acceptance:** A3 proves no-brick; A7 proves both platforms connect after a standard install. On any failure, STOP → §5 rollback.

## 3. Phase B — Live feature matrix

Per test: **Setup** (messages sent from the local Feishu/Slack app) → **Action** →
**Expected (user-visible)** → **Server evidence** (SSH). Server evidence handles:
```bash
P=PROFILE   # set from docs/local-runtime.md
tail -n 120 ~/.hermes/profiles/$P/logs/gateway.log
sqlite3 ~/.hermes/profiles/$P/slack-tag.sqlite3 "select event,created_at,chat_id,detail from audit_events order by id desc limit 15;"
sqlite3 ~/.hermes/profiles/$P/slack-tag.sqlite3 "select name,value from metrics;"   # metrics are their own table, NOT audit_events
# /tag status (sent from the client) also surfaces preflight metrics + any degraded flag.
```

- **B1 · Mention/slash gating — split by platform (boundary).**
  - **Feishu:** `/tag admin count` WITHOUT mention → **no reply**; `/tag admin count @BOT_NAME` → `tier0=… tier1=… standing_jobs=…`. (Feishu group commands are mention-gated.)
  - **Slack:** `/tag` is itself the trigger — `_is_tag_command` makes it count as mentioned (`src/hermes_tag/platforms/slack.py:150-152,195-198`). So native `/tag admin count` (after A6) **replies** with counts; there is no "unmentioned → silent" case for `/tag` on Slack. Before the manifest is saved use the leading-space ` /tag admin count` smoke fallback.
  - *Evidence:* visible count reply; gateway log shows the inbound command; tier0 row count via sqlite. (Note: `/tag admin count` writes **no** audit row — `src/hermes_tag/base.py:520-523` — so do not look for a command audit event.)

- **B2 · F1 contract + F3 ranking through the real model (Feishu & Slack).** Seed two
  unmentioned facts, one relevant one not: `LIVE-…-1 the staging deadline is Friday` and
  `LIVE-…-2 the lunch order is pizza`. Then `@bot for LIVE-…-1, when is the staging deadline?`
  → **answer says Friday**, ignores pizza. *Evidence (not the 240-char preview):* the latest
  `enhance_event` audit detail `selected_text_ids` includes the deadline row and excludes the
  lunch row; cross-check the row text in `tier0_messages`. The prompt contract is injected after
  `current:` (`src/hermes_tag/base.py` `_budget_context`) so do **not** assert "preview starts with
  contract" — assert the model answer used the deadline fact and the selection excluded the lunch row. *(F1, F3)*

- **B3 · F2 evicted-parent text (Feishu).** Reply to a **pre-existing parent the bot never
  buffered** (e.g. a message older than the bot's join / not in Tier-0) — do NOT flood the
  channel to force eviction (Tier-0 cap is 500, `src/hermes_tag/core.py:29`). `@bot what room?`
  → **answer uses the parent's fact**. *Evidence:* audit `scope=focused_reply`; `media_by_source`/
  text shows the reply-parent reached `channel_context`. *(F2)*

- **B4 · P1-A scope ladder on real events (Feishu, mirror on Slack).** (a) In a **thread**, `@bot`
  with no explicit reply → audit `scope=thread`. (b) Explicit **reply** + `@bot` → `scope=focused_reply`.
  (c) **Top-level** `@bot` → `scope=plain` (Slack synthetic self-ts falls to plain). *Evidence:* three
  `enhance_event` audit rows with scopes `[thread, focused_reply, plain]`. *(P1-A)*

- **B5 · F6 Slack media + buffer-aware metric (Slack).** Record `metrics.slack_reply_media_unavailable`
  before/after each step. (a) Post an image, then `@bot what is in the image above` → **vision answers**
  and the metric delta is **0**. (b) Reply to an evicted/never-buffered parent + `@bot` → metric delta
  **+1**. *Evidence:* `select value from metrics where name='slack_reply_media_unavailable'` before/after,
  or `/tag status`. *(F6 buffer-aware fix)*

- **B6 · F2 reply-image (Feishu).** Post an image, reply to it with `@bot what is this?` → **native
  vision answers with the replied image attached**. *Evidence:* `media_download_success` metric
  increments; audit detail `media_by_source.parent ≥ 1`. *(F2 media)*

- **B7 · Tier-1 cross-restart persistence (Feishu or Slack).** The **only** thing asserted live is
  DB/profile durability across a real gateway restart; the dedup and consolidation *logic itself is
  already proven by the stub suite* and is **not** the pass criterion here. *Setup* (to produce a
  non-trivial Tier-1 state without flooding — temporarily set a low `tier1_max_count`, e.g. 3, in the
  test profile, or use a handful of interactions): ask one question twice to get a dedup-skip, then a
  few distinct interactions past the lowered cap so a `consolidated: …` row exists. *Pass criterion:*
  take a sqlite snapshot — `select count(*), group_concat(summary) from tier1_memories` plus
  `metrics.tier1_write_skipped_duplicate` — **restart the gateway**, re-snapshot, and assert the two
  snapshots are **identical** (rows, the consolidated summary text, and the skip metric all survive the
  restart). Do not assert the dedup `+1`/consolidation behavior as the live result, and do not assert
  "high-confidence survives" (live writes use the default confidence). *(F5, F4 — persistence seam only)*

- **B8 · F7 real private-runner session reset (Feishu & Slack).** Seed a fact only before clear.
  `/tag admin clear` (admin, mentioned) → reply **`cleared; session reset`**. Ask the pre-clear fact
  → bot does **not** answer from the old session. *Evidence:* audit `hermes_session_reset` with
  **distinct old/new session ids** AND `metrics.session_reset_degraded` did **not** increment — proving
  the real runner seam is reachable (the stub can only ever fake this). If instead you see
  `hermes_session_reset_skipped`/degraded, the live runner/`session_store` is unreachable — that is a
  real environment finding. *(F7)*

- **B9 · F9 standing-job id + real cron (Feishu).** `/tag standing add weekly-Friday-10:00 Asia/Shanghai
  LIVE-…-9 @bot` → `/tag standing confirm` → `/tag standing list`. *Evidence:* `standing_jobs.id` matches
  `^job-\d+-[0-9a-f]{12}$`; the formatted list/`standing_jobs.cron_job_id` references a **real** cron job
  the gateway created (verify the cron id exists in the Hermes cron surface, not just the local row).
  Then `/tag standing cancel <id>`. *(F9)*

- **B10 · P0-C audit redaction over the real DB (Feishu & Slack).** `/tag admin audit` returns only the
  **last 10** events (`src/hermes_tag/base.py:534-536`), so generate a **fresh** enhance event immediately
  before B10 (one `@bot` question). Then `/tag admin audit` (admin) → output lists `type / created_at /
  scope / *_count` and **no message body / no `context_preview`**. *Evidence:* sqlite shows the raw
  `enhance_event` detail DOES contain `context_preview` while the `/tag admin audit` reply does NOT, and
  new rows have non-null `created_at`. *(F8/P0-C)*

- **B11 · P1-B native `/tag` (Slack).** After A6 save + A7 restart, native `/tag admin count` (no leading
  space) → **works** (Slackbot does not reject; app responds). *Evidence:* gateway log shows the native
  slash-command event reaching Hermes. *(P1-B)*

- **B11b · P1-B standalone one-command generator (host shell).** The headline P1-B acceptance is the
  **no-arg** generator (`docs/design/roadmap.md:256-268`). On the host:
  ```bash
  cd ~/.hermes/plugins/hermes-tag && python3 docs/slack-manifest-add-tag.py > /tmp/m.json
  grep '"/tag"' /tmp/m.json && python3 -c "import json;json.load(open('/tmp/m.json'))" && echo "valid manifest"
  ```
  *Evidence:* stdout `/tmp/m.json` is valid JSON containing `/tag`; the `slack_tag` config block is printed
  to stderr (not captured by `>`). *(P1-B)*

- **B12 · Cross-platform parity.** Repeat B1, B2, B8, B10 on the other platform (`FEISHU_GROUP` with
  `@BOT_NAME`; `SLACK_CHANNEL`), asserting equivalent scopes/metrics/redaction.

## 4. Evidence capture & results

Record per test — token, exact messages, visible reply, server-evidence line — in the
**git-ignored local evidence file** (`docs/local-runtime.md` or a `/tmp` scratch), NOT in this
tracked plan. This file keeps only the empty schema:

| Test | Platform | Pass? | (details → local-runtime.md) |
| --- | --- | --- | --- |
| A1–A7 | host | | |
| B1…B12 | FS/Slack | | |

**Quality caveat:** assert the *correct evidence was selected / stored / redacted* and the *correct
metric/audit transition*, NOT the model's exact wording. A live answer is PASS if it uses the seeded fact.

## 5. Rollback

- **Feishu regression / bad plugin state** (restores to the exact pre-reinstall ref captured in A1):
  ```bash
  P=PROFILE   # set from docs/local-runtime.md
  REF=$(cat /tmp/hermes-tag.pre-reinstall.ref 2>/dev/null)
  if [ -d ~/.hermes/plugins/hermes-tag ]; then
    cd ~/.hermes/plugins/hermes-tag && git checkout "${REF:-main}"
  else
    hermes --profile $P plugins install DanielLi202/hermes-tag
    [ -n "$REF" ] && ( cd ~/.hermes/plugins/hermes-tag && git checkout "$REF" )
  fi
  hermes --profile $P gateway restart
  ```
- **Config regression:** `cp ~/.hermes/profiles/$P/config.yaml.pre-reinstall.bak ~/.hermes/profiles/$P/config.yaml && hermes --profile $P gateway restart`.
- **Slack-only issue:** set `platforms.slack.enabled: false`, restart — Feishu keeps running (additive/fail-safe).

## 6. Out of scope / safety

- Only the designated test group/channel. Never test in non-test groups without explicit per-group authorization.
- No tokens, secrets, IDs, or private transcripts in any tracked file (this plan included). Host specifics + filled results stay in git-ignored `docs/local-runtime.md`.
- Model answer quality and latency are observed, not gated.
- B3/B7/B5 must not flood live channels (Tier-0 cap 500, Tier-1 cap 100); use pre-existing parents or temporary low caps.

## 7. Execution model (who runs what)

- **Server ops (A1–A7, B11b, all server evidence):** SSH-automatable by the agent (`ssh HOST …`; the alias is in `docs/local-runtime.md`).
- **Client message sends (the B-series messages):** human in the Feishu/Slack desktop app, or Computer
  Use (Slack desktop) / MobAI — the prior `slack-e2e.md` smoke used Computer Use.
- **Observation:** SSH log/sqlite/metrics/audit + `/tag status` replies.

Sequence: Phase A (server) → confirm 2-platform health → Phase B per platform (client send + server
observe) → fill the git-ignored evidence file → rollback only on regression.
