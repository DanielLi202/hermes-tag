# Hermes Tag — Optimization & Fix Plan (capability-preserving)

Status: spec for implementation. Date: 2026-06-27.

This plan fixes correctness/precision/robustness gaps **without changing any
deliberately-designed capability** of hermes-tag. Every change is additive within
existing modules; no public seam signature changes; stdlib-only (no new deps).

---

## 0. Invariants — what MUST NOT change (deliberate design)

A change that violates any of these is out of scope and must be rejected.

- **I1 — ReplyTarget vs ContextPack split.** The answer is posted to the
  triggering user message in the main conversation; the quoted parent is
  *evidence*, not the reply target. (`_enhance_event` re-anchoring in
  `base.py`; design doc §"Design Principle".)
- **I2 — Three bounded scopes only.** `focused_reply`, `deictic_recent`,
  `plain`. No full-history RAG, no new retrieval scope, no expansion of the
  candidate pool beyond the existing Tier-0 buffer + Tier-1 rows.
  (Design doc §"Non-goals".)
- **I3 — @-mention gate; no ambient answering.** Only @-mention reaches the
  model; only @-mention interactions create Tier-1 memory. Tier-0 buffering of
  unmentioned messages stays as-is.
- **I4 — `enabled_chats` is the storage/processing boundary**, not a
  channel→source binding. Do not turn it into source selection. Per-chat
  isolation of Tier-0/Tier-1 is preserved.
- **I5 — Additive & fail-safe.** If tag config is absent or raises, the base
  platform adapter still works (`adapter_factory` fallbacks). Base Feishu/Slack
  behavior untouched when the tag layer is disabled.
- **I6 — Privacy posture.** TTL/count eviction with media cleanup, `0o600` files,
  consent `ENABLE_NOTICE`, disable-cascade, and "no full message body in audit"
  all remain. No change widens what is stored or sent to the model by default.
- **I7 — Public seam contract.** `PlatformSeam` Protocol method names/signatures
  and `assert_real_seams` requirements are unchanged. No new required env/scopes
  for existing behavior.

**Backward-compatibility rule (capability-level, not byte-level).** With an
unchanged config, no deliberately-designed **capability** changes — I1–I7 all
hold. Several fixes intentionally improve precision/quality and therefore produce
*observable deltas that stay strictly inside the existing scope, reply target,
and privacy envelope*:

- F1 adds the prompt-contract text the existing design doc already mandates;
- F2 completes `focused_reply` parent-text evidence so the *evicted-parent* case
  matches what the design already sends for a *buffered* parent (no new scope);
- F3 re-ranks the **existing** bounded candidate set (no pool expansion);
- F4 changes only the consolidation path (when `count > max_count`);
- F5 suppresses near-duplicate Tier-1 writes.

None of these expands the candidate pool, changes the reply target, sends
out-of-scope data, or alters the @-mention / Tier-1 gates. **Any delta beyond
that envelope is a defect in this plan.** Privacy envelope = the data the design
already considers in-scope for the triggering @-mention (the user's message, the
explicit reply parent they invoked on, the bounded Tier-0 buffer, and Tier-1
memory); a fix may not send anything outside it by default.

---

## Fixes

Each fix: **problem → change → files → invariants touched → acceptance test**.

### F1 (P0) — Ship the Prompt Contract into model context

- **Problem.** The design doc §"Prompt Contract" specifies an anti-hallucination
  instruction ("use only the listed evidence; if missing/ambiguous, say so"), but
  it is **not** implemented. `_budget_context` only packs
  `current / media_notes / background / memories`.
- **Change.** Add a short, fixed contract string (zh+en) to `i18n.py` as
  `PROMPT_CONTRACT`. In `_budget_context` (`base.py`), the **`current:` line stays
  first and is built before anything else**; the contract is placed immediately
  after `current:` and is kept when it fits the remaining budget. Concretely:
  start `pieces = [f"current: {current}"]`, then add the contract only if
  `len(contract) <= remaining`, then `media_notes`, then `background`/`memories`
  as today. The final `[:max_context_chars]` slice is unchanged.
- **Files.** `src/hermes_tag/i18n.py`, `src/hermes_tag/base.py` (`_budget_context`).
- **Invariants.** Respects I2/I6 (instruction only; selects/sends nothing new).
  The `current:` (user question) line is built first and is **never truncated to
  make room for the contract**. Contract length ≤ ~240 chars, so under realistic
  configs (`max_context_chars=4000` default) it is always present; only under a
  pathologically small budget is it omitted — by design, never at the expense of
  `current:`.
