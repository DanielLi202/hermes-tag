# Hermes Tag — Integrated Execution Roadmap (fix + parity)

Status: execution plan. Date: 2026-06-27.

This is the **single execution document**. It supersedes, for sequencing purposes,
[optimization-plan.md](optimization-plan.md) (the capability-preserving *fix* plan,
items `F1–F9`) and [claude-tag-parity-plan.md](claude-tag-parity-plan.md) (the
adoption *growth* plan, items `P0-A…P1-B`); both are retained for full rationale.
Here the two are merged, ordered by **user value**, mapped to the correct
**architecture layer**, and the growth plan's weak spots are corrected.

---

## 0. Field corrections (2026-06-27) — native Hermes capability vs. claude-tag

The Phase-1 analysis characterized Hermes-on-Slack from **docs/GitHub, not from a
running bot**, and the parity plan inherited "Hermes = synchronous Q&A." Field
evidence corrected three items. Root cause: capability claims about a running
system must be checked against the running system, not only its docs.

1. **Positioning stays.** "**Use Hermes to bring claude-tag-style capability to
   your Feishu/Lark (and Slack)**" is the product's headline and north star — it is
   **not** removed. claude-tag is the benchmark we measure against; the README's
   honesty job is only to mark what is *shipped now* vs. *on this roadmap*, never to
   drop the claude-tag framing. (Corrects F8 below.)
