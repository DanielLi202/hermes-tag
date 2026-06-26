# Repair Evidence

## Source pins

- Hermes source inspected from `NousResearch/hermes-agent` tag `v2026.6.19`, commit `2bd1977d8fad185c9b4be47884f7e87f1add0ce3`.
- `README.md`/`pyproject.toml` record Hermes project version `0.17.0`, tag, commit, and `lark-oapi==1.6.9`; `plugin.yaml` keeps only official directory-plugin manifest fields.

## v2 contract facts checked against true source

- `hermes_cli/plugins.py:770`: `register_platform(self, name, label, adapter_factory, check_fn, validate_config=None, required_env=None, install_hint="", **entry_kwargs)`.
- `plugins/platforms/feishu/adapter.py`: current Hermes Feishu adapter path; the older `gateway.platforms.feishu` path is no longer present in the local Hermes install.
- `plugins/platforms/feishu/adapter.py`: `async send(self, chat_id, content, reply_to=None, metadata=None)`.
- `plugins/platforms/feishu/adapter.py`: `_dispatch_inbound_event(event)` is an async enqueue/guard layer and returns `None`.
- `gateway/platforms/base.py:1423`: real `MessageEvent` has no `mentioned`, `author`, `chat_id`, or test-only reply media field.
- `gateway/platforms/feishu.py:3706/3737`: media download seams are `_download_feishu_image(... image_key)` and `_download_feishu_message_resource(... file_key, resource_type, fallback_filename="")`.

## Real seam alignment

- Directory-plugin entrypoint is root `__init__.py`, which exposes `register(ctx)` and delegates to `hermes_tag.register`.
- `register(ctx)` calls `ctx.register_platform(name="feishu", adapter_factory=...)` using supported parameters only.
- Runtime adapter subclasses the real Hermes Feishu adapter, preferring `plugins.platforms.feishu.adapter.FeishuAdapter` and falling back to `gateway.platforms.feishu.FeishuAdapter` only for older installs.
- `register(ctx)` preserves the base Feishu registry contract: config validation, YAML config bridge, allowlist envs, cron delivery env, standalone sender, update command, and message length.
- Startup signature self-check covers:
  - `_dispatch_inbound_event(event)` async
  - `_download_feishu_image(message_id=..., image_key=...)` async
  - `_download_feishu_message_resource(message_id=..., file_key=..., resource_type=..., fallback_filename=...)` async
  - `send(chat_id, content, reply_to=None, metadata=None)` async
- Cron is routed through `cron.jobs.create_job/update_job` via `HermesCronAPI`.

## v3 F4 keyed Tier-1 association

- Tier-1 pending entries are keyed by Feishu `response_correlation_key` (`chat_id:message_id`) instead of a per-chat FIFO queue.
- `send(...)` writes Tier-1 only when `metadata.response_correlation_key`, `metadata.task_session_id`, `metadata.tier1_key`, `metadata.trigger_message_id`, or `reply_to` resolves to an existing pending key.
- Bot self-sends from `enable_chat` and `trigger_standing_job` have no matching key, so they do not consume pending mentions.
- Same-key multi-part replies write once because the pending entry is popped atomically under `store.lock`.
- Pending entries are scoped by key and pruned by `tier1_pending_ttl_seconds` instead of being popped by unrelated sends.
- Regression coverage includes standing-trigger pollution, enable notice pollution, out-of-order replies, no-reply pending, multi-part replies, and an explicit old-FIFO effectiveness check.

## Unable to complete here

R4 live smoke is blocked in this local repo because there is no running Hermes gateway, Feishu test app/bot credentials, pilot group, or organization scope approval state available.

Current R5 scope status: not verified here. Consequence:

- R4.1 cannot be proven live here: no Hermes gateway instance to load the plugin and prove adapter override.
- R4.2 cannot be proven live here: no Feishu group/image mention event to verify real `media_urls` + native vision.
- R4.3 cannot be proven live here: no live scheduler + Feishu group to verify timed cron delivery.
- R1.4 full unmentioned group-message ingest depends on `im:message.group_msg`; approval state is external and unverified here.