- **Acceptance.** `channel_context` contains the contract text and the `current:`
  line for a normal-budget @-mention; with a tiny `max_context_chars` (e.g. less
  than `len(current)+len(contract)`), the `current:` line still appears in full
  and the contract is the part dropped (never the reverse).

### F2 (P0) — Use `reply_to_text` as guaranteed parent-text evidence

- **Problem.** In `focused_reply`, the parent's *text* is included only if the
  parent still happens to be in the Tier-0 buffer. The Feishu reply fetch grabs
  media refs only; `event.reply_to_text` is copied but never injected. A reply to
  an evicted/old parent silently loses the framing message — the exact failure
  (#2950 class) the scope exists to fix.
- **Change.** In `_enhance_event` (`base.py`), when `pack.scope ==
  "focused_reply"` and the parent text is not already present in
  `pack.text_rows`, append `event.reply_to_text` (with an author label if
  available) to `background` as parent evidence. De-duplicate so it is not added
  twice when the parent is already buffered. It flows through the existing
  `_budget_context` truncation, so it is bounded by `max_context_chars` like any
  other background item. No-op when `reply_to_text` is `None`/empty.
- **Files.** `src/hermes_tag/base.py` (`_enhance_event`).
- **Not a privacy regression (I6).** `reply_to_text` is the text of the parent the
  user **explicitly replied to while @-mentioning the bot** — the design doc §1
  ("include parent text and parent media if available") already treats it as
  in-scope evidence, and the buffered-parent path already sends it. F2 only brings
  the *evicted/un-buffered* parent to parity with the buffered parent; it sends
  nothing the design did not already consider in-scope, and adds no new data
  source. This is the F2 delta allowed by the backward-compatibility rule.
- **Invariants.** Only in `focused_reply` (I2). Does not add the quote *preview*
  in other scopes; does not expand the candidate pool. The parent remains
  evidence, not the reply target (I1). Bounded by `max_context_chars` (I6).
- **Acceptance.** Reply to a parent that is NOT in Tier-0 → the parent text still
  reaches `channel_context` (bounded). Reply to a parent that IS in Tier-0 →
  parent text is not duplicated. Non-`focused_reply` scopes: `channel_context`
  unchanged. Empty `reply_to_text` → no change.

### F3 (P0) — Make ranking question-aware (bounded re-rank only)

- **Problem.** `ContextSelector._rank` / `_candidate` score only thread-match
  (10) + author-match (5); `relevant_tier1` sorts only by owner-match + recency.
  Neither considers the current question text, so "relevant" really means
  "recent, same author." Precision miss for a question-driven evidence layer.
- **Change.** Add a lexical-overlap signal (stdlib only: lowercase, split on
  non-word chars, drop a tiny stopword set, token-set overlap) between
  `event.text` and each candidate's text, contributing a value that is **bounded
  strictly below `1.0`** so it can never reach the smallest integer structural
  weight. Dominance is guaranteed *by construction*, not by tuning:
  - In `_candidate`, compute `relevance = overlap / (overlap + 1)` (so
    `relevance ∈ [0, 1)` regardless of token count) and add it to `score`. Because
    `THREAD_MATCH_WEIGHT = 10` and `AUTHOR_MATCH_WEIGHT = 5` are integers and
    `relevance < 1`, any thread- or author-matched candidate (`score ≥ 5`) always
    outranks any pure-lexical candidate (`score < 1`). A relevance-only candidate
    still gets `score > 0`, so it now also passes the existing `score > 0`
    "has-signal" filter in `deictic`/`plain`.
  - In `relevant_tier1` (`core.py`), change the sort key to
    `(owner_match, relevance, created_at)` (reverse), where `relevance` is the
    same bounded `[0,1)` overlap of `event.text` vs `row["summary"]`. Owner-match
    stays the primary key; relevance breaks owner-ties ahead of recency. Still
    return at most `limit` rows.
- **Files.** `src/hermes_tag/context.py`, `src/hermes_tag/core.py`.
- **Invariants.** I2: re-ranks the EXISTING bounded candidate set only — no new
  candidates, no pool expansion, not RAG. `focused_reply` still returns before
  `_rank` (explicit anchor supremacy preserved). `created_at` remains the final
  tiebreak so ordering stays deterministic. This **does change ranking order**
  within `deictic_recent`/`plain` — that is the intended F3 precision delta
  allowed by the backward-compatibility rule, and it is not a capability change
  (scope, pool, gates, and reply target are untouched).
- **Acceptance.** (1) Within `deictic_recent`/`plain`, a candidate whose text
  shares content tokens with the question ranks above an unrelated, newer,
  different-author message. (2) A thread- or author-matched candidate **always**
  outranks a pure-lexical-match candidate, no matter how many tokens overlap
  (assert with a high-overlap, no-structural-match row vs. a single-author-match,
  zero-overlap row → the author-match row wins; this holds by construction since
  `relevance < 1 ≤ AUTHOR_MATCH_WEIGHT`). (3) `focused_reply` selection is
  byte-for-byte unchanged. (4) **`relevant_tier1` owner-tie**: given two active
  Tier-1 rows with the *same* owner, the one more lexically relevant to
  `event.text` is ordered before the merely-newer one (relevance breaks the
  owner-tie ahead of recency); owner-match still beats relevance (a matching-owner
  row precedes a non-matching-owner row regardless of overlap).

### F4 (P1) — Consolidate Tier-1 by value, not by age

- **Problem.** `consolidate_tier1` always merges the two **oldest** rows via
  string concatenation, with `min(confidence)` and an ever-growing
  `"consolidated: A | B"` blob. It destroys the oldest context first and can drop
  high-value memories.
- **Change.** When over `max_count`, select the merge pair deterministically by
  **lowest combined value** (value = confidence, tie-broken by oldest
  `created_at`) rather than strictly the two oldest; union their
  `source_message_ids`; keep `max(confidence)` of the pair (a consolidation is at
  least as supported as its weakest input is wrong — use max to avoid confidence
  decay spiral; document the choice). Add an explicit constant
  `CONSOLIDATED_SUMMARY_MAX_CHARS = 2000` in `core.py` and truncate the merged
  summary to it, stopping unbounded blob growth.
- **Files.** `src/hermes_tag/core.py` (`consolidate_tier1`, new module constant).
- **Invariants.** I3/I4: still per-chat, still @-derived; tombstone semantics and
  `count ≤ max_count` preserved. No behavior change unless `count_tier1 >
  max_count` (consolidation path only).
- **Acceptance.** With one high-confidence recent memory + several low-confidence
  old ones over the cap, the high-confidence memory survives; total count returns
  to `≤ max_count`; every merged summary satisfies
  `len(summary) <= CONSOLIDATED_SUMMARY_MAX_CHARS` (assert directly).

### F5 (P1) — Suppress near-duplicate Tier-1 writes (no capability loss)

- **Problem.** `_write_tier1_memory` persists a summary on **every** answered
  @-mention, so repeated / near-identical Q&A spam the long-term store
  ("foundation of sand").
- **Change.** Before `write_tier1`, skip the write **only** if the new summary is
  a near-duplicate (high token-overlap, threshold e.g. ≥0.9 Jaccard) of the most
  recent active Tier-1 row in the same chat. Distinct facts are still written.
  Optionally expose `tier1_write_mode` config (`"all"` default | `"explicit"`),
  where `"all"` is the current behavior — default preserves capability.
- **Files.** `src/hermes_tag/base.py` (`_write_tier1_memory`), `core.py`
  (helper for "most recent active row" if needed), `core.py` `TagConfig` (optional
  flag, default `"all"`).
- **Invariants.** I3: only @-mention still creates memory; default mode `"all"`
  reproduces today's behavior except exact/near-duplicate suppression. A
  `tier1_write_skipped_duplicate` metric is incremented (observability, I6).
- **Acceptance.** Two identical answered questions in a row → exactly one Tier-1
  row + one `tier1_write_skipped_duplicate`. Two distinct questions → two rows.
  Existing "write on @ interaction" tests stay green under default config.

### F6 (P1) — Make Slack media-evidence behavior explicit and honest

- **Problem.** Slack `_fetch_reply_media_refs` returns `[]` and `_download_media`
  returns `("","")` (`slack.py:160-164`), so `focused_reply`/`deictic_recent`
  *media* evidence is a silent no-op on Slack. The README scope table is
  **platform-agnostic** ("nearest recent media") and so does not say Slack lacks
  it — a Slack operator can reasonably expect media evidence and get none, with no
  signal. This is a documentation/observability gap, not a correctness bug.
- **Change (default — ships now, zero dependency on unverified internals).** Make
  the no-op explicit and *detectable*: increment a `slack_reply_media_unsupported`
  metric **inside the Slack `_fetch_reply_media_refs` no-op itself** — i.e.
  whenever it is invoked with a `reply_id` (which only happens when
  `event.reply_to_message_id` is set, via `_load_reply_media`). The honest,
  stub-visible signal is "a Slack reply occurred and parent-media cannot be
  fetched," NOT "the parent had media" (the latter is undetectable without the
  deferred lookup, so it is explicitly not claimed). Surface the metric in
  `preflight_status` and add a one-line README/scope-table caveat that Slack
  evidence is **text-only** (Feishu carries media). No change to evidence sent to
  the model.
