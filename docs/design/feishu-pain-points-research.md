# Feishu/Lark Bot Pain-Point Landscape: hermes-agent vs OpenClaw, and What It Means for hermes-tag

*Competitive pain research to inform the next iteration of `hermes-tag` (the Feishu/Lark context-selection layer on top of hermes-agent). Evidence deduplicated across 9 source streams. Chinese terms in parentheses where they help a Feishu-context reader.*

> **Method / provenance.** Compiled 2026-07-03 via a 9-stream research sweep (hermes-agent GitHub cards + non-cards, hermes-agent CN + EN community, OpenClaw official Lark plugin + core/community plugins + CN + EN, and the Feishu-platform substrate) → 179 raw cited pain points → dedup + synthesis. Every claim carries a source URL; confidence flags and coverage gaps are in §8. Catalyst: a Twitter/X report that the latest hermes-agent still doesn't support Feishu cards well.

---

## 1. TL;DR

- **"Doesn't support Feishu cards well" is real, current, and shared across BOTH products — and it is fundamentally a Feishu-platform (飞书平台) problem, not a hermes-specific one.** The same class of bug (append-vs-replace streaming, approval-button auth, markdown-table loss, 200340 config trap) appears independently in hermes-agent GitHub issues and in `larksuite/openclaw-lark` — because both are wrestling the same CardKit (卡片) API limits. See [hermes #21873](https://github.com/NousResearch/hermes-agent/issues/21873), [openclaw-lark #565](https://github.com/larksuite/openclaw-lark/issues/565).

- **The card catalyst breaks into five distinct sub-pains, not one:** (a) no native interactive-card abstraction; (b) approval-button clicks fail on an `open_id` vs `user_id` identity mismatch; (c) streaming emulated by message-edit / overwrite-not-append; (d) markdown tables (表格) render as raw pipes or silently truncate; (e) the gap is filled by fragile, mutually-incompatible community plugins. Detailed in §2.

- **The card verdict for hermes-tag: rich card RENDERING stays hermes-agent-core's job and should remain out of scope — but the ONE card-adjacent pain hermes-tag is uniquely positioned to own is the approval-button identity failure (`open_id`/`user_id`), because hermes-tag already owns the allowlist + per-chat identity boundary.** More in §7.

- **hermes-agent's non-card Feishu pain is dominated by connection lifecycle (连接):** WebSocket drops restart the *entire gateway* instead of the adapter reconnecting, and a Feishu App ID only permits one live WS — so multi-worker mode collapses. [#31386](https://github.com/NousResearch/hermes-agent/issues/31386), [#24807](https://github.com/NousResearch/hermes-agent/issues/24807), [#10202](https://github.com/NousResearch/hermes-agent/issues/10202), [#18693](https://github.com/NousResearch/hermes-agent/issues/18693).

- **OpenClaw's Feishu pain is dominated by packaging/upgrade churn and quota exhaustion:** repeated broken npm tarballs (missing `dist/`), plugin-rename/duplicate-id breakage, and a health-probe that burns ~27,000 API calls/month per machine, exhausting Feishu's quota within ~10 days even when idle. [#555](https://github.com/larksuite/openclaw-lark/issues/555)/[#567](https://github.com/larksuite/openclaw-lark/issues/567), [openclaw #15293](https://github.com/openclaw/openclaw/issues/15293).

- **Group-chat context (群聊上下文) is the differentiator whitespace and it is exactly hermes-tag's thesis.** Both products offer only a binary `require_mention` gate: either @-only (losing the preceding messages that set up the question) or answer-everything. Neither buffers unmentioned messages to fold in as context on a late @. That is precisely hermes-tag's late-@ / Tier-0 design. [hermes #25728](https://github.com/NousResearch/hermes-agent/issues/25728), [openclaw docs](https://docs.openclaw.ai/channels/feishu).

- **Group security (群聊安全) is a live, under-served pain — and hermes-tag's redacted-audit + allowlist boundary is a real answer.** OpenClaw's own docs recommend *not* adding the bot to groups (data-leak/permission-abuse risk); hermes leaks conversation content via auto-generated session titles visible to group members. [openclaw-lark README](https://github.com/larksuite/openclaw-lark), [hermes #15538](https://github.com/NousResearch/hermes-agent/issues/15538).

- **English-language social coverage is essentially absent.** The substantive complaints live in GitHub issue trackers and Chinese-language X/博客园/CSDN posts. This sparsity is itself a finding: any English-market positioning for hermes-tag is greenfield. (Coverage notes, streams 4 & 8.)

---

## 2. The card problem (the catalyst), dissected

The Twitter signal — *"latest hermes-agent still doesn't support Feishu cards well"* — is accurate but imprecise. "Cards well" collapses at least five separable failures, all traceable to Feishu's CardKit (卡片) API design, and all reproduced independently in both hermes-agent and OpenClaw.

### 2a. No native interactive-card abstraction (无原生卡片抽象)
hermes-agent's Feishu channel sends plain text fine but has **no first-class card abstraction**: no template rendering, no button-callback routing, no headers/markdown/dividers/buttons as supported elements. To send a card at all, a developer must hand-build card JSON and POST it via raw `urllib`/`curl` outside the gateway abstraction — parity that Discord/Telegram get natively. [hermes #21873](https://github.com/NousResearch/hermes-agent/issues/21873). This is the root gap the tweet points at, and it exists because Feishu support was originally **"closed as not planned"** ([#3663](https://github.com/NousResearch/hermes-agent/issues/3663)) and grew as a bolt-on.

### 2b. Approval-button clicks fail — the `open_id` / `user_id` auth mismatch (审批按钮鉴权失败)
This is the sharpest, most under-appreciated sub-pain, and it is a **platform-substrate** root cause:

- Feishu's `card.action.trigger` callback identifies the clicker by `open_id`, and `open_id` is **application-scoped (应用级)** — the same person has a *different* `open_id` under each app. `user_id` is a **sensitive field (敏感字段)** returned only if the app enabled the `contact:user.employee_id:readonly` permission. [Feishu card-callback doc](https://open.feishu.cn/document/feishu-cards/card-callback-communication?lang=zh-CN).
- hermes stores the allowlist (`FEISHU_ALLOWED_USERS`) as `user_id`, but card events carry only `open_id` → an allow-listed user's approval click is rejected as unauthorized and the gated command times out. [hermes #37252](https://github.com/NousResearch/hermes-agent/issues/37252).
- OpenClaw hits the same root in groups: `checkBotMentioned()` fails because the pushed `open_id` doesn't match the receiving bot's app-scoped id. [openclaw #40768](https://github.com/openclaw/openclaw/issues/40768).
- Related failure modes stack on top: button clicks fall through to an unimplemented `/card` command ([hermes #7675](https://github.com/NousResearch/hermes-agent/issues/7675), [#11600](https://github.com/NousResearch/hermes-agent/issues/11600)); or clicks return **error 200340** unless three separate Developer-Console steps are done (subscribe `card.action.trigger`, enable the Interactive Card toggle, set the Card Request URL) — a silent trap because *sending* cards works even when *receiving* callbacks isn't configured ([hermes #6893](https://github.com/NousResearch/hermes-agent/issues/6893), [#8764](https://github.com/NousResearch/hermes-agent/issues/8764), [docs](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/feishu)). OpenClaw's parallel: approval cards silently dropped in DM because the plugin registers only approval *auth* and no *delivery* transport ([openclaw-lark #569](https://github.com/larksuite/openclaw-lark/issues/569)).

### 2c. Streaming emulated by message-edit / overwrite-not-append (流式输出：覆盖而非追加)
- **hermes:** `streaming.enabled` fakes streaming by repeatedly editing the last message via `im.v1.message.update` instead of using Feishu's native CardKit streaming. Result: a grey **"edited" (已编辑)** badge on every flush, a tight **~50 QPM per-message** cap, and a full-message re-render (flashing) rather than typewriter append. CardKit would allow **5+ QPS per card**. [hermes #16084](https://github.com/NousResearch/hermes-agent/issues/16084), [#6363](https://github.com/NousResearch/hermes-agent/issues/6363).
- **OpenClaw:** the CardKit path is wired up but buggy in *both* directions — each chunk either **overwrites** the card so only the last character survives ([openclaw-lark #565](https://github.com/larksuite/openclaw-lark/issues/565), a self-upgrade regression [#561](https://github.com/larksuite/openclaw-lark/discussions/561)), or **appends cumulatively** so text repeats 2–5× in a staircase ([openclaw #38943](https://github.com/openclaw/openclaw/issues/38943)). A card-API `400` with no plain-text fallback and no TTL can **permanently lock a session for 13+ hours** ([openclaw #43322](https://github.com/openclaw/openclaw/issues/43322)).
- **Both** lack token-level typewriter streaming as a stable feature ([openclaw-lark #384](https://github.com/larksuite/openclaw-lark/issues/384)).

### 2d. Markdown tables and long content lost (表格/长内容丢失)
- hermes detects a markdown table and **forces plain-text mode**, leaking raw `|`/`-` pipes (or a blank message if sent as `post`). The Card JSON 2.0 table fix is still open. [hermes #21866](https://github.com/NousResearch/hermes-agent/issues/21866), [#21326](https://github.com/NousResearch/hermes-agent/issues/21326).
- Platform root: Feishu cards **do not render GFM tables** at all (plain text / code block), require the CardKit v2 `table` component (client v7.4+, **max 5 tables per card**), and cap cards at **~30 KB with silent truncation** and **30,000 chars**. [Feishu-to-table repo](https://github.com/chapaofan/Hermes-feishu-to-table), [openclaw #13267](https://github.com/openclaw/openclaw/issues/13267), [openclaw-lark #46 / ErrCode 11310](https://github.com/larksuite/openclaw-lark/issues/46).

### 2e. Community plugins fill the gap — fragmented and fragile (社区插件填补空白，但脆弱)
Because core lacks CardKit streaming, **two incompatible hermes community plugins** exist ([baileyh8/hermes-feishu-streaming-card](https://github.com/baileyh8/hermes-feishu-streaming-card), [Cheerwhy/hermes-lark-streaming](https://github.com/Cheerwhy/hermes-lark-streaming)), each missing features (image→`img_key` resolution, multi-bot support, `/stop` handling, multi-language). Neither is officially endorsed; the ask to consolidate into core is open ([hermes #33854](https://github.com/NousResearch/hermes-agent/issues/33854)). Worse, they monkey-patch / AST-inject into `run.py`/`scheduler.py` and **break on every hermes upgrade**.

**Verdict on the catalyst:** "cards well" = a bundle of (native abstraction) + (identity-correct callbacks) + (append-correct streaming) + (table rendering). Items 2a/2c/2d are **rendering/transport = agent-core territory**. Item 2b's identity layer is **the one piece adjacent to hermes-tag's existing allowlist ownership** (see §7).

---

## 3. hermes-agent Feishu pain points (grouped by category)

### Cards / interactive (卡片) — the catalyst cluster
| Pain | Sev | Source |
|---|---|---|
| No native interactive-card abstraction; cards need raw urllib/curl | P1 | [#21873](https://github.com/NousResearch/hermes-agent/issues/21873) |
| Approval-button click → error 200340 unless 3 console steps done; ~537s timeout blocks agent | P0 | [#6893](https://github.com/NousResearch/hermes-agent/issues/6893), [#8764](https://github.com/NousResearch/hermes-agent/issues/8764), [#20596](https://github.com/NousResearch/hermes-agent/issues/20596) |
| Allow-listed users rejected on click (`open_id` vs `user_id`) | P0 | [#37252](https://github.com/NousResearch/hermes-agent/issues/37252) |
| Button clicks fall through to unimplemented `/card` command | P1 | [#7675](https://github.com/NousResearch/hermes-agent/issues/7675), [#11600](https://github.com/NousResearch/hermes-agent/issues/11600) |
| Markdown tables render as raw pipes / blank; Card 2.0 table support missing | P1 | [#21866](https://github.com/NousResearch/hermes-agent/issues/21866), [#21326](https://github.com/NousResearch/hermes-agent/issues/21326) |
| Inbound markdown escaping leaks `\*\*bold\*\*` into replies | P2 | [#27469](https://github.com/NousResearch/hermes-agent/issues/27469) |
| No optimistic UI on click; can't tell it registered | P2 | [#8358](https://github.com/NousResearch/hermes-agent/issues/8358) |
| No model/timing/token card footer (blocked by text→card cross-type limit) | P2 | [#9978](https://github.com/NousResearch/hermes-agent/issues/9978) |

### Streaming (流式)
| Pain | Sev | Source |
|---|---|---|
| Streaming faked via `im.v1.message.update`: "edited" badge, ~50 QPM, full re-render | P1 | [#16084](https://github.com/NousResearch/hermes-agent/issues/16084), [#6363](https://github.com/NousResearch/hermes-agent/issues/6363) |
| No consolidated CardKit streaming; two competing community plugins | P1 | [#33854](https://github.com/NousResearch/hermes-agent/issues/33854) |
| Streamed content drops/reorders chars; tables/code as raw markdown; tool-calls invisible | P1 | [baileyh8 README](https://github.com/baileyh8/hermes-feishu-streaming-card), [Cheerwhy README](https://github.com/Cheerwhy/hermes-lark-streaming) |

### Connection (连接) — the heaviest non-card cluster
| Pain | Sev | Source |
|---|---|---|
| WS disconnect (~30 min) restarts the ENTIRE gateway instead of adapter reconnect | P0 | [#31386](https://github.com/NousResearch/hermes-agent/issues/31386) (issue# confidence: medium) |
| WS ping-timeout swallowed by `except Exception: pass` → adapter "goes deaf" | P1 | [#24807](https://github.com/NousResearch/hermes-agent/issues/24807) |
| `gateway --replace`/dashboard restart kills WSS with no CLOSE frame → CLOSE-WAIT, dead routing | P0 | [#10202](https://github.com/NousResearch/hermes-agent/issues/10202) |
| Dropped inbound msgs "before adapter loop ready"; SDK overwrites reconnect tuning | P1 | [#5499](https://github.com/NousResearch/hermes-agent/issues/5499) |
| Proxy/VPN routes WS through wrong proxy; needs `no_proxy` hack | P1 | [#17036](https://github.com/NousResearch/hermes-agent/issues/17036) |
| Event subscription (`im.message.receive_v1` / 长连接) easy to miss → zero messages | P2 | [blog](https://blog.csdn.net/weixin_66401877/article/details/160017098) |

### Group-chat (群聊)
| Pain | Sev | Source |
|---|---|---|
| Group @mention messages never reach gateway (legacy EventDispatcher, not Channel SDK) | P0 | [#50656](https://github.com/NousResearch/hermes-agent/issues/50656) |
| Group replies misrouted to sender's DM despite correct `oc_...` chat_id | P1 | [#23698](https://github.com/NousResearch/hermes-agent/issues/23698) |
| `require_mention` can't be disabled even with `FEISHU_GROUP_POLICY=open` | P2 | [#5465](https://github.com/NousResearch/hermes-agent/issues/5465) |
| No buffering of unmentioned messages → lost pre-@ context (binary gate) | P2 | [#25728](https://github.com/NousResearch/hermes-agent/issues/25728) |
| Default allowlist blocks ALL messages until config edited → looks dead | P1 | [aliyun blog](https://developer.aliyun.com/article/1725007) |

### Media (媒体)
| Pain | Sev | Source |
|---|---|---|
| Native voice notes classified AUDIO (never transcribed) → spoken msg silently ignored | P1 | [#28993](https://github.com/NousResearch/hermes-agent/pull/28993) |
| Image/file uploads fail with HTTP/2 stream reset (urllib3-future) | P1 | [#32224](https://github.com/NousResearch/hermes-agent/issues/32224) |
| `send_image_file` passes raw bytes → "Can't recognize image format" | P1 | [#6912](https://github.com/NousResearch/hermes-agent/issues/6912) |
| Missing `send_file` → `/btw` media fails silently; file+caption hits error 230055 | P1 | [#10826](https://github.com/NousResearch/hermes-agent/issues/10826) |
| Voice replies render as file attachment (missing `duration`) not voice bubble | P2 | [#16524](https://github.com/NousResearch/hermes-agent/issues/16524) |
| GIFs downgraded to file attachments; `.txt`/`.md` auto-injected into text | P2 | [docs](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/feishu) |

### Sessions / deployment (会话/部署)
| Pain | Sev | Source |
|---|---|---|
| Multi-worker `--replace` incompatible with Feishu's single-WS-per-App-ID limit → process group collapse | P1 | [#18693](https://github.com/NousResearch/hermes-agent/issues/18693) |
| WS sessions not closed on restart → zombie sessions pile up in DB | P1 | [#9090](https://github.com/NousResearch/hermes-agent/issues/9090) |
| Windows: `lark-oapi` missing from venv; `status.py os.kill(pid,0)` → WinError 11 | P1 | [aliyun blog](https://developer.aliyun.com/article/1725007) (confidence: medium) |
| Docker: config writes fail without `chmod 777`; `docker run -it` mis-parses stdin | P2 | [openeuler blog](https://openeuler.csdn.net/69eb39930a2f6a37c5a5d850.html) |
| CLI pairing handshake (`hermes pairing approve feishu <code>`) + manual `/sethome` | P2 | [Huawei guide](https://support.huaweicloud.com/bestpractice-flexusl/flexusl_bp_0021.html) |

### Rate-limits / security / docs-base
| Pain | Sev | Source |
|---|---|---|
| 429/timeout drops the user's own message from the transcript (agent forgets) | P1 | [#7100](https://github.com/NousResearch/hermes-agent/issues/7100) |
| Missing scopes (`contact:contact.base:readonly`, `im:resource`) fail silently | P1 | [openeuler blog](https://openeuler.csdn.net/69eb39930a2f6a37c5a5d850.html) |
| **Session titles leak private conversation content to group members** | P1 | [#15538](https://github.com/NousResearch/hermes-agent/issues/15538) |
| No Feishu ecosystem (Docs/Sheets/Bitable/Calendar/Wiki/Drive) integration | P2 | [#10356](https://github.com/NousResearch/hermes-agent/issues/10356) |
| No handling of Feishu document comments (文档评论) | P2 | [#11465](https://github.com/NousResearch/hermes-agent/issues/11465) |

---

## 4. OpenClaw Feishu pain points (grouped)

### Deployment / packaging / plugin-coexistence (部署/打包/插件共存) — OpenClaw's signature pain
| Pain | Sev | Source |
|---|---|---|
| **Official plugin & built-in feishu channel are mutually exclusive** (must set built-in `enabled:false`) | P1 | [discussion #335](https://github.com/larksuite/openclaw-lark/discussions/335) |
| **`doctor --fix` re-enables built-in feishu → duplicate replies** | P1 | [openclaw #44722](https://github.com/openclaw/openclaw/issues/44722) |
| **Duplicate plugin id** (global + local both present) → later plugin overridden | P1 | [treasury-manager blog](https://www.cnblogs.com/treasury-manager/p/19601042), [openclaw-lark #10](https://github.com/larksuite/openclaw-lark/issues/10) |
| Broken npm tarball: `main`→`./dist` but no `dist/` shipped (recurs across versions) | P0 | [#555](https://github.com/larksuite/openclaw-lark/issues/555), [#567](https://github.com/larksuite/openclaw-lark/issues/567) |
| Missing `@larksuiteoapi/node-sdk` dep / `workspace:*` EUNSUPPORTEDPROTOCOL | P0 | [openclaw #23611](https://github.com/openclaw/openclaw/issues/23611) |
| Plugin-SDK breaking refactor left official plugin incompatible with core | P1 | [openclaw #53003](https://github.com/openclaw/openclaw/issues/53003) |
| Plugin not discovered ("unknown channel id: feishu") after loader refactor | P0 | [openclaw #60196](https://github.com/openclaw/openclaw/issues/60196) |
| Rename broke upgrade path (`-tools` → base); version/npm skew | P1/P2 | [#225](https://github.com/larksuite/openclaw-lark/discussions/225), [#324](https://github.com/larksuite/openclaw-lark/discussions/324) |
| Old-plugin residue → migration ID mismatch/auth errors | P0 | [LexLuc blog](https://www.cnblogs.com/LexLuc/p/19904568) |
| Windows-native install fails `spawn EINVAL` (docs push WSL2) | P1 | [openclaw #27273](https://github.com/openclaw/openclaw/issues/27273) |

### Streaming / cards (流式/卡片) — same catalyst, OpenClaw flavor
| Pain | Sev | Source |
|---|---|---|
| Streaming card shows only last char (overwrite-not-append) | P0 | [#565](https://github.com/larksuite/openclaw-lark/issues/565) |
| Streaming card duplicates content 2–5× (append-not-replace) | P1 | [openclaw #38943](https://github.com/openclaw/openclaw/issues/38943) |
| Card API 400 → permanent session lock (13+ h no-reply) | P0 | [openclaw #43322](https://github.com/openclaw/openclaw/issues/43322) |
| Two competing delivery paths race; built-in wins, kills streaming cards | P1 | [openclaw #11830](https://github.com/openclaw/openclaw/issues/11830) |
| `blockStreamingDefault:on` silently drops all replies (replies=0) | P0 | [openclaw #38824](https://github.com/openclaw/openclaw/issues/38824) |
| Streaming cards created despite `streaming=false`; output truncated to tail | P1 | [openclaw #10078](https://github.com/openclaw/openclaw/issues/10078) |
| `message` tool `send` requires a `card` param → breaks proactive text | P1 | [openclaw #53295](https://github.com/openclaw/openclaw/issues/53295) |
| Subagent completions render as plain post, not card | P2 | [openclaw-lark #564](https://github.com/larksuite/openclaw-lark/issues/564) |
| Plugin footer config rejected by core schema (`additionalProperties:false`) | P2 | [openclaw #56882](https://github.com/openclaw/openclaw/issues/56882) |

### Connection / no-response (连接/无响应)
| Pain | Sev | Source |
|---|---|---|
| Gateway process death = silent Feishu disconnect (single point of failure) | P0 | [SegmentFault](https://segmentfault.com/a/1190000047645779) |
| **Infinite reconnect loop (890+/24h); health probe reports "works" while offline** | P0 | [openclaw #59753](https://github.com/openclaw/openclaw/issues/59753) |
| Messages silently dropped by routing/policy (无 @、白名单、`drop`) | P1 | [qiniushanghai blog](https://www.cnblogs.com/qiniushanghai/p/19698320) |
| HTTP proxy breaks auth (plain HTTP→443; `tenant_access_token` undefined) | P1 | [openclaw #48949](https://github.com/openclaw/openclaw/issues/48949), [#361](https://github.com/larksuite/openclaw-lark/discussions/361) |
| Bot WS fails (`1000040350 system busy` / PingInterval crash), esp. cross-region | P1 | [#342](https://github.com/larksuite/openclaw-lark/discussions/342) |
| Silent event-subscription trap: save fails if gateway not running; must publish app | P1 | [Stack Junkie](https://www.stack-junkie.com/blog/openclaw-feishu-setup-guide) |

### Rate-limits (配额)
| Pain | Sev | Source |
|---|---|---|
| **Health-probe `bot/v3/info` every 60s → ~27,000 calls/mo; quota gone in ~10 days idle** | P0 | [openclaw #15293](https://github.com/openclaw/openclaw/issues/15293), [AlexAnys](https://github.com/AlexAnys/openclaw-feishu) |
| Keeps hitting `bot/info` after stop signal → 429 (no backoff, closed stale) | P1 | [openclaw #23894](https://github.com/openclaw/openclaw/issues/23894) |
| 429 with no failover → same msg reprocessed 95+× in a loop | P1 | [openclaw #58442](https://github.com/openclaw/openclaw/issues/58442) |

### Group-chat + security (群聊/安全) — OpenClaw's structural fit-gap
| Pain | Sev | Source |
|---|---|---|
| **Official docs recommend NOT adding bot to groups (data-leak/permission-abuse)** | P2 | [openclaw-lark README](https://github.com/larksuite/openclaw-lark) |
| **Group attack surface: impersonation, prompt-injection, context-poisoning/DoS** | P0 | [feishu.cn article](https://www.feishu.cn/content/article/7615520954977881029) |
| Hardcoded permission check: only app-owner may use Bitable/Calendar → multi-user broken | P1 | [openclaw-lark #376](https://github.com/larksuite/openclaw-lark/issues/376) |
| Group card callback returns p2p `chat_id` → reply misrouted to DM | P1 | [openclaw-lark #385](https://github.com/larksuite/openclaw-lark/issues/385) |
| Reply-to (no @) processed but never delivered (replies=0) | P1 | [openclaw-lark #385](https://github.com/larksuite/openclaw-lark/issues/385) |
| @-mention unrecognized with multiple bots (app-scoped `open_id`) | P1 | [openclaw #40768](https://github.com/openclaw/openclaw/issues/40768) |
| No true multi-user isolation in DMs (single-user positioning; 1 agent/person) | P1 | [multi-agent docs](https://docs.openclaw.ai/concepts/multi-agent) |
| Dynamic agent isolation is NOT a security boundary (shared host/process) | P1 | [feishu docs](https://docs.openclaw.ai/channels/feishu) |

### Sessions / media (会话/媒体)
| Pain | Sev | Source |
|---|---|---|
| `refresh_token` race across cron subagents → 20064 REFRESH_TOKEN_REVOKED, manual re-auth | P1 | [openclaw-lark #557](https://github.com/larksuite/openclaw-lark/issues/557) |
| Stale `.jsonl.lock` → permanent request timeouts; regenerated on restart | P1 | [openclaw #45726](https://github.com/openclaw/openclaw/issues/45726) |
| `dmPolicy` default silently changed open→pairing (no migration) | P1 | [Stack Junkie](https://www.stack-junkie.com/blog/openclaw-feishu-setup-guide) |
| Media upload 400 regression after node-sdk bump; local images sent as plain-text path | P1 | [openclaw-lark #568](https://github.com/larksuite/openclaw-lark/issues/568), [openclaw #27256](https://github.com/openclaw/openclaw/issues/27256) |
| Inbound Feishu image crashes whole gateway (path bug, 100% repro) | P0 | [openclaw #44778](https://github.com/openclaw/openclaw/issues/44778) |
| Uploaded `file_token` unusable in Bitable attachment fields (hardcoded `explorer`) | P1 | [openclaw-lark #582](https://github.com/larksuite/openclaw-lark/issues/582) |

---

## 5. Shared Feishu-platform substrate pains (平台底层约束)

These are the API-level root causes that constrain **both** products — and any future hermes-tag work. They are the "declined as agent-core / actually platform" bucket.

| Substrate constraint | Effect on bots | Source |
|---|---|---|
| **`open_id` is app-scoped; `user_id` is a sensitive scope** | The root of every approval-button/@-mention identity bug (§2b) — no stable cross-app identity without a sensitive permission + ID-conversion round-trip | [card-callback doc](https://open.feishu.cn/document/feishu-cards/card-callback-communication?lang=zh-CN) |
| **Card callback token: 30-min validity, max 2 updates, 3-s response deadline** | Long-running button actions must decouple ack from work and switch to CardKit entity APIs | [card-callback doc](https://open.feishu.cn/document/feishu-cards/card-callback-communication?lang=zh-CN) |
| **CardKit streaming: 10 ops/sec/entity, auto-closes after 10 min, entity dies at 14 days** | Token streaming must batch/debounce; long agent runs get cut off | [streaming doc](https://open.feishu.cn/document/cardkit-v1/streaming-updates-openapi-overview?lang=zh-CN) |
| **Streaming mode ⊥ interactivity** (can't update a streaming card on callback) | Live-answer card + inline approve/cancel needs a state machine flipping streaming off per interaction | [streaming doc](https://open.feishu.cn/document/cardkit-v1/streaming-updates-openapi-overview?lang=zh-CN) |
| **Group bot sees only @-mentions unless sensitive `im:message.group_msg` granted** | Ambient group context (Tier-0) requires a sensitive scope that admin review often blocks | [add-bot-to-group doc](https://open.feishu.cn/document/uAjLw4CM/ukzMukzMukzM/develop-robots/add-bot-to-external-group?lang=zh-CN) |
| **Cards don't render GFM tables; CardKit table max 5/card, client v7.4+; card ~30 KB silent truncation** | LLM table-heavy output breaks or gets cut without warning | [Feishu-to-table](https://github.com/chapaofan/Hermes-feishu-to-table), [openclaw #13267](https://github.com/openclaw/openclaw/issues/13267) |
| **Send limits 5 QPS + 100/min per bot per tenant; NOT self-raisable** | Streaming-by-edit + fan-out + retry loops trip 429; only a CSM can raise | [frequency-control doc](https://open.feishu.cn/document/server-docs/api-call-guide/frequency-control) |
| **Card messages not editable via standard edit API (only text/rich-text); batch cards can't be updated** | Splits the update path into incompatible regimes | [im-v1 FAQ](https://open.feishu.cn/document/server-docs/im-v1/faq) |
| **Lark International has no WebSocket long-connection → webhook + 内网穿透 required** | Cross-region/self-host adds tunnel + public-exposure burden | [AlexAnys](https://github.com/AlexAnys/openclaw-feishu), [openclaw #48949](https://github.com/openclaw/openclaw/issues/48949) |
| **Recall requires owner/admin + ≤1 year; batch messages can't be recalled** | Bot can't self-remediate a leaked secret in group | [openclaw #51422](https://github.com/openclaw/openclaw/issues/51422) |
| **Personal vs enterprise Feishu are separate systems** | Personal-account bot can't be pulled into enterprise groups | [feishu.cn article](https://www.feishu.cn/content/article/7613321214802643921) |
| **30 MB media cap; voice needs ffmpeg Ogg/Opus transcode** | Voice silently degrades to file attachment if ffmpeg missing | [openclaw docs](https://docs.openclaw.ai/channels/feishu) |

---

## 6. Side-by-side comparison

| Pain category | hermes-agent | OpenClaw | Shared / platform |
|---|---|---|---|
| **Native card abstraction** | ✗ absent; raw curl ([#21873](https://github.com/NousResearch/hermes-agent/issues/21873)) | ~ CardKit wired but buggy ([#565](https://github.com/larksuite/openclaw-lark/issues/565)) | Card API design is the ceiling |
| **Approval-button auth** | ✗ `user_id`/`open_id` mismatch, 200340 ([#37252](https://github.com/NousResearch/hermes-agent/issues/37252), [#6893](https://github.com/NousResearch/hermes-agent/issues/6893)) | ✗ auth-only, no delivery ([#569](https://github.com/larksuite/openclaw-lark/issues/569)) | **Root = app-scoped id + sensitive scope** |
| **Streaming** | ~ message-edit hack, "edited" badge, 50 QPM ([#16084](https://github.com/NousResearch/hermes-agent/issues/16084)) | ✗ overwrite/append bugs, 13h lock ([#43322](https://github.com/openclaw/openclaw/issues/43322)) | 10 ops/s, 10-min auto-close, streaming⊥interactivity |
| **Tables / long content** | ✗ raw pipes, plain-text forced ([#21866](https://github.com/NousResearch/hermes-agent/issues/21866)) | ✗ ErrCode 11310, 30 KB truncation ([#46](https://github.com/larksuite/openclaw-lark/issues/46)) | Cards can't render GFM tables |
| **Connection lifecycle** | ✗✗ full-gateway restart on WS drop ([#31386](https://github.com/NousResearch/hermes-agent/issues/31386), [#10202](https://github.com/NousResearch/hermes-agent/issues/10202)) | ✗✗ infinite zombie reconnect ([#59753](https://github.com/openclaw/openclaw/issues/59753)) | Single-WS-per-App; Lark-intl no WS |
| **Group @mention delivery** | ✗ legacy dispatcher, no group events ([#50656](https://github.com/NousResearch/hermes-agent/issues/50656)) | ✗ multi-bot open_id mismatch ([#40768](https://github.com/openclaw/openclaw/issues/40768)) | @-only default; group_msg is sensitive |
| **Group context (pre-@ buffering)** | ✗ binary gate, no buffer ([#25728](https://github.com/NousResearch/hermes-agent/issues/25728)) | ✗ binary gate ([docs](https://docs.openclaw.ai/channels/feishu)) | **Whitespace — nobody solves it** |
| **Rate-limit / quota** | ~ webhook 120/60s, 429 drops msg ([#7100](https://github.com/NousResearch/hermes-agent/issues/7100)) | ✗✗ health-probe quota burn ([#15293](https://github.com/openclaw/openclaw/issues/15293)) | 5 QPS un-raisable |
| **Media** | ✗ HTTP/2 reset, raw bytes, no send_file ([#32224](https://github.com/NousResearch/hermes-agent/issues/32224), [#6912](https://github.com/NousResearch/hermes-agent/issues/6912)) | ✗ 400 regression, gateway crash ([#568](https://github.com/larksuite/openclaw-lark/issues/568), [#44778](https://github.com/openclaw/openclaw/issues/44778)) | 30 MB cap, ffmpeg voice |
| **Deployment / packaging** | ~ Windows/Docker traps ([aliyun](https://developer.aliyun.com/article/1725007)) | ✗✗ broken tarballs, dup-id, migration ([#555](https://github.com/larksuite/openclaw-lark/issues/555), [#335](https://github.com/larksuite/openclaw-lark/discussions/335)) | npm/SDK churn |
| **Sessions / auth durability** | ✗ zombie sessions on restart ([#9090](https://github.com/NousResearch/hermes-agent/issues/9090)) | ✗ refresh_token race, lock files ([#557](https://github.com/larksuite/openclaw-lark/issues/557), [#45726](https://github.com/openclaw/openclaw/issues/45726)) | token-refresh semantics |
| **Group security / privacy** | ✗ session titles leak content ([#15538](https://github.com/NousResearch/hermes-agent/issues/15538)) | ✗✗ "don't use in groups" ([README](https://github.com/larksuite/openclaw-lark)); attack surface ([article](https://www.feishu.cn/content/article/7615520954977881029)) | **Whitespace — nobody solves it well** |

Legend: ✗✗ severe/unsolved · ✗ present · ~ partial/mitigated.

---

## 7. Implications for hermes-tag

hermes-tag's charter is narrow and deliberate: a **context-selection layer** that overrides the built-in Feishu platform, adds bounded multimodal context selection (late-@, per-chat Tier-0/Tier-1 memory), redacted audit, and an `enabled_chats` allowlist as the only storage/processing boundary. It has **explicitly declined rich/streaming card rendering** as agent-core territory. Sorting each pain against that charter:

### Ownership map

| Pain | Owner | Rationale |
|---|---|---|
| Native card abstraction, streaming append/overwrite, table rendering, footer metadata | **hermes-agent-core** | Pure rendering/transport; not context selection. hermes-tag rightly stays out. |
| Card callback token limits, CardKit 10 ops/s, group_msg sensitivity, 5 QPS, table ceilings | **Feishu-platform** | Immutable API limits; anyone can only design around them. |
| Approval-button `open_id`/`user_id` identity mismatch | **hermes-tag-adjacent (candidate to own)** | hermes-tag *already* owns the allowlist + per-chat identity boundary (`admins`, `bot_open_id`, `enabled_chats`). It's the one card-touching pain that lives at the identity layer it controls. |
| Pre-@ group-context buffering / late-@ context | **hermes-tag (core thesis — already shipped)** | Exactly Tier-0 + `ContextSelector` `deictic_recent`/`thread`/`focused_reply`. |
| Group content-leak via session titles; group attack surface | **hermes-tag (already partially covered)** | Redacted audit + "never stores message bodies" + allowlist boundary is a direct answer. |
| Per-chat memory isolation; no cross-workspace bleed | **hermes-tag (already covered)** | The privacy promise; directly counters OpenClaw's "no true multi-user isolation" gap. |
| WS reconnect, packaging, media transport, quota burn | **hermes-agent-core / substrate** | Below hermes-tag's seam; it inherits whatever core does. Worth *documenting* as known pins, not fixing. |

### Prioritized shortlist for the next iteration

**P0 — own the group-context + group-privacy story explicitly (this is the differentiator, and it's already your thesis).**
The single clearest whitespace across both competitors is that group context is a **binary `require_mention` gate** ([hermes #25728](https://github.com/NousResearch/hermes-agent/issues/25728), [openclaw docs](https://docs.openclaw.ai/channels/feishu)) and group *use* is actively discouraged for security ([openclaw README](https://github.com/larksuite/openclaw-lark), [attack-surface article](https://www.feishu.cn/content/article/7615520954977881029)). hermes-tag already solves both (late-@ Tier-0 + redacted audit + allowlist). **Action:** make this the headline in positioning and docs — a benchmarked "late-@ picks the 3 messages that matter, and never the whole transcript, and never leaks bodies to group members" demo, contrasted against the competitors' binary gate and their session-title leak. This is documentation/positioning + eval work, not new rendering.

**P1 — own the approval-button identity fix at the seam you already control.**
The `open_id`/`user_id` mismatch ([hermes #37252](https://github.com/NousResearch/hermes-agent/issues/37252)) and multi-bot app-scoped-id failure ([openclaw #40768](https://github.com/openclaw/openclaw/issues/40768)) are the one card-adjacent class rooted in *identity*, which hermes-tag already handles (`bot_open_id`, `admins` as open_ids, allowlist). **Action:** provide a small, correct identity-resolution helper on hermes-tag's seam that normalizes allowlist/admin checks to `open_id` (the field callbacks actually carry) and documents the sensitive `contact:user.employee_id:readonly` requirement. This does *not* mean rendering cards — it means making the identity checks that gate any interaction correct where hermes-tag already gates them. Justified because it's within charter (identity/allowlist), high-severity (P0 in both products), and platform-root-caused so a clean helper is durably valuable.

**P1 — harden the ambient-context capability against the sensitive-scope reality.**
Tier-0 depends on `im:message.group_msg` (敏感权限), which admin review often blocks ([add-bot-to-group doc](https://open.feishu.cn/document/uAjLw4CM/ukzMukzMukzM/develop-robots/add-bot-to-external-group?lang=zh-CN)), and DingTalk already lacks any equivalent (per your own README). **Action:** detect at startup whether `im:message.group_msg` is actually granted; if not, degrade gracefully and *surface a clear diagnostic* (this directly counters the whole "silent no-response" class in both competitors — [hermes default-allowlist trap](https://developer.aliyun.com/article/1725007), [openclaw silent-drop](https://www.cnblogs.com/qiniushanghai/p/19698320)). Turn the substrate limit into a first-class, legible capability check.

**P2 — revisit rich card RENDERING? Recommendation: DON'T build it; do publish an interop stance.**
The Twitter signal is genuine, but the evidence says the card gap is (a) core/platform-rooted, (b) already contested by two hermes community plugins and OpenClaw's own buggy CardKit path, and (c) a maintenance treadmill (upgrade-fragile monkey-patching — [#33854](https://github.com/NousResearch/hermes-agent/issues/33854)). Building a rendering layer would pull hermes-tag off its context-selection thesis into a crowded, core-owned fight it can't win cleanly. **However**, the tweet still deserves an answer: since hermes-tag *overrides* the Feishu platform, document explicitly how it **coexists with** (does not fight) a streaming-card plugin — i.e., hermes-tag owns context selection and mention gating; card rendering is delegated downstream. That converts "doesn't support cards" from a perceived hermes-tag gap into a clean separation-of-concerns statement, without taking on rendering.

**P2 — document the inherited substrate pins as a "known limits" page.**
Single-WS-per-App-ID ([hermes #18693](https://github.com/NousResearch/hermes-agent/issues/18693)), Lark-International no-WebSocket, 30 MB media cap, 5 QPS send limit, personal-vs-enterprise separation. hermes-tag can't fix these but users hit them and blame the plugin. A short "these are Feishu/agent-core limits, not hermes-tag" page pre-empts the misdiagnosis that fills both competitors' issue trackers.

**Explicitly NOT hermes-tag's to own (leave to core):** WS reconnect lifecycle, npm/packaging, media byte-handling, quota/health-probe behavior, streaming transport. Flag them upstream; don't absorb them.

---

## 8. Confidence & gaps

**Well-substantiated (high confidence, page-verified):**
- The entire card catalyst (2a–2e) — corroborated across directly-fetched hermes issues, OpenClaw core + plugin issues, and official Feishu docs. The `open_id`/`user_id` root cause is triple-sourced (hermes [#37252](https://github.com/NousResearch/hermes-agent/issues/37252), openclaw [#40768](https://github.com/openclaw/openclaw/issues/40768), [Feishu callback doc](https://open.feishu.cn/document/feishu-cards/card-callback-communication?lang=zh-CN)).
- Connection-lifecycle pain in both products (multiple verified issues each).
- OpenClaw packaging/upgrade churn and health-probe quota burn (repeated, cross-sourced in EN + 中文).
- All platform-substrate constraints (§5) trace to official Feishu docs.

**Thinner / flagged (medium-low confidence):**
- **hermes issue #31386** (30-min WS drop → full restart): issue *number* unverified in the source run (surfaced via redirect); the *symptom* is corroborated by verified [#10202](https://github.com/NousResearch/hermes-agent/issues/10202)/[#24807](https://github.com/NousResearch/hermes-agent/issues/24807). Treat the number as soft.
- **Windows deployment bugs** (missing `lark-oapi`, `status.py` WinError, allowlist-blocks-all): rest on a single [aliyun tutorial's](https://developer.aliyun.com/article/1725007) paraphrase, not the underlying source — medium.
- **Community plugin READMEs** are self-serving about the gap they fill; their concrete claims align with core issues but confidence is medium by nature.
- OpenClaw **latency** ([openclaw-lark #251](https://github.com/larksuite/openclaw-lark/discussions/251)) and **CardKit 30 KB truncation** ([openclaw #13267](https://github.com/openclaw/openclaw/issues/13267)) are lower-confidence (search-summary / single-thread).

**Not found / coverage gaps:**
- **English-language social sentiment is essentially absent.** No substantive English Reddit/HN/X thread on Feishu cards surfaced for either product; the real discussion is GitHub issues + Chinese posts. The original English trigger tweet was not located as a distinct URL — the closest verifiable public sentiment is Chinese. Any English-market positioning is greenfield.
- No verified issue specific to Feishu **message recall/edit/delete** handling in hermes (only the platform-limit and an OpenClaw feature request [#51422](https://github.com/openclaw/openclaw/issues/51422)).
- Several Feishu-Base/Docs tool-API pains ([openclaw-lark #582](https://github.com/larksuite/openclaw-lark/issues/582), #580, #86) were not exhaustively fetched — a follow-up pass could add 2–3 more docs/Base findings.
- Whether hermes **v0.18.0** ("Judgement Release") fixed any card bugs was not independently confirmed; card issues dated mid-June 2026 (v0.17.0) suggest cards remained unsolved in the latest version at collection time, consistent with the tweet.

**To validate on the live deployment:**
1. Does hermes-tag's current allowlist/admin check actually receive `open_id` (not `user_id`) on any interactive path, and does it match correctly? (Confirms whether P1 identity work is needed.)
2. Is `im:message.group_msg` genuinely granted in the pilot app, and does Tier-0 silently no-op if it isn't? (Confirms the P1 diagnostic value.)
3. Behaviorally verify the late-@ context selection against a scripted group transcript to produce the P0 benchmark demo.
