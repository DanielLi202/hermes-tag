# 已知限制（Known limits） (Feishu platform & hermes-agent core)

Hermes Tag runs on top of Feishu's OpenAPI and the hermes-agent gateway. Several limits that users
routinely hit — and file against bots built on this stack — are **not fixable in this plugin**.
This page exists so you can tell in one minute whose limit you're hitting and what to do about it.

Quick self-diagnosis:

| Symptom | Likely cause | Section |
| --- | --- | --- |
| Bot answers @-mentions but seems blind to other group messages | missing `im:message.group_msg` | [Sensitive scopes](#sensitive-scopes) |
| Bot dies/restarts when you run a second gateway or worker | one WebSocket per App ID | [Connection](#connection) |
| Works on feishu.cn, silent on Lark international | no WS long-connection on Lark intl | [Connection](#connection) |
| Replies intermittently dropped under load, 429 in logs | send rate limits | [Rate limits](#rate-limits) |
| Large file/video never arrives | 30 MB media cap | [Media](#media) |
| Can't add the bot to a company group | personal vs enterprise Feishu | [Account types](#account-types) |

## Connection

- **One live WebSocket per App ID.** Feishu allows a single WS long-connection per app. Running
  multiple gateway workers (or two gateways with the same App ID) makes them fight over the
  connection and collapse ([hermes-agent #18693](https://github.com/NousResearch/hermes-agent/issues/18693)).
  Run exactly one gateway per Feishu app.
- **WS drop restarts the whole hermes gateway** rather than just reconnecting the adapter — this is
  hermes-agent core behavior ([#31386](https://github.com/NousResearch/hermes-agent/issues/31386),
  [#10202](https://github.com/NousResearch/hermes-agent/issues/10202)); supervise the gateway
  (launchd/systemd) so restarts are automatic.
- **Lark International has no WebSocket long-connection.** Cross-region deployments must use
  webhook mode, which means a publicly reachable endpoint or a tunnel
  ([openclaw #48949](https://github.com/openclaw/openclaw/issues/48949)).

## Rate limits

- Bot message sends are capped at **5 QPS and 100 messages/minute per bot per tenant**, and the cap
  is **not self-raisable** (only Feishu can raise it) — see the official
  [frequency-control doc](https://open.feishu.cn/document/server-docs/api-call-guide/frequency-control).
  Fan-out replies, retry loops, and streaming-by-edit all burn this budget; 429 responses mean
  dropped or delayed messages.
- Message edits (used by hermes core's fake streaming) are further capped per message
  ([hermes-agent #16084](https://github.com/NousResearch/hermes-agent/issues/16084)).

## Media

- **30 MB cap** on message media; larger files never arrive
  ([openclaw Feishu docs](https://docs.openclaw.ai/channels/feishu) document the same ceiling).
- Voice messages require Ogg/Opus transcoding (ffmpeg) on the sending side; without it, voice
  degrades to a plain file attachment. Media *reception* in this plugin is bounded by Tier-0
  buffering — see the privacy/retention notes in the README.

## Account types

- **Personal and enterprise Feishu are separate systems**: a bot on a personal account cannot be
  added to enterprise-tenant groups, and vice versa
  ([feishu.cn article](https://www.feishu.cn/content/article/7613321214802643921)). Build the app
  in the tenant where your groups live.

## 敏感权限（Sensitive scopes）

- Tier-0 full-group context requires the sensitive scope **`im:message.group_msg`**. Without it,
  Feishu never delivers non-@ group messages — the bot is not broken, it is blind by permission.
  Since v0.4.0 the plugin live-verifies this scope against your app on first use and DMs the
  configured admins when the config claims a scope the app doesn't hold; `/tag status` shows the
  verdict as `capability_check=ok|mismatch|upgrade_available|unknown`.
- The plugin does **not** need `contact:user.employee_id:readonly`; sender identity is normalized
  to the app-scoped `open_id` regardless (see CHANGELOG v0.4.0).

## Explicitly out of scope for this plugin

Interactive card rendering, native CardKit streaming, and markdown-table cards are Feishu
CardKit/API territory and hermes-agent core's rendering decision — this plugin deliberately stays a
context/memory layer. See the positioning notes in
[docs/design/feishu-pain-points-research.md](design/feishu-pain-points-research.md).