- **Change (OPTIONAL follow-up — explicitly out of this plan's default scope).**
  Implement real Slack reply-media only **after verifying** the base Slack
  adapter's client exposes parent-message + `files[]` access (e.g.
  `conversations.replies` + `files.info`/`url_private`). That base-adapter shape
  is **not** confirmed in this repo, so it is not committed here. If implemented,
  it must: activate only when `files:read` is granted, reuse the existing
  size/`0o600`/eviction path in `_persist_event_media`, and return `[]` gracefully
  when the scope/client is absent. This is the only F6 step that could send Slack
  files to the model, and it is deferred and gated, so the **default plan has no
  privacy delta**.
- **Files.** `src/hermes_tag/platforms/slack.py`, `src/hermes_tag/base.py`
  (`preflight_status`), `README.md`/`README.zh-CN.md` (scope-table caveat).
- **Invariants.** I5/I6/I7: default change is observability + docs only; sends
  nothing new to the model; no new required scope.
- **Acceptance.** Dispatching a Slack event with `reply_to_message_id` set
  increments `slack_reply_media_unsupported` (the no-op path ran) and
  `channel_context` carries no Slack media; the metric appears in
  `preflight_status`; the README/scope table states Slack is text-only; the base
  Slack platform still works. (Optional follow-up has its own acceptance if/when
  undertaken.)

