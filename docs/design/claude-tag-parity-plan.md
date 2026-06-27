# Hermes Tag — Claude Tag Parity Plan (adoption-driven, additive)

Status: proposal for review. Date: 2026-06-27.

Goal: borrow the **verified** appeals of Anthropic's Claude Tag (Slack channel
teammate, launched 2026-06-23) for Hermes Tag users — without copying what this
plugin structurally can't or shouldn't be. This is a *growth* plan; it is the
companion to [optimization-plan.md](optimization-plan.md) (a capability-preserving
*fix* plan). Where the two collide, §6 reconciles them.

---

## 1. What Claude Tag's appeal actually is

Researched + adversarially verified against the Anthropic announcement, support
docs, VentureBeat, TechCrunch. The genuine draw is **friction-reduction +
permission-bounded collaboration**, *not* "magic org learning" (memory is bounded
per-channel; cross-channel is opt-in and admin-gated). In weight order:

1. **Async delegation that feels like a teammate** — `@`-mention a multi-step
   task; it works in stages and posts back in-thread while the team moves on.
   Visible in-channel, not buried in a DM. *(headline)*
2. **Ambient proactive follow-up (opt-in)** — watches the channel, flags
   relevant info, re-pings threads that went quiet — without being mentioned.
3. **One shared teammate per channel** — anyone picks up where a colleague left
   off; "tag it like a coworker," near-zero learning curve.
4. **Governance without lockdown** — per-channel memory isolation, "nothing
   connected by default," admin audit/delete of memory, spend caps.

Sources: anthropic.com/news/introducing-claude-tag · claude.com/docs/claude-tag ·
VentureBeat/TechCrunch launch coverage.

## 2. The audience wedge (why we copy *some* appeals, not all)

Claude Tag is **Anthropic Enterprise/Team only, Slack only**. We can't out-feature
it (no autonomous agent, no connector fabric, no enterprise infra) and shouldn't
try. Our job is to bring the appeals that *matter* to the people Claude Tag can't
serve:

- **Feishu/Lark teams** — Claude Tag does not exist there at all.
- **Self-hosted Hermes teams** — own model/keys, data stays on their box.

So we replicate appeals **#2, #3, #4** (and improve #1's *feel*), and deliberately
decline the rest (§5).

## 3. Mapping: appeal → plugin today → action

| Claude Tag appeal | Plugin today | Action |
| --- | --- | --- |
| One shared teammate / channel | ✅ one agent identity per `enabled_chat` | none — lead with it |
| Bounded context (CT: per-thread sandbox) | ✅ named `focused_reply`/`deictic_recent`/`plain` scopes — bounded, but over a **chat-wide** candidate set, **not** thread-isolated | lean in: named scopes are more *transparent* than CT's opaque "~50 msgs"; thread isolation itself is P1-A |
| Async, feels-like-a-teammate | ⚠️ synchronous Q&A reply | **P0-A** reply UX |
| Ambient follow-up (opt-in) | ⚠️ Tier-0 buffers unmentioned msgs **only where delivered** (Slack always; Feishu needs `im:message.group_msg` scope **and** upstream all-message delivery / `require_mention=false`) + `/tag standing` scheduler exists | **P0-B** standing follow-up (heuristic first) |
| Per-thread isolation | ❌ no `thread` scope in code; `thread_id` is only an anchor/ranking signal | **P1-A** add `thread` as a new 4th scope (deliberate I2 relaxation) |
| Governance (isolation/audit/"nothing by default") | ✅ substance present (allowlist, `admin clear/disable`, audit events) | **P0-C** surface it |
| Frictionless onboarding | ❌ manifest regen + scopes + config + restart | **P1-B** one-command setup |
| Connectors / MCP / Agent Identity | ❌ context layer only | **Skip** |
| Cross-channel shared memory | ❌ strictly per-chat | **Skip by design** |

## 4. Plan (lazy ladder — reuse existing seams first)

### P0 — cheap, high-leverage, ride existing infra

- **P0-A · Teammate-feel reply.** On `@`-mention: instant ack (`🏷️ on it`) →
  threaded reply; optional "working…" edit for slow answers. Pure UX wrapper
  around the existing dispatch; no new data path. Captures a large slice of
  appeal #1 cheaply.
- **P0-B · Opt-in standing follow-up.** A `/tag standing`-driven job that, per
  enabled chat, surfaces threads that went quiet / questions left unanswered.
  **Off by default, per-chat opt-in.** Requires a populated Tier-0 buffer (see the
  §3 ingestion preconditions — on Feishu that means group scope + all-message
  delivery). Ship the **heuristic** cut first
  (timestamp/no-reply detection over the Tier-0 buffer — **no model call, no
  Tier-1 write, no full message body in the nudge or audit**). It still *acts* on
  unmentioned content, so it is a bounded relaxation of I3 (§6), kept safe by
  off-by-default + opt-in + audit. A model-summarized digest is a separate
  **gated follow-up only** (§6).
