# Repair Evidence

## Source pins

- Hermes source inspected from `NousResearch/hermes-agent` tag `v2026.6.19`, commit `2bd1977d8fad185c9b4be47884f7e87f1add0ce3`.
- `README.md`/`pyproject.toml` record Hermes project version `0.17.0`, tag, commit, and `lark-oapi==1.6.9`; `plugin.yaml` keeps only official directory-plugin manifest fields.

## v2 contract facts checked against true source

- `hermes_cli/plugins.py:770`: `register_platform(self, name, label, adapter_factory, check_fn, validate_config=None, required_env=None, install_hint="", **entry_kwargs)`.
- `gateway/platforms/feishu.py:1774`: `async send(self, chat_id, content, reply_to=None, metadata=None)`.
- `gateway/platforms/feishu.py:3179`: `_dispatch_inbound_event(event)` is an async enqueue/guard layer and returns `None`.
- `gateway/platforms/base.py:1423`: real `MessageEvent` has no `mentioned`, `author`, `chat_id`, or test-only reply media field.
- `gateway/platforms/feishu.py:3706/3737`: media download seams are `_download_feishu_image(... image_key)` and `_download_feishu_message_resource(... file_key, resource_type, fallback_filename="")`.

## Real seam alignment

- Directory-plugin entrypoint is root `__init__.py`, which exposes `register(ctx)` and delegates to `hermes_plugin_feishu.register`.
- `register(ctx)` calls `ctx.register_platform(name="feishu", adapter_factory=...)` using supported parameters only.
- Runtime adapter subclasses `gateway.platforms.feishu.FeishuAdapter` when Hermes is installed.
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
