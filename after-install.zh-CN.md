# Hermes Tag 安装后指南

Hermes 通过克隆仓库安装此插件；**不会**从 \pyproject.toml\ 安装 Python 依赖。

## 安装路径 — 谁做什么

**已经在用 Hermes + 飞书？** 那么只需人工完成一步；其余可由 AI 代理完成。

- **人工（一次性，需审批）：** 在飞书应用的 **权限** 中添加敏感权限 \im:message.group_msg\，并由组织管理员审批。这是安装开发者通常无法自助完成的唯一一步。没有它，@ 驱动的 Tier-1 记忆仍可用，但未提及的背景上下文会静默降级。
- **代理：** 安装插件、写入配置块、重启 gateway 并验证。见 [AGENTS.md](AGENTS.md)。

**还没有 Hermes + 飞书？** 先完成下面的飞书控制台完整设置，再按上面的路径操作。

### 飞书控制台设置（从零开始 — 人工，一次性）

在 [open.feishu.cn](https://open.feishu.cn)（开放平台）完成。控制台标签可能随版本变化；若文案不同，按意图匹配。

1. **创建企业自建应用** — 记录 **App ID** 和 **App Secret** — 在 Hermes 环境中设为 \FEISHU_APP_ID\ / \FEISHU_APP_SECRET\。
2. **应用能力 → 机器人** — 启用 Bot 能力。
3. **权限** — 添加：\im:message\（读消息 + 下载媒体）和 \im:message.group_msg\（**敏感 — 需组织管理员 / 安全审批**；开发者可能无法自助开通）。
4. **事件订阅** — 使用 **长连接 / websocket** 投递，并订阅消息接收事件（\im.message.receive_v1\）。
5. **版本管理与发布** — 创建版本，设置 **可用范围**，并发布（可能需要组织管理员审批）。
6. **将机器人加入各试点群** — 记录群 **chat_id**（\oc_...\）、**bot_open_id**（\ou_...\）以及你的 **admin open_id**（\ou_...\）。

## 必需环境变量

在与 Hermes 相同的环境中设置：

- \FEISHU_APP_ID- \FEISHU_APP_SECRET- \SLACK_BOT_TOKEN\（仅在启用 Slack 时）
- \SLACK_APP_TOKEN\（仅在启用 Slack Socket Mode 时）

\lark-oapi==1.6.9\ 与锁定的 Hermes 飞书环境一致。

## 最小配置

> 代理：优先使用 [AGENTS.md](AGENTS.md) 中带注释的模板 — 每个字段标有 \AGENT-SET\ 与 \HUMAN-PROVIDED\。下方为相同值，不含来源标记。

\\yaml
plugins:
  hermes-tag:
    enabled: true
    # 见 AGENTS.md 完整字段说明
\
## 验证

安装并配置后：

1. 重启 Hermes gateway。
2. 在试点群发送 \/tag status\ — 期望看到 \capability_check=ok\（或文档中的其他状态）。
3. 确认敏感权限已审批；否则后台上下文可能静默降级。

## 故障排查

- **收不到消息：** 检查事件订阅是否为长连接，以及 bot 是否在群内。
- **能力校验 mismatch：** 复核 \im:message.group_msg\ 是否已审批。
- **依赖错误：** Hermes 不会从本仓库安装依赖；使用 Hermes 自带的 Feishu 环境。

## 相关文档

- [AGENTS.md](AGENTS.md) — 代理安装流程
- [docs/known-limits.md](docs/known-limits.md) — 能力与限制
- [docs/known-limits.zh-CN.md](docs/known-limits.zh-CN.md) — 中文版已知限制

---

*本文为 [after-install.md](after-install.md) 的中文翻译。*