- **P0-C · Surface governance.** Add `/tag admin audit` (events are already
  logged) and lift the README's trust narrative to the lead — "`enabled_chats` is
  the boundary; every message in an enabled chat is buffered as short-lived,
  TTL/count-evicted Tier-0; only `@`-mentions reach the model and create Tier-1
  long-term memory" — mirroring CT's "nothing connected by default." (Note: Tier-0
  *does* persist all enabled-chat messages to local SQLite short-term; the promise
  is short-lived + local + `@`-only escalation, not "nothing is stored.")
  **Audit redaction (I6):** the surfaced `/tag admin audit` output must be
  metadata-only — event type, timestamp, scope, selected/excluded counts — and must
  **not** expose the stored audit detail's `context_preview` (`base.py:267` embeds
  up to 240 chars of `channel_context`, i.e. the `current:` user text), per I6's
  "no full message body in audit." Optional: a per-chat message/usage cap to match
  CT's "spend limit" reassurance.

### P1 — medium, clean architectural fit

- **P1-A · `thread` context scope.** A genuinely new (4th) scope — a natural
  extension of the existing `thread_id` plumbing (today only an anchor/ranking
  signal in `context.py`, not a scope), *not* a pre-built extension point. Maps
  1:1 onto CT's per-thread sandbox and Slack's thread model (higher value on Slack
  than Feishu). Fold into `ContextSelector` as a scope; **no inline rule** (honor
  the selection-layer architecture). **Tier-0-only:** it narrows the
  *recent-evidence* candidate set to the thread; Tier-1 long-term memory stays
  **chat-scoped** (it is channel memory, has no `thread_id` column, and
  `relevant_tier1` is chat/owner/recency-only), so no Tier-1 schema change is
  needed or implied.
- **P1-B · One-command Slack onboarding.** Wrap the existing
  `docs/slack-manifest-add-tag.py` + config block into a single guided
  `hermes tag setup`, bringing "turn it on for a channel" closer to CT's 4-step
  feel. Attacks our single worst dimension vs Claude Tag.

### Also needed (not an appeal, but blocks the Slack story)

- **Slack reply/parent media** is stubbed (`_fetch_reply_media_refs → []`), so
  `focused_reply` on an image degrades silently on Slack. Tracked as F6 in
  optimization-plan.md — do that there; this plan just depends on it.

## 5. Explicit non-goals (declining is the positioning)

- Autonomous multi-stage agent execution → that's Hermes-agent core, not a
  context/memory layer.
- Connectors / MCP fabric / Agent Identity → out of scope.
- Cross-channel shared "workspace memory" → **deliberately declined**; per-chat
  isolation is our privacy promise. Saying no here is the honest differentiator
  ("self-hosted, per-channel-isolated, data stays local").

## 6. Reconciliation with optimization-plan.md (the I2/I3 tension)

That plan's invariants **I2** (three bounded scopes only) and **I3** (no ambient
answering; `@`-only memory) were constraints for a *fix* plan, not eternal law.
This growth plan consciously extends them, but bounds the cost:

- **P1-A adds a 4th named scope** (`thread`) → a **deliberate relaxation of I2**.
  Be precise: the code today has only `focused_reply`/`deictic_recent`/`plain`
  (`context.py`); `thread_id` is merely an anchor/ranking signal, not a scope, so
  this is a genuinely new scope, not an "already-anticipated" freebie. It adds no
  new *candidate pool* — only a tighter way to bound the existing Tier-0 set — so
  the I2 *spirit* (no RAG, no pool expansion) is preserved even as the
  three-scope letter is relaxed.
- **P0-B is a deliberate, bounded relaxation of I3** (no-ambient). Honest framing:
  a heuristic nudge *does* act on unmentioned Tier-0 content (`core.py` buffers it
  before the mention gate), so it **is** ambient processing — just a tightly
  bounded kind. The default heuristic cut makes **no model call, no Tier-1 write,
  and puts no full message body in the nudge or audit**, so the model gate and the
  Tier-1/privacy envelope (I6) stay intact; only the "never act without an `@`"
  stance is relaxed, and only when an admin opts a chat in (off by default,
  audited). A model-summarized ambient digest **would** further cross I3/I6 (it
  sends unmentioned content to the model), so it is a separate gated follow-up —
  owner's call, not default scope.
- Everything else (P0-A, P0-C, P1-B) is additive UX/observability/docs and
  touches no invariant.

## 7. Done = (acceptance per item)

- **P0-A** — an `@`-mention produces an immediate ack then a threaded reply; no
  change to evidence sent to the model.
- **P0-B** — with follow-up enabled for a chat, a stale/unanswered thread yields
  exactly one nudge; **disabled (default) → zero nudges**; heuristic path makes
  no model call on unmentioned content.
- **P0-C** — `/tag admin audit` returns **redacted** recent audit events
  (type/timestamp/scope/counts, **no** `context_preview` or message text) + memory
  counts; README leads with the trust narrative.
- **P1-A** — an `@`-mention inside a thread scopes Tier-0 evidence to that thread;
  `focused_reply` precedence unchanged; no candidate-pool expansion; Tier-1
  channel memory still applies unchanged (no schema change).
- **P1-B** — one command emits a valid Slack manifest (incl. `/tag`) + a ready
  config block; existing manual path still documented.

## 8. Sequencing & risk

P0-A → P0-C → P0-B (heuristic) → P1-A → P1-B. Each lands with its own tests in
stub mode; all existing tests stay green. Low risk: additive, per-module, no seam
signature / schema / dependency change. P0-B's model-digest variant and the
per-chat spend cap are deferred owner decisions, not default scope.
