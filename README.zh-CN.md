# Hermes Tag

**先发图、再说话、最后才 @——该看的它都在。**

用 Hermes 把 Claude-Tag 式能力带到飞书 / Lark（以及 Slack）。你先发几张图、补一段说明，别人插几句讨论——等你终于 @ 它，它取回的是**那几张图的原图 + 你的说明 + 相关的讨论**，而不是只看你最后那一句，也不是把整个群史倒给它。平时一句不答，只在被 @ 时，精准取回“该看的那几条”。

[English](README.md) · [中文](README.zh-CN.md)

![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg) ![Version: 0.5.0](https://img.shields.io/badge/version-0.5.0-blue.svg) ![hermes-agent: tested against v0.22.5](https://img.shields.io/badge/hermes--agent-tested%20against%20v0.22.5-blue.svg) ![Python: 3.14](https://img.shields.io/badge/python-3.14-blue.svg)

<p align="center"><img src="docs/demo.zh.gif" alt="在飞书群里先发三张图、再补几句说明、夹一句无关的「中午吃饭」，最后才 @ Hermes Tag——它在对话内回复，综合三张图的原图、你的说明和相关讨论，按编号给出关键结论，无关的那句不进结论。" width="760"></p>

<p align="center"><sub>真实录屏 · <a href="docs/demo.zh.mp4">高清 MP4</a></sub></p>

## 这是什么

Hermes Tag 是 Hermes 的一个 Claude-Tag 式**上下文选择层**，面向飞书 / Lark（以及 Slack）。它**覆盖** Hermes 内置的飞书平台，而不是新增一个平台。每个启用的群拥有一个共享的智能体身份，它只在被 @ 时回复。

它在 Hermes 内置频道之上独有地补足的能力：

1. **迟到的 @，完整的上下文。** 你可以在 @ 它之前就把上下文铺散开——图片、一段说明、别人的回复——等你终于 @ 它，它会跨时间、跨图文重建出恰当的有界证据：那几张图的原图、你的说明、相关的讨论。不是只看触发那一句，也不是整段聊天记录。
2. **记忆按群隔离，by design。** 长期记忆只来自 @ 互动，并且只停留在那个群——一个群的记忆不会泄露到另一个群，也不会变成你的全部账号历史。没有跨频道的“workspace 记忆”；这种隔离就是隐私承诺。
3. **可审计，审计事件已脱敏。** `/tag admin audit` 返回脱敏事件（scope、时间、数量——绝不含消息文本）；`/tag admin clear|disable` 清除某个群保留的数据。`enabled_chats` 白名单是唯一的存储与处理边界。

`ContextSelector` 通过 `focused_reply`、`thread`、`deictic_recent`、`plain` 四种范围选择**有界证据**，而不是把整段聊天记录塞给模型。这意味着没有全量历史 RAG，也不会无人 @ 就自动回复。

**当前已交付 vs. 路线图。** 已交付：有界的多模态证据、Tier-0/Tier-1 记忆、按群隔离、管理员生命周期控制、脱敏审计——在飞书 / Lark 与 Slack 上。钉钉也已支持，但**能力受限**：钉钉机器人在群里只能收到 @ 它的消息（没有飞书 `im:message.group_msg` 的等价权限），因此**群内环境上下文（Tier-0）在钉钉上不可用**——详见 [docs/dingtalk.md](docs/dingtalk.md)。路线图：更深入的连接器 / 来源绑定能力。Claude-Tag 是我们对标与追赶的目标，而不是声称它的每个能力都已经交付。

本仓库、Python / pip 包名与清单名均为 `hermes-tag`。

## 安全与风险提示（使用前必读）

- `enabled_chats` 白名单是存储与处理的边界。
- **Tier-0 会存消息正文。** bot 在启用群里收到的每条消息都会作为 Tier-0 短期上下文存下来，**包括正文**。飞书上只有 `granted_scopes` 包含 `im:message.group_msg` 时才会存；Slack 和钉钉上总是会存。默认每个群最多 500 条（`tier0_max_count`）。超过 24 小时（`tier0_ttl_seconds`）的记录，要等该群下一次有消息被存储时才会被删除，所以安静的群可能保留得更久。
- **Tier-1 会存提问和回复。** 每次 @ 互动都会写入一条 Tier-1 记忆，格式为 `question=<消息正文>; conclusion=<回复正文>`。私聊里的每一轮都算作 @。一个群超过 `tier1_max_count`（默认 100 条）后，较早的记忆会被合并。Tier-1 没有时间上限。
- 两者都存在一个明文 SQLite 文件里（声明的 `encryption_posture` 为 `plaintext-db-on-local-disk`），路径为 `<hermes home>/plugin-data/hermes-tag/<platform>-tag.sqlite3`，配置了 `db_path` 时以它为准。已存消息自带的附件会复制到同级的 `<sqlite 文件名>.media` 目录。被引用消息中的媒体由内置 adapter 下载到 Hermes 的媒体缓存，每次下载都生成一个新文件。插件会删除所有这些文件：用完当轮即删；如果作为 Tier-0 上下文保留，就在 clear 或过期清理时删除。
- 在飞书上，插件会用 bot 凭据自行调用以下飞书开放平台 API：
  - `application.v6.scope.list`：每个进程一次，核对应用是否真的拥有 `granted_scopes` 声称的 `im:message.group_msg`；
  - `im.v1.message.get` 和消息资源下载：用于读取被引用的消息；
  - 上述核对发现权限不匹配或可升级时，私信每位配置的管理员。

  在 Slack 和钉钉上，插件自身不调用任何 API。
- 管理员执行 `/tag standing confirm` 会创建一个 Hermes cron 任务。该任务按计划运行并发到群里，直到被取消或暂停。
- `/tag admin clear` 和 `/tag admin disable` 会删除该群的 Tier-0、Tier-1 和媒体，并取消该群定时任务对应的 cron 任务。它们不会重置 Hermes 会话；要重置请发送 `/new`。
- 审计事件（`/tag admin audit`）记录启动、存储、管理、定时任务和生命周期等操作，只含 id、计数和固定文本，绝不含消息正文。clear 之后审计事件仍会保留。旧版本写入的、带上下文预览的记录，会在打开存储时被清理掉。

启用试点群之前，请阅读 [SECURITY.md](SECURITY.md) 与 [docs/design/](docs/design/)。

## 环境要求 / 兼容性

| 项 | 要求 |
| --- | --- |
| hermes-agent | `>=0.22.5` (tested: `v0.22.5`) |
| lark-oapi | `1.6.8` |
| Python | `3.14` |
| 必需环境变量 | `FEISHU_APP_ID` + `FEISHU_APP_SECRET` |

Hermes 会检查 manifest 中的 `requires_hermes: ">=0.22.5"` 要求。

## 快速开始（<60 秒）

> **让 AI agent 来安装？** 把它指向 [llms.txt](llms.txt) 和 [AGENTS.md](AGENTS.md)——那些是为 agent 驱动的安装 / 配置写的。本 README 面向人类。

```bash
hermes plugins install DanielLi202/hermes-tag
```

```yaml
plugins:
  enabled:
    - hermes-tag
platforms:
  feishu:
    require_mention: false   # 让未被 @ 的群消息也能进入适配器，用于 Tier-0 上下文
    extra:
      feishu_tag:
        enabled: true
        enabled_chats: [oc_xxx_pilot_chat]
        bot_open_id: ou_xxx_bot_open_id
        granted_scopes: [im:message.group_msg]
        admins: [ou_xxx_admin_open_id]
        encryption_posture: plaintext-db-on-local-disk
```

`bot_open_id` 和 `admins` 必须使用飞书 open_id（`ou_...`）。本插件不需要 `contact:user.employee_id:readonly`；即使授予该权限，也会把发送者身份规范化为 open_id。

首次使用时，Hermes Tag 会实时核对 `granted_scopes` 与飞书应用实际权限；如果配置声明了 `im:message.group_msg` 但应用未实际持有，会私信已配置的管理员。这样可以直接暴露“未 @ 的群消息从未被投递，导致 Tier-0 群上下文退化为仅 @ 消息”的静默故障。

完整安装与线上验证：见 [after-install.md](after-install.md)。Slack 接入：见 [docs/slack-setup.md](docs/slack-setup.md)。钉钉接入与能力边界：见 [docs/dingtalk.md](docs/dingtalk.md)。遇到疑似故障？先查 [docs/known-limits.md](docs/known-limits.md)（英文）——它把常见症状对应到飞书平台 / hermes 核心的限制，这些不是本插件能修的。

## 使用

在群里，`/tag` 命令需要 @ 机器人。

- `/tag status` →（仅管理员）返回适配器平台、`tier0_full_ingest` / `l2_context` / `tier1_at_memory` 等能力标志，以及当前按群统计的指标。
- `/tag admin count` → 返回保留状态计数，例如 `tier0=... tier1=... standing_jobs=...`。
- `/tag admin clear|disable|audit` → 清除插件数据、停用该群的插件存储，或返回脱敏审计事件。
- `/tag standing add <schedule> <timezone> <description>`，随后 `/tag standing confirm`
- `/tag standing list|cancel <id>|pause <id>|enable <id>`

| 上下文范围 | 含义 |
| --- | --- |
| `focused_reply` | 显式回复 → 收窄到被回复的父消息作为证据。 |
| `thread` | 没有显式回复的真实 thread → 收窄到该 thread 作为证据。 |
| `deictic_recent` | “上面那张图” / “the image above” → 最近的相关媒体。 |
| `plain` | 有界的近期文本。 |

| 记忆层 | 行为 |
| --- | --- |
| `Tier-0` | 每群短期缓冲，按 TTL / 数量淘汰。 |
| `Tier-1` | 长期，来自 @ 互动，会合并，删除时打墓碑。 |

## 项目结构

- `src/hermes_tag/core.py` — 配置、sqlite 存储、TagEngine、PlatformSeam。
- `src/hermes_tag/context.py` — ContextSelector：有界证据选择器。
- `src/hermes_tag/base.py` — TagAdapterMixin：平台无关的编排逻辑。
- `src/hermes_tag/platforms/feishu.py` — 飞书绑定：@ 检测、媒体拉取 / 下载、注册。
- `src/hermes_tag/platforms/slack.py` — Slack 绑定：@ 检测、媒体缓冲、注册。
- `src/hermes_tag/platforms/dingtalk.py` — 钉钉绑定：`is_in_at_list` @ 检测、注册（能力受限——见 [docs/dingtalk.md](docs/dingtalk.md)）。
- `src/hermes_tag/i18n.py` — 多语言字符串。
- `src/hermes_tag/adapter.py` — 向后兼容的再导出垫片。

平台无关的基类加上窄接缝，意味着每个平台只需很少代码；通用策略只写一次、对所有平台生效。

## 贡献 · 更新日志 · 许可

- [贡献指南](CONTRIBUTING.md)
- [更新日志](CHANGELOG.md)
- 许可：MIT，DanielLi202。
