# Feishu Context Injection Review Plan

Status: review draft, not an implementation commitment.

Date: 2026-06-26

## Background

The Hermes Tag plugin already restores the default Hermes Feishu gateway path,
supports approved group allowlists, records short-lived Tier-0 group context,
and can use replied or recent image messages for vision requests.

The latest testing exposed a more precise problem: the plugin currently mixes
two different concepts:

- response routing: where the agent's answer should appear in Feishu;
- evidence selection: which quoted, recent, or remembered facts should be sent
  to the model.

When a user replies to a previous chat message and asks the agent a question,
Feishu/Hermes can route the answer under the quoted parent message. The desired
behavior is different: the agent should answer the user's triggering message in
the main conversation, while still using the quoted message as evidence.

A second test showed that an explicit reply to one image caused the model to see
three images: the current Feishu quote preview, the replied parent image, and
older L2 media from the channel buffer. That is a context precision failure, not
just a missing rule.

## Goal

Provide a reviewed design for replacing ad hoc context construction with a
small, explicit context-selection layer.

The implementation should:

- keep answers anchored to the triggering user message, not to the quoted parent;
- use an explicit quoted/replied message as the primary evidence anchor;
- avoid injecting current quote previews or unrelated recent media when a
  stronger explicit anchor exists;
- preserve useful channel awareness for cases like "上面这张图" when there is no
  explicit Feishu reply;
- keep channel-scoped memory useful without making every prior message or image
  part of every request;
- make selection decisions inspectable in logs and tests.

## Non-goals

- Do not build a general RAG system over the full Feishu history.
- Do not make the bot ambiently answer unmentioned group messages.
- Do not add more special-case string rules as the primary architecture.
- Do not depend on upstream Hermes changes before the local plugin can work.

## Reference Behavior

Claude Tag and similar shared-channel agents are useful references, but the
important pattern is not "load more context". The useful pattern is:

- one shared agent identity per channel;
- channel-scoped memory and tools;
- narrow retrieval of thread or channel context when the user invokes the bot;
- a visible answer in the same conversation where the user asked;
- admin/audit control over retained memory.

The reference model suggests a channel-aware context pack with bounded evidence,
not a raw transcript dump.

Sources used during investigation:

- Official Claude Tag help article:
  `https://support.claude.com/en/articles/15594475-what-is-claude-tag`
- Open-source Claude Tag style implementation:
  `https://github.com/Anil-matcha/open-claude-tag`
- Arcade Claude Tag Slack tutorial:
  `https://www.arcade.dev/blog/claude-tag-build-slack-ai-agent/`

## Design Principle

Separate the inbound event into two products:

1. `ReplyTarget`: the Feishu message/thread anchor used for sending the answer.
2. `ContextPack`: the bounded set of text, media, and memory evidence sent to
   the model.

The quoted parent may be evidence without being the reply target.

## Proposed ContextPack Shape

Each triggered request should produce a structured context pack before the
Hermes runner sees it.

```text
ContextPack
  current_request
    message_id
    chat_id
    user_id
    text
    direct_media
  reply_target
    message_id            # triggering user message
    thread_id_policy      # main conversation or thread, depending on platform
  anchors
    explicit_reply_parent # optional, strongest evidence anchor
    recent_deictic_media  # optional, only if no explicit reply anchor
  evidence
    text_items[]
    media_items[]
  memory
    channel_memory[]
  exclusions
    skipped_candidates[]  # for audit and tests
```

The adapter can still emit a Hermes `MessageEvent`, but that event should be
derived from this pack rather than assembled directly from several independent
lists.

## Selection Scopes

### 1. Focused Reply

Trigger: the Feishu event has `reply_to_message_id`.

Behavior:

- answer the triggering user message;
- fetch the replied parent as the primary evidence anchor;
- include parent text and parent media if available;
- do not include the current quote preview as a separate image when parent media
  was fetched successfully;
- do not include older L2 media unless the user explicitly asks to combine wider
  context, for example "结合前面几张图".

This is the case that failed when one explicit replied image expanded into three
model images.

### 2. Deictic Recent Context

Trigger: no explicit Feishu reply, but the text contains a contextual reference
such as "上面这张图", "刚刚那个截图", or "前面那条".

Behavior:

- search Tier-0 candidates in the same chat;
- prefer the nearest candidate with compatible modality;
- if there is one high-confidence candidate, include it;
- if there are multiple plausible candidates, include at most a small ranked set
  and expose ambiguity in the prompt or reply;