Local verification covers logic and real-signature-shaped seams only.

## 2026-06-26 local live onboarding evidence

The earlier "R4 live smoke is blocked" section is historical. A later local
pilot run used a real Hermes profile and Feishu pilot group to complete the
onboarding checks.

Environment:

- Profile: `shiling-pm`
- Pilot group name: `TAG-TEST`
- Pilot group chat ID: `oc_...` (redacted)
- Plugin DB: `~/.hermes/profiles/shiling-pm/feishu-tag.sqlite3`
- Gateway logs: `~/.hermes/profiles/shiling-pm/logs/gateway.log`
- Installed plugin path: `~/.hermes/plugins/hermes-tag`

Live checks completed:

- Default Feishu recovery after plugin install.
  - Root cause: the plugin originally imported the old `gateway.platforms.feishu`
    adapter path. Current Hermes uses `plugins.platforms.feishu.adapter`.
  - Fix: load the current path first, fall back to the old path for compatible
    installs, and preserve the base Feishu platform registry contract.

- Profile-local plugin loading.
  - `shiling-pm` needed the plugin visible in that profile's plugin path.
  - Gateway restart showed Feishu connected over websocket and loaded the
    plugin-backed `feishu` platform.

- Group mention recognition.
  - DM worked while group mentions initially did not.
  - Root cause: real Feishu raw events expose mentions under
    `raw_message.event.message.mentions`; tests only covered simpler shapes.
  - Fix: read the real raw Feishu message, call the base `_mentions_self`
    helper when available, and keep a local fallback parser.

- Feishu receive-all background context.
  - Before `im:message.group_msg` was granted, Feishu history access returned
    a missing-scope error.
  - After the scope was granted, unmentioned background messages entered
    Tier-0 and mentioned questions received L2 context.
  - Verified cases included:
    - deadline background followed by a deadline question
    - grey-version background followed by a version question
    - owner/release-time background followed by a combined question

- Reply image context.
  - A group image followed by a reply question routed through native vision
    with the replied image attached.

- Namespaced plugin commands.
  - Canonical commands are under `/tag`, for example `/tag admin count` and
    `/tag standing list`, so they do not collide with Hermes core commands.
  - Legacy `/admin` and `/standing` aliases remain for compatibility only.

- Group command mention gate.
  - `/tag admin count` without a group mention incorrectly replied during
    testing.
  - Fix: command messages no longer imply mention in groups. DMs may still run
    commands without a mention.
  - Regression coverage: group `/tag ...` without `@BOT_NAME` returns no reply.

- Command reply path.
  - `/tag admin count` was recognized as a command but initially produced no
    Feishu reply because the command result only returned from
    `_dispatch_inbound_event`; the base Feishu dispatch path ignores that return
    value.
  - Fix: `TagEngine` formats command results and sends them through the platform
    seam before returning the structured result to tests.

- `/tag admin clear` semantics.
  - Clearing plugin Tier-0/Tier-1 alone was not enough: Hermes gateway session
    history still contained old facts and the model could answer from the old
    transcript.
  - A first attempt to call the native `/new` message handler from inside the
    plugin produced an audit event but did not rotate the real session ID.
  - Final fix: the plugin obtains the gateway runner from the bound message
    handler, resolves the exact session key with `_session_key_for_source`, calls
    `session_store.reset_session(session_key)`, and clears runtime state such as
    cached agent, running state, queued events, model/reasoning overrides, and
    session-boundary security state.
  - If the runner/session store is unavailable, the plugin reports
    `cleared; session reset skipped: ...` instead of claiming success.

Current verification command:

```bash
PYTHONPATH=src /Users/february/.hermes/hermes-agent/venv/bin/python -m unittest discover -s tests
```

Current expected result:

```text
Ran 60 tests
OK
```
