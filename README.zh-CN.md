# Hermes Tag

**先发图、再说话、最后才 @——该看的它都在。**

用 Hermes 把 Claude-Tag 式能力带到飞书 / Lark（以及 Slack）。你先发几张图、补一段说明，别人插几句讨论——等你终于 @ 它，它取回的是**那几张图的原图 + 你的说明 + 相关的讨论**，而不是只看你最后那一句，也不是把整个群史倒给它。平时一句不答，只在被 @ 时，精准取回“该看的那几条”。

[English](README.md) · [中文](README.zh-CN.md)

![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg) ![Version: 0.2.0](https://img.shields.io/badge/version-0.2.0-blue.svg) ![hermes-agent: v2026.6.19](https://img.shields.io/badge/hermes--agent-v2026.6.19-blue.svg) ![Python: 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)

<p align="center"><img src="docs/demo.zh.gif" alt="在飞书群里先发三张图、再补几句说明、夹一句无关的「中午吃饭」，最后才 @ Hermes Tag——它在对话内回复，综合三张图的原图、你的说明和相关讨论，按编号给出关键结论，无关的那句不进结论。" width="760"></p>

<p align="center"><sub>真实录屏 · <a href="docs/demo.zh.mp4">高清 MP4</a></sub></p>

## 这是什么

Hermes Tag 是 Hermes 的一个 Claude-Tag 式**上下文选择层**，面向飞书 / Lark（以及 Slack）。它**覆盖** Hermes 内置的飞书平台，而不是新增一个平台。每个启用的群拥有一个共享的智能体身份，它只在被 @ 时回复。

它在 Hermes 内置频道之上独有地补足的能力：

1. **迟到的 @，完整的上下文。** 你可以在 @ 它之前就把上下文铺散开——图片、一段说明、别人的回复——等你终于 @ 它，它会跨时间、跨图文重建出恰当的有界证据：那几张图的原图、你的说明、相关的讨论。不是只看触发那一句，也不是整段聊天记录。
2. **记忆按群隔离，by design。** 长期记忆只来自 @ 互动，并且只停留在那个群——一个群的记忆不会泄露到另一个群，也不会变成你的全部账号历史。没有跨频道的“workspace 记忆”；这种隔离就是隐私承诺。
3. **可审计，且从不存你的消息正文。** `/tag admin audit` 返回脱敏事件（scope、时间、数量——绝不含消息文本）；`/tag admin clear|disable` 清除某个群保留的数据。`enabled_chats` 白名单是唯一的存储与处理边界。

`ContextSelector` 通过 `focused_reply`、`thread`、`deictic_recent`、`plain` 四种范围选择**有界证据**，而不是把整段聊天记录塞给模型。这意味着没有全量历史 RAG，也不会无人 @ 就自动回复。

**当前已交付 vs. 路线图。** 已交付：有界的多模态证据、Tier-0/Tier-1 记忆、按群隔离、管理员生命周期控制、脱敏审计——在飞书 / Lark 与 Slack 上。钉钉也已支持，但**能力受限**：钉钉机器人在群里只能收到 @ 它的消息（没有飞书 `im:message.group_msg` 的等价权限），因此**群内环境上下文（Tier-0）在钉钉上不可用**——详见 [docs/dingtalk.md](docs/dingtalk.md)。路线图：更深入的连接器 / 来源绑定能力。Claude-Tag 是我们对标与追赶的目标，而不是声称它的每个能力都已经交付。

本仓库、Python / pip 包名与清单名均为 `hermes-tag`。

## 安全与风险提示（使用前必读）

- `enabled_chats` 白名单是存储与处理的边界。
- 启用群里的所有消息都可能作为 Tier-0 短期上下文被本地缓冲。
- 只有 @ 互动才会产生 Tier-1 长期记忆。
- 声明的 `encryption_posture` 为 `plaintext-db-on-local-disk`（本地磁盘明文）。
- 管理员可执行 `/tag admin clear` 或 `/tag admin disable` 清除某个群保留的插件数据，并用 `/tag admin audit` 查看脱敏的活动记录。
- 审计事件记录启动、存储、管理、定时任务与生命周期等操作——绝不记录消息正文。

启用试点群之前，请阅读 [SECURITY.md](SECURITY.md) 与 [docs/design/](docs/design/)。

## 环境要求 / 兼容性

| 项 | 要求 |
| --- | --- |
| hermes-agent | `v2026.6.19` |
| lark-oapi | `1.6.9` |
| Python | `>=3.11` |
| 必需环境变量 | `FEISHU_APP_ID` + `FEISHU_APP_SECRET` |

这些版本固定是项目约定；Hermes 没有强制的兼容性机制。

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

完整安装与线上验证：见 [after-install.md](after-install.md)。Slack 接入：见 [docs/slack-setup.md](docs/slack-setup.md)。钉钉接入与能力边界：见 [docs/dingtalk.md](docs/dingtalk.md)。

## 使用

在群里，`/tag` 命令需要 @ 机器人。

- `/tag status`
- `/tag admin count|clear|disable|audit`
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