### F7 (P2) — Loud-fail the private-Hermes session-reset coupling

- **Problem.** `_reset_gateway_session` / `_clear_gateway_session_runtime_state`
  reach ~8 private runner internals. They already degrade gracefully **and** the
  `clear` reply already surfaces the failure per-call: `_handle_admin` returns
  `session_reset=False` + `session_reset_reason` (`base.py:500-504`) and
  `format_command_result` renders "cleared; session reset skipped: <reason>"
  (`core.py:381-386`). What is missing is a **persistent** signal: an operator
  cannot see *chronic* degradation without reading every clear reply, and
  `preflight_status` does not expose it. So this is an observability gap, not a
  silent-failure bug.
- **Change.** Add a `session_reset_degraded` metric (incremented when a clear
  cannot reach the runner/session-store internals) and a `preflight_status`
  capability flag reflecting the last/aggregate degraded state. Keep behavior
  graceful (never hard-fail / never break additivity, I5); keep the existing
  per-call `session_reset` + reason in the clear reply unchanged.
- **Files.** `src/hermes_tag/base.py` (`_reset_gateway_session`,
  `preflight_status`).
- **Invariants.** I5: still never bricks; only adds observability.
- **Acceptance.** When the runner lacks the expected internals, `/tag admin clear`
  returns `session_reset=False` with a reason AND `preflight_status` /metrics show
  the degraded signal; when present, no degraded flag.

### F8 (P2) — Calibrate the README claim

