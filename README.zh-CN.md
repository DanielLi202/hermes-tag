# Feishu Tag
飞书 / Lark 群聊的频道级 AI 助手，构建于 Hermes agent 框架之上。在群里 @ 它，它就在对话中回复——只带上这个群自己的记忆和恰当的上下文，而不是你的全部历史。

[English](README.md) · [中文](README.zh-CN.md)

![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg) ![Version: 0.2.0](https://img.shields.io/badge/version-0.2.0-blue.svg) ![hermes-agent: v2026.6.19](https://img.shields.io/badge/hermes--agent-v2026.6.19-blue.svg) ![Python: 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)

<!-- TODO: add docs/demo.gif — sanitized @-mention -> focused_reply clip -->
*演示将展示：群内 @ 机器人、有界证据选择，以及一条在对话中的聚焦回复。*

## 简介

Feishu Tag 是 Hermes 的飞书 / Lark 插件，提供 “claude-tag 式” 的频道级智能体：类似企业微信 / 钉钉里的群内智能助手，也对标 Anthropic 的 Claude Tag（Slack）——但面向飞书 / Lark。它**覆盖** Hermes 内置的飞书平台，而不是新增一个平台。

每个启用的群拥有**一个共享的智能体身份**。它只在被 @ 时回复，长期记忆也**只来自这些 @ 互动**，因此单个群的工作记忆不会变成你的全部账号历史。

`ContextSelector` 通过 `focused_reply`、`deictic_recent`、`plain` 三种范围选择**有界证据**，而不是把整段聊天记录塞给模型。这意味着没有全量历史 RAG，也不会无人 @ 就自动回复；管理员对保留的记忆拥有审计与生命周期控制。

本仓库为 `hermes-plugin-feishu`；Python / pip 包名与清单名为 `hermes-plugin-feishu-tag`。

## 安全与风险提示（使用前必读）

- `enabled_chats` 白名单是存储与处理的边界。
- 启用群里的所有消息都可能作为 Tier-0 短期上下文被本地缓冲。
- 只有 @ 互动才会产生 Tier-1 长期记忆。
- 声明的 `encryption_posture` 为 `plaintext-db-on-local-disk`（本地磁盘明文）。
- 管理员可执行 `/tag admin clear` 或 `/tag admin disable` 清除某个群保留的插件数据。
- 审计事件记录启动、存储、管理、定时任务与生命周期等操作。

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

```bash
hermes plugins install DanielLi202/hermes-plugin-feishu
```

```yaml
plugins:
  enabled:
    - hermes-plugin-feishu-tag
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

完整安装与线上验证：见 [after-install.md](after-install.md)。

## 使用

在群里，`/tag` 命令需要 @ 机器人。

- `/tag status`
- `/tag admin count|clear|disable`
- `/tag standing add <schedule> <timezone> <description>`，随后 `/tag standing confirm`
- `/tag standing list|cancel <id>|pause <id>|enable <id>`

| 上下文范围 | 含义 |
| --- | --- |
| `focused_reply` | 显式回复 → 收窄到被回复的父消息作为证据。 |
| `deictic_recent` | “上面那张图” / “the image above” → 最近的相关媒体。 |
| `plain` | 有界的近期文本。 |

| 记忆层 | 行为 |
| --- | --- |
| `Tier-0` | 每群短期缓冲，按 TTL / 数量淘汰。 |
| `Tier-1` | 长期，来自 @ 互动，会合并，删除时打墓碑。 |

## 项目结构

- `src/hermes_plugin_feishu/core.py` — 配置、sqlite 存储、TagEngine、PlatformSeam。
- `src/hermes_plugin_feishu/context.py` — ContextSelector：有界证据选择器。
- `src/hermes_plugin_feishu/base.py` — TagAdapterMixin：平台无关的编排逻辑。
- `src/hermes_plugin_feishu/platforms/feishu.py` — 飞书绑定：@ 检测、媒体拉取 / 下载、注册。
- `src/hermes_plugin_feishu/i18n.py` — 多语言字符串。
- `src/hermes_plugin_feishu/adapter.py` — 向后兼容的再导出垫片。

平台无关的基类加上窄接缝，意味着接入新平台（已规划 Slack）只需很少代码。

## 贡献 · 更新日志 · 许可

- [贡献指南](CONTRIBUTING.md)
- [更新日志](CHANGELOG.md)
- 许可：MIT，lidongyuan。