- do not attach all recent media by default.

### 3. Thread Context

Trigger: the message is part of a Feishu thread/reply sequence and the question
asks about the discussion rather than a single object.

Behavior:

- include a bounded text transcript from the thread or parent chain;
- attach media only when the question requests visual content or the selected
  anchor is media-dominant;
- keep author labels and message IDs for provenance.

### 4. Channel Memory

Trigger: general questions where prior decisions, owners, deadlines, or standing
facts are relevant.

Behavior:

- query Tier-1 channel memory by chat and semantic/text relevance;
- include compact memories, not raw old media;
- keep provenance so a future admin/debug command can explain where memory came
  from.

### 5. Broad Summary

Trigger: the user explicitly asks for broad history, for example "总结今天群里
讨论了什么".

Behavior:

- use a bounded summary/retrieval path;
- prefer text summaries and source ranges over raw media;
- require a wider context budget and clear audit logs.

## Candidate Ranking

Candidates should have explicit metadata rather than being appended as strings:

```text
ContextCandidate
  source: current | explicit_reply | thread | recent | tier1_memory
  message_id
  chat_id
  author
  created_at
  text
  media_paths[]
  modality: text | image | file | mixed
  score
  reasons[]
```

Suggested ranking signals:

- explicit reply anchor beats all inferred context;
- exact same thread beats same chat;
- recent media beats old media only when the user uses deictic wording;
- same author is a weak signal, not a hard filter;
- Tier-1 memories are compact background, not media sources;
- media budget is independent from text budget.

## Prompt Contract

The model should receive an explicit instruction derived from the context pack:

```text
Use only the attached media items listed as evidence.
Do not infer that quote previews or older channel images were included unless
they appear in the evidence list.
If the requested evidence is missing or ambiguous, say so.
```

This is not a substitute for correct selection, but it prevents the model from
treating broad channel context as direct visual evidence.

## Observability

Every enhanced request should produce a compact audit entry with:

- `scope`: focused_reply, deictic_recent, thread_context, channel_memory, or
  broad_summary;
- selected text candidate IDs;
- selected media candidate IDs and paths count;
- excluded candidate IDs with reasons;
- response target message ID;
- original quoted parent message ID if present;
- downgrade reason when media fetch fails or scope is unavailable.

This makes future Feishu screenshots diagnosable from logs without guessing.

## Test Plan

Minimum regression cases:

- explicit reply to one image sends exactly that parent image to the model;
- explicit reply response is anchored to the triggering message, not the parent;
- current Feishu quote preview is ignored when parent media is available;
- unrelated older L2 image is excluded from focused reply;
- no explicit reply plus "上面这张图" selects the nearest recent image;
- ambiguous "上面这张图" with multiple recent images does not silently attach all
  images;
- Tier-1 memory is injected as text and never as raw media;
- per-chat memory/context remains isolated across enabled groups.

Live verification should include both `TAG-TEST` and `时令内测`, because the
multi-chat configuration is part of the plugin's expected behavior.

## Implementation Direction

Recommended implementation after review:

1. Add a `context.py` module with `ContextCandidate`, `ContextPack`, and
   `ContextSelector`.
2. Keep Feishu API/media-fetching logic in the adapter, but pass fetched parent,
   Tier-0, and Tier-1 candidates into the selector.
3. Convert the selected `ContextPack` back into the Hermes `MessageEvent`
   fields used by the existing runner.
4. Route replies by clearing or overriding the parent-thread anchor only after
   the context pack has captured the parent as evidence.
5. Add audit logging at context-pack construction time.
6. Keep the older hotfix behavior covered by tests, but express it through the
   selector instead of inline rules inside `_enhance_event`.

## Review Questions

- Should broad summary mode be implemented now, or deferred until focused reply
  and deictic recent context are stable?
- Should ambiguous deictic references ask a clarification question, or include a
  small ranked set with labels?
- Should `ContextPack` be persisted for later debugging, or only written to the
  audit log?
- What is the default media cap for inferred recent context when there is no
  explicit reply?

## Acceptance Criteria

This design is ready to implement when reviewers agree on:

- the response target vs evidence anchor split;
- the five selection scopes;
- the rule that explicit reply media narrows the evidence set by default;
- the audit fields needed to diagnose future over-injection or under-injection;
- whether ambiguous deictic references should clarify or include a small set.