- **Problem.** README line 13 ("a claude-tag-style … like Anthropic's Claude Tag,
  or Dust / Glean in Slack") invites a comparison the plugin deliberately does not
  enter (no external-source binding/connectors/selection).
- **Change.** Reword to state what it is: bounded *evidence* selection +
  governed per-chat memory for Feishu/Lark (and Slack), inspired by Claude Tag's
  channel-scoped/shared-identity pattern — without claiming external-source
  connectors. Keep the design doc's honest framing.
- **Files.** `README.md` (and `README.zh-CN.md` for parity).
- **Invariants.** Docs only.
- **Acceptance.** README no longer implies connector/source-selection parity;
  scope table and security section unchanged.

### F9 (P2) — Make standing-job id suffix unique without PYTHONHASHSEED dependence

- **Problem.** `create_standing_job` (`core.py:231-232`) derives the id suffix
  from `abs(hash((chat_id, description, schedule))) % 10000`. Python salts `str`
  hashing per process (`PYTHONHASHSEED`), so the suffix is non-deterministic, and
  `% 10000` invites collisions for two jobs created in the same millisecond. The
  goal is **uniqueness independent of `PYTHONHASHSEED`**, not reproducibility (a
  job id need not be reproducible).
- **Change.** The id keeps its `job-<ms-timestamp>-<suffix>` shape. Replace the
  salted-hash suffix with `uuid4().hex[:12]` (Codex-endorsed: random, no
  `PYTHONHASHSEED` dependence, no global/persisted state). Import it as a
  module-level symbol (`from uuid import uuid4` in `core.py`) so a test can patch
  `hermes_tag.core.uuid4` deterministically. The `<ms-timestamp>` prefix plus a
  48-bit random suffix makes practical collisions negligible, and any
  astronomically-rare collision fails **loudly** on insert: `standing_jobs.id` is
  a `PRIMARY KEY`, so a dup raises `IntegrityError` rather than corrupting data
  (acceptable at uuid4's ~2⁻⁴⁸ per-pair probability; no retry logic added — YAGNI).
- **Files.** `src/hermes_tag/core.py` (`create_standing_job`, `uuid4` import).
- **Invariants.** No API/format change beyond suffix derivation; existing tests
  that read `created["created"]` directly are unaffected. `uuid` is stdlib (no new
  dependency, I7).
- **What is NOT claimed.** Reproducibility, and a *hard* cross-process uniqueness
  guarantee — `uuid4` gives practical (probabilistic) uniqueness, which is the
  honest and sufficient property for a job id namespaced and queried within a
  single store (`WHERE chat_id=? AND id=?`). The earlier "two processes produce
  unique ids as a hard guarantee" claim is dropped as unachievable without a
  persisted/global counter.
- **Acceptance (deterministic, non-flaky).** (1) Patch `hermes_tag.core.uuid4` to
  return two distinct controlled values across two `create_standing_job` calls and
  assert the two ids carry those distinct suffixes — deterministic, no reliance on
  randomness, no flake. (2) Assert the suffix matches `^[0-9a-f]{12}$`, proving it
  is uuid-derived, not `hash(...) % 10000`. (Both are byte-exact; neither depends
  on a probabilistic "two random values differ" event.)

---

## Test plan

All tests run in stub mode (`HERMES_PLUGIN_FEISHU_USE_STUBS=1`,
`HERMES_PLUGIN_SLACK_USE_STUBS=1`), stdlib `unittest`, no new deps.

- Keep all existing 78 tests green (regression gate). Current baseline verified:
  `HERMES_PLUGIN_FEISHU_USE_STUBS=1 HERMES_PLUGIN_SLACK_USE_STUBS=1 PYTHONPATH=src
  python3 -m unittest discover -s tests` → 78 passed, 1 skipped.
- Add focused unit tests: F1 (contract + current present; tiny-budget keeps
  `current`, drops contract), F2 (parent text via `reply_to_text` when
  un-buffered; no dup when buffered; non-focused scope unchanged), F3
  (question-relevant candidate outranks newer unrelated one; thread/author still
  dominate; focused_reply unchanged), F4 (high-value memory survives; `len(summary)
  <= CONSOLIDATED_SUMMARY_MAX_CHARS`), F5 (duplicate suppressed + metric; distinct
  written; default-config regression green), F6 (`slack_reply_media_unsupported`
  metric increments; `channel_context` carries no Slack media), F7
  (`session_reset_degraded` metric/flag set when runner internals missing; absent
  when present), F9 (two same-arg jobs in one process get distinct ids).

## Rollout & risk

- Low risk: every change is local to an existing module; no seam signature,
  dependency, or schema change (sqlite tables unchanged) **for the fix items
  F1–F9**. (The integrated [roadmap.md](roadmap.md) adds one additive
  `audit_events.created_at` column under its governance item P0-C — that is
  governance scope, not a fix item, and does not apply to F1–F9.) Config additions
  (`tier1_write_mode`) default to current behavior.
- Sequence: F1, F2, F3 first (precision core), then F4/F5 (memory quality), then
  F6 (Slack parity), then F7–F9 (robustness/docs). Each lands with its tests.
- Reversibility: each fix is independently revertable; F8 is docs-only.