2. **The "on it" ack is already native.** Hermes natively posts a *processing
   reaction* (an emoji on the triggering message) while it works — observed in the
   product, not in the docs the research read. So P0-A was mis-scoped: there is **no
   ack to build**. Where claude-tag is genuinely *stronger* is the **staged,
   multi-step in-thread checklist** ("Pulled p99 latency → Diffed deploy → Opening a
   PR") — live progress for a multi-step agentic task. That is **Hermes-agent-core**
   behavior (the agent's tool loop posting intermediate updates), not a
   context/memory-layer concern, so it is **declined** here alongside autonomous
   execution. (Corrects P0-A → moved to §4.)
3. **Slack already reads contextual images.** Slack `receive_all=True` buffers all
   media into Tier-0 via the platform-agnostic `store_tier0 → _persist_event_media`,
   and current-message + deictic/recent + buffered-parent images flow into the model
   (field-verified: a Slack "上面这张图是什么" was answered correctly). The Slack
   `_fetch_reply_media_refs` stub is **not** "Slack is text-only" — it only affects an
   explicit reply to a parent that is **no longer in the Tier-0 buffer**. (Corrects
   F6 below; the "Slack text-only" caveat is removed.)
4. **Proactive follow-up is parked.** Opt-in ambient follow-up is a real claude-tag
   trait, but the owner's call is **do not build it for now** — recorded in §4, not
   to be implemented unless the owner reverses. (Removes Phase 4 / P0-B from active
   scope; I3 "no ambient" therefore stays an absolute invariant again.)

---

## 1. Principles

### 1.1 Value-first ordering

Phases are ordered by user-visible value × confidence, not by "fixes before
features." Correctness work that directly removes wrong/low-trust answers comes
first; internal hygiene comes last; capabilities Hermes already provides natively
are not rebuilt (§0). Each item carries an explicit **Value** rating.

### 1.2 Architecture / layering contract (load-bearing)

Two layers, and a hard rule for what goes where:

- **Layer A — shared core (multi-channel).** `core.py` (config, `TagStore`,
  `TagEngine`, `PlatformSeam`), `context.py` (`ContextSelector`), `base.py`
  (`TagAdapterMixin` orchestration), `i18n.py` (strings). **All generic policy and
  logic lives here** and is written once for every platform.
- **Layer B — platform adapters (channel-specific).** `platforms/slack.py`,
  `platforms/feishu.py`. **Only platform-divergent *mechanism* lives here**,
  expressed as `PlatformSeam` method implementations (mention detection, media
  fetch/download, message send, manifest/setup).

**The rule:** a capability's *decision/policy* is generic → Layer A; its
*platform mechanism* is a seam method → interface declared in Layer A
(`PlatformSeam`), implemented in Layer B. A new capability that needs a new
mechanism **adds a seam method with a safe default** (so existing adapters/tests
keep working); it never changes an existing seam signature. If an item can be
done with the seams that already exist (`send`, `is_mentioned`,
`_fetch_reply_media_refs`, `_download_media`, cron API), it must be — no new
platform code for free.

**Placement check (every item below states its layer; the roadmap is invalid if
any generic logic is pushed into an adapter or any platform mechanism leaks into
core):**

| Layer | Modules | Holds |
| --- | --- | --- |
| A (shared) | `core.py`, `context.py`, `base.py`, `i18n.py` | selection, ranking, memory, prompt contract, consent text, dedup, scheduling decisions, governance/audit, ambient heuristic *(parked)* |
| B (Slack) | `platforms/slack.py` | Slack mention detection, Slack evicted-parent reply-media, Slack manifest/setup |
| B (Feishu) | `platforms/feishu.py` | Feishu mention detection, Feishu media fetch/download, Feishu setup |
| B (DingTalk) | `platforms/dingtalk.py` *(v0.3.0)* | DingTalk mention detection (`is_in_at_list`), `handle_message`+`dispatch_to_model` override, reply-media stubs, DingTalk setup — see [0.3.0-dingtalk-plan.md](0.3.0-dingtalk-plan.md) |

### 1.3 Invariant policy

The fix-plan invariants **I1, I3, I4, I5, I6 hold absolutely** throughout
(ReplyTarget ≠ ContextPack; `enabled_chats` boundary; **no ambient — @-only**;
additive/fail-safe; privacy posture & "no full message body in audit"). Exactly
**one** is consciously, narrowly relaxed, gated as an owner decision:

- **I2 (three bounded scopes)** → relaxed by **P1-A** (adds a named `thread`
  scope). Bounded: no candidate-pool expansion, no RAG.

(Ambient follow-up — the former P0-B — would have relaxed I3, but the owner has
**parked it** (§0.4, §4), so **I3 stays absolute**.)

**I7 (extended).** Existing `PlatformSeam` signatures and `assert_real_seams`
requirements are unchanged. New capabilities **may add** a seam method, each with
a safe default in `TagAdapterMixin` so adapters that don't override it still work.
No new third-party dependency (stdlib only).

---

## 2. Phases

Each item: **Value · Layer · Change · Invariant · Acceptance · Deps.** F-items
restate the (already Codex-passed) essence; see optimization-plan.md for full
rationale.

### Phase 1 — Trust & evidence precision (highest value, pure Layer A, no relaxation)

Goal: answers are grounded in the *right* evidence and the layer is honest about
what it stores. Pure shared-core; zero platform code; zero invariant relaxation.

- **F1 · Prompt contract.** *Value: high (kills the #1 trust-killer — confidently
  wrong/over-broad answers).* **Layer A** (`i18n.PROMPT_CONTRACT`, `base._budget_context`).
  Build `current:` first; place the ≤240-char contract right after it, kept only
  when it fits; `current:` is never truncated for the contract.
  *Acceptance:* normal budget → `channel_context` contains contract + `current:`;
  a budget large enough for `current` but not `current`+contract → `current`
  present, contract dropped (contract is added only if it fits *after* `current`).
- **F2 · Parent-text evidence in `focused_reply`.** *Value: high (makes the
  headline feature correct when the parent was evicted).* **Layer A**
  (`base._enhance_event`). When `scope == "focused_reply"` and parent text isn't
  already in `pack.text_rows`, append `event.reply_to_text` (bounded by
  `_budget_context`); de-dup; no-op if empty. Not a privacy regression — it is the
  explicit reply parent the user invoked on (design doc §1).
  *Acceptance:* reply to an un-buffered parent → parent text reaches
  `channel_context`; buffered parent → no duplication; non-focused scopes
  unchanged.
- **F3 · Question-aware ranking.** *Value: high (evidence precision).* **Layer A**
  (`context.py`, `core.relevant_tier1`). Add a bounded lexical-overlap signal
  `relevance = overlap/(overlap+1) ∈ [0,1)` added to the integer structural score,
  so thread(10)/author(5) **always** dominate by construction; `relevant_tier1`
  sort key becomes `(owner_match, relevance, created_at)`.
  *Acceptance:* a thread/author match always outranks any pure-lexical match;
  within `deictic`/`plain` a question-relevant row beats an unrelated newer one;
  `focused_reply` byte-for-byte unchanged; `relevant_tier1` owner-tie broken by
  relevance before recency.
- **F8 + P0-C · Governance honesty (merged — both touch trust narrative/audit).**
  *Value: high for the self-hosted/privacy-conscious wedge.* **Layer A** (README
  docs; `base` admin command; `TagStore` audit already platform-agnostic).
  - **Keep the claude-tag positioning (§0.1).** The README headline stays "use
    Hermes to bring claude-tag-style capability to Feishu/Lark (and Slack)" — that
    is the product's north star, not to be removed. The only README edit is
    *honesty about staging*: add a short "what's shipped now vs. on the roadmap"
    line so the claude-tag *comparison* is framed as the goal we're driving toward,
    not a claim that every claude-tag appeal (connectors, source-binding) already
    ships. Keep `README.zh-CN.md` in parity. Also lead with the trust narrative
    ("`enabled_chats` is the boundary; every enabled-chat message is buffered as
    short-lived TTL/count-evicted Tier-0 in local SQLite; only @-mentions reach the
    model and create Tier-1").
  - **Audit timestamp prerequisite (schema gap).** `audit_events` today is
    `(id, event, chat_id, detail)` with **no timestamp** (`core.py:92`), and
    `audit()` writes none (`core.py:133`). So add a `created_at REAL` column via an
    **idempotent migration** in `TagStore.__init__` (check `PRAGMA
    table_info(audit_events)`; if absent, `ALTER TABLE audit_events ADD COLUMN
    created_at REAL`), and have `audit()` write `time.time()`. Additive and
    backward-compatible (existing rows get NULL); Layer A; no seam/dependency change.
  - Add `/tag admin audit` returning **redacted** recent events: type,
    `created_at`, `chat_id`, and only the non-sensitive keys parsed from `detail`
    (scope, selected/excluded *counts*) — and **never** the stored
    `context_preview` (`base.py:267` embeds ≤240 chars of `channel_context`, i.e.
    the user's `current:` text), honoring I6. Order by `id` (insertion order) so a
    NULL legacy `created_at` never breaks ordering.
  *Acceptance:* a newly written audit event has non-null `created_at`; the
  migration adds the column idempotently on an existing DB (running `TagStore`
  twice does not error); `/tag admin audit` output contains no
  `context_preview`/message body and surfaces type/timestamp/scope/counts; the
  README **keeps** the claude-tag positioning **and** carries a shipped-now-vs-
  roadmap line (so the comparison reads as a goal, not as already-shipped
  connector parity); scope table + security section unchanged.

### Phase 2 — Memory quality & robustness (additive, pure Layer A unless noted)

> Note: the "teammate-feel ack" (former P0-A) is **dropped** — Hermes already posts
> a native processing reaction (§0.2); there is nothing to build. claude-tag's
> stronger staged in-thread checklist is Hermes-agent-core, declined (§4).

- **F5 · Suppress near-duplicate Tier-1 writes.** *Value: medium (keeps memory
  signal, not sand).* **Layer A** (`base._write_tier1_memory`, `core` helper).
  Skip the write only when the new summary is ≥0.9 token-overlap with the most
  recent active Tier-1 row in the chat; increment `tier1_write_skipped_duplicate`.
  Default still writes distinct @-interactions. *Acceptance:* two identical
  answered questions → one row + one skip metric; two distinct → two rows.
- **F4 · Value-based Tier-1 consolidation.** *Value: medium.* **Layer A**
  (`core.consolidate_tier1`, new constant). Merge the **lowest-value** pair
  (value=confidence, tie-broken oldest), union `source_message_ids`, keep
  `max(confidence)`, and truncate to `CONSOLIDATED_SUMMARY_MAX_CHARS = 2000`.
  *Acceptance:* high-confidence recent memory survives over the cap; count returns
  `≤ max_count`; every merged summary `≤ 2000` chars.
- **F6 · Slack evicted-parent reply-media fallback (narrow; corrected per §0.3).**
  *Value: low (narrow edge case — Slack media already works for the common paths).*
  **Correction:** Slack is **not** text-only. `receive_all=True` buffers all media
  into Tier-0 (`store_tier0 → _persist_event_media`, Layer A), so **current-message,
  deictic/recent, and buffered-parent images already reach the model** on Slack
  (field-verified). The Slack `_fetch_reply_media_refs` stub (`platforms/slack.py`)
  only matters for an **explicit reply to a parent no longer in the Tier-0 buffer**
  (evicted by TTL/count, or posted before the bot joined) — the media analogue of
  F2's evicted-parent text gap.
  - **Default (ships now):** make the edge case observable, not silently empty —
    increment `slack_reply_media_unavailable` only when an explicit Slack reply's
    parent is absent from Tier-0 (**Layer B**), and surface it in
    `preflight_status` (**Layer A**). Buffered-parent media must not increment the
    metric because that media can still reach the model through Tier-0. **Do not**
    add a "Slack is text-only" README caveat — that would be false; if anything,
    document that Slack media works for current/recent/buffered context and only
    evicted-parent reply media is unfetched.
  - **Optional follow-up (Layer B, deferred, gated on `files:read`):** real
    parent-file fetch (`conversations.replies` + `url_private`) reusing the existing
    `0o600`/eviction path, only when the parent is absent from Tier-0.
  *Acceptance:* a Slack reply whose parent is **not** in Tier-0 increments
  `slack_reply_media_unavailable`; a Slack reply/message/deictic reference whose
  image **is** in Tier-0 still carries that media to the model and does **not**
  increment the metric (regression guard proving Slack is not text-only); base
  Slack platform still works.
- **F7 · Session-reset degradation signal.** *Value: low (ops).* **Layer A**
  (`base._reset_gateway_session`, `preflight_status`). Add `session_reset_degraded`
  metric + preflight flag when the Hermes runner internals aren't reachable; keep
  the existing per-call `session_reset` + reason in the clear reply.
  *Acceptance:* runner internals missing → `session_reset=False` + reason AND
  preflight/metric show degraded; present → no flag.
- **F9 · Collision-safe standing-job id.** *Value: low (internal correctness).*
  **Layer A** (`core.create_standing_job`). Replace `hash()%10000` suffix with
  `uuid4().hex[:12]` via a patchable `from uuid import uuid4`; `standing_jobs.id`
  PRIMARY KEY is the fail-loud backstop. *Acceptance (deterministic):* patch
  `core.uuid4` to two values → two ids carry those distinct suffixes; suffix
  matches `^[0-9a-f]{12}$`.

### Phase 3 — Thread transparency & frictionless onboarding (I2 relaxation, gated)

- **P1-A · Named `thread` scope.** *Value: medium — be honest: thread-narrowing
  **already happens**. Today `anchor_id = reply_to_message_id or thread_id`
  (`context.py:56`), so a threaded message already routes through `focused_reply`
  anchored on its `thread_id`. P1-A does **not** add net-new narrowing; it
  **splits** the implicit-thread case out of `focused_reply` into a named `thread`
  scope so (a) audit/observability shows `scope=thread` vs `focused_reply`, and
  (b) explicit-reply precedence is explicit in code.* **Layer A**
  (`ContextSelector.select`). Precedence ladder after the split:
  `focused_reply` (explicit `reply_to_message_id`) → `thread` (a real
  `thread_id`, i.e. not the Slack synthetic self-ts) → `deictic_recent` → `plain`.
  No candidate-pool change; Tier-1 stays chat-scoped (no `thread_id` column, no
  schema change). This is the **deliberate I2 relaxation** (3→4 named scopes);
  the I2 *spirit* (no RAG, no pool expansion) is preserved.
  *Acceptance:* an @-mention with an explicit `reply_to_message_id` still yields
  `scope=focused_reply` (byte-for-byte unchanged); an @-mention in a real thread
  with no explicit reply now yields `scope=thread` with the same same-thread
  candidate set it produced before; Slack top-level (synthetic thread_id == own
  ts) still falls to `plain`; no Tier-1 schema change.
- **P1-B · One-command setup (standalone script).** *Value: medium-high (attacks
  the worst dimension vs Claude Tag — onboarding friction).* **Build-time tooling
  (Slack), outside the A/B runtime layers.** There is **no** `hermes` CLI
  subcommand to extend and **no `console_scripts`** in `pyproject.toml`, and this
  plan must **not** depend on upstream Hermes CLI changes (I5). So P1-B upgrades the
  **existing standalone** `docs/slack-manifest-add-tag.py` into a complete one-shot
  generator: `python docs/slack-manifest-add-tag.py` emits a valid Slack manifest
  (incl. the `/tag` command) **and** a ready `slack_tag` config block, and
  `docs/slack-setup.md` documents it as the one-command path. Feishu keeps its
  existing registered `setup_fn`. No runtime adapter change, no new entry point, no
  upstream dependency.
  *Acceptance:* running the script emits a valid manifest incl. `/tag` + a ready
  config block; the manual path stays documented; no runtime adapter change; no new
  console entry point added to `pyproject.toml`.

### PARKED — Ambient follow-up (P0-B) — recorded, NOT on the active roadmap

> **Owner decision (§0.4): do not build proactive follow-up for now.** This is a
> real claude-tag trait, but it stays parked unless the owner explicitly reverses.
> The full design is **kept below as a record** (so a future revival starts from a
> reviewed spec, not a blank page); it is **not** scheduled and does **not** relax
> I3 while parked. Nothing in Phases 1–3 depends on it.

- **P0-B · Opt-in heuristic standing follow-up.** *Value: medium, **risk: high** —
  this is the one item that posts **unprompted** in a channel, the "surveillance /
  digital supervisor" perception. Ship only behind every guard below.* **Layer A**
  (heuristic + scheduling decision in `TagEngine`/`base`; config in `TagConfig`;
  consent text in `i18n`) using the **existing** cron seam (`HermesCronAPI`) for
  scheduling and the **platform** send for delivery — no new platform code.
  - **Off by default; genuinely per-chat opt-in.** Config is
    `ambient_followup_chats: tuple[str, ...]` on `TagConfig` (default `()` = off
    everywhere); a chat is eligible only if its `chat_id` is in that tuple **and**
    in `enabled_chats`. A single global bool would not be per-chat; the tuple makes
    "chat A opted in, chat B not" real and testable.
  - **Delivery must bypass the Tier-1 correlation path (same trap as P0-A).** The
    nudge is sent via the **platform** send (`send_to_platform`/`super().send`),
    **not** `engine.send` — `engine.send` pops the pending map and writes Tier-1
    using the sent text as the "conclusion" (`core.py:353-363`), which would
    fabricate a memory from the nudge. Platform send writes no Tier-1 and makes no
    model call.
  - **Scheduling (reuse the existing cron seam).** The scan is a periodic job
    registered per opted-in chat through the existing `HermesCronAPI.create`
    (the same plumbing `/tag standing` uses), whose handler runs the heuristic over
    that chat's Tier-0 buffer. No new scheduling mechanism; no new seam.
  - **Consent-notice update (closes the parity plan's gap), deduped durably.**
    The first time ambient runs for a chat it sends a new `i18n.AMBIENT_NOTICE`:
    "this chat has opt-in follow-up on; the bot may post unprompted reminders about
    quiet/unanswered threads using **local heuristics only — no message content is
    sent to the model** for these reminders." **Once-ever dedup must be durable** —
    use a persisted `ambient_notice_sent` audit marker per `chat_id` (not the
    in-memory `self.notified_chats` set that `enable_chat` uses at `base.py:512`,
    which resets on restart and would re-spam the notice). The existing
    `ENABLE_NOTICE` is unchanged; ambient gets its own disclosure so the behavior
    contract users were given stays honest.
  - **One consistent thread key (fixes the grouping mismatch).** All three uses —
    Tier-0 grouping, the `bot_engaged` marker, and the `ambient_nudge` dedup — key on
    the **same** value as `store_tier0` already persists: `thread_key(event) =
    _thread_id(event) or event.reply_to_message_id or event.message_id` (mirroring
    `base.py:187` + `insert_tier0`'s `thread_id or message_id` default at
    `core.py:148`). Keying `bot_engaged` on `thread_id_of` alone would miss
    explicit-reply chains (whose Tier-0 `thread_id` falls back to
    `reply_to_message_id`); using the shared `thread_key` guarantees the marker and
    the Tier-0 group match. Define `thread_key` once in Layer A (`core.py`) and reuse.
  - **"Bot engaged" marker (keeps the heuristic in Layer A).** Tier-0 has **no
    bot-authored flag** (`core.py:93-96`) and bot identity is platform-specific
    (Slack `_bot_user_id`, Feishu `bot_open_id`), so a "newest row not bot-authored
    / bot already replied" test would leak Layer-B mechanism into core. Instead, the
    engine writes a **Layer-A** `bot_engaged` marker keyed by `(chat_id,
    thread_key(event))` via `TagStore.audit` whenever it dispatches an @-mention to
    the model. "The bot answered in this thread" is then a generic lookup, no bot
    identity required.
  - **Precise heuristic (testable, no vagueness, Layer A only).** Group the Tier-0
    buffer by the stored `thread_id` (= `thread_key`). A thread is a nudge candidate
    iff: it has **≥2** Tier-0 rows (a real discussion, not a lone stale message)
    **and** its newest Tier-0 row is older than `ambient_quiet_seconds` (config,
    default `3600`) **and** no `bot_engaged` marker exists for `(chat_id, thread)`
    **and** no prior `ambient_nudge` marker exists for it. (Optional
    question-detection on the newest row is a deferred, locale-fragile refinement —
    **not** in the core acceptance.)
  - **One nudge per thread, ever** — dedup via an `ambient_nudge` audit marker keyed
    by `(chat_id, thread)` (no new table; reuse `TagStore.audit`/`audit_events`). The
    nudge is a fixed reminder posted **in-thread** via the platform send
    (`send_to_platform(chat_id, text, reply_to=thread_root)`, **not** `engine.send`);
    it **quotes no message body** (points by location), makes **no model call**, and
    writes **no Tier-1**.
  - **Model-summarized digest** (would send unmentioned content to the model →
    crosses I3/I6) is **deferred** as a separate owner decision, not in scope here.
  *Acceptance (all Layer-A, stub-testable):* (1) default (`ambient_followup_chats
  = ()`) → **zero** nudges. (2) **Per-chat gate:** with chat A in
  `ambient_followup_chats` and chat B not, only chat A is eligible (B → zero even
  with a matching stale thread). (3) An eligible chat with a thread of ≥2 Tier-0
  rows whose newest row is older than `ambient_quiet_seconds`, no `bot_engaged` and
  no `ambient_nudge` marker → **exactly one** nudge, delivered via the platform send
  so `count_tier1` is **unchanged** (no Tier-1 write) and no model call occurs, plus
  one body-free `ambient_nudge` audit. (4) After the bot answered an @-mention in
  that thread (a `bot_engaged` marker keyed by the shared `thread_key` exists) →
  **zero** nudges — including the explicit-reply case where Tier-0 `thread_id` came
  from `reply_to_message_id`. (5) Re-running the job → zero further nudges for that
  thread. (6) The first ambient scan for a chat sends `AMBIENT_NOTICE` once,
  deduped via the persisted `ambient_notice_sent` marker — a second scan (even
  after clearing in-memory state to simulate a restart) does **not** re-send it.

---

## 3. Cross-cutting

- **ContextSelector single-owner sequencing.** F3 (Phase 1) and P1-A (Phase 3)
  both edit `select()`. F3 lands first (ranking within the bounded set); P1-A
  later splits the `thread` scope. They must be one coordinated change-stream on
  `context.py`, not parallel branches. `focused_reply` precedence is preserved by
  both.
- **README single source.** F8 and P0-C both touch README/trust narrative; they
  are merged into one Phase-1 edit to avoid contradictory messaging.
- **Audit single source.** F7 (session-reset signal) and P0-C (`/tag admin audit`)
  both add to the audit/preflight surface in Layer A; coordinate field names.
- **Schema-change scope.** The **only** schema change in the whole roadmap is
  P0-C's additive `audit_events.created_at` column (idempotent migration). All
  **F1–F9 fix items remain schema-free**, so optimization-plan.md's "no schema
  change" statement stays accurate for its scope (the fixes); the migration belongs
  to the governance item, not to any fix.
- **Testing gate.** All work runs in stub mode
  (`HERMES_PLUGIN_FEISHU_USE_STUBS=1 HERMES_PLUGIN_SLACK_USE_STUBS=1
  PYTHONPATH=src python3 -m unittest discover -s tests`). Baseline verified by
  local run: **`Ran 80 tests … OK (skipped=1)`**. Every item lands with its own
  stub test; the baseline stays
  green as a regression gate. No new dependency; stdlib only.
- **Sequencing graph.** Phase 1 (F1→F2→F3→F8/P0-C) → Phase 2 (F4, F5, F6, F7, F9,
  independent) → Phase 3 (P1-A after F3; P1-B independent). Ambient (P0-B) is
  **parked**, not in the graph.

## 4. Declined / deferred (positioning)

- **Declined by design:** external connectors / MCP fabric / agent identity
  (that's Hermes-agent core, not a context/memory layer); cross-channel
  "workspace memory" (per-chat isolation is the privacy promise and the honest
  self-hosted differentiator); autonomous multi-stage agent execution; **the staged
  multi-step in-thread checklist** (claude-tag's stronger "working…" UX — also
  Hermes-agent-core, §0.2).
- **Already native — nothing to build:** the **"on it" processing reaction** (former
  P0-A) is provided by Hermes core (§0.2); **contextual image reading on Slack**
  (current/recent/buffered) already works (§0.3).
- **Parked (recorded, not building unless the owner reverses):** **P0-B opt-in
  ambient follow-up** — full design kept in the "PARKED" section above (§0.4).
- **Deferred owner decisions (not default scope):** F6 real Slack evicted-parent
  file fetch; a per-chat message/spend cap; a future `edit_message` seam if an
  "edit ack into answer" UX is ever wanted.

## 5. Layer-placement summary (the abstraction model, at a glance)

| Item | Phase | Layer | New seam? |
| --- | --- | --- | --- |
| F1 prompt contract | 1 | A (`i18n`,`base`) | no |
| F2 parent-text evidence | 1 | A (`base`) | no |
| F3 question-aware ranking | 1 | A (`context`,`core`) | no |
| F8+P0-C governance honesty | 1 | A (`base`,docs) | no |
| ~~P0-A teammate reply~~ | — | **dropped — native (§0.2)** | — |
| F5 dup-suppression | 2 | A (`base`,`core`) | no |
| F4 consolidation | 2 | A (`core`) | no |
| F6 Slack evicted-parent media | 2 | B (`slack`) + A surface | no |
| F7 session-reset signal | 2 | A (`base`) | no |
| F9 job-id | 2 | A (`core`) | no |
| P1-A `thread` scope | 3 | A (`context`) | no |
| P1-B one-command setup | 3 | tooling (Slack script), no runtime layer | no |
| P0-B ambient follow-up | **parked** | A (heuristic/config/consent) + existing cron/`send` | no |

Every generic capability is Layer A; the only platform-specific work is F6 (Slack
evicted-parent media no-op + optional fetch) and P1-B (Slack manifest script) —
each strictly an adapter-side mechanism behind a seam. No generic logic lives in an
adapter; no platform mechanism leaks into core.

> **2026-06-29 update — v0.3.0 adds DingTalk as a third Layer B adapter.** The Layer B
> table (§1.2) and this summary predate it and enumerate only Slack/Feishu. v0.3.0 adds
> `platforms/dingtalk.py`, mirroring Slack's seam set (override `handle_message` +
> `dispatch_to_model` + `is_mentioned`, reply-media stubs) — **Layer A and every
> `PlatformSeam` signature stay unchanged (I7 holds)**. Full plan:
> [0.3.0-dingtalk-plan.md](0.3.0-dingtalk-plan.md).
