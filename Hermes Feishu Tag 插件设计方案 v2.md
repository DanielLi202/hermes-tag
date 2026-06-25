# Hermes Feishu Tag 插件 — 设计方案 v2.2

> v2.2 = v2.1 + 需求方对"长期记忆"边界的最终裁决(2026-06-25)。范围与决策已全部锁定。
> v2.1 = v2 + Codex 评审驱动的修订。本文是**设计方案**,不含实现细节(无代码、无方法签名)。
> 取代初版《Hermes Feishu Tag 插件设计文档.md》中与本版冲突的部分。

### v2.2 变更摘要(D8 裁决:长期记忆仅来自 @ 交互)
- **D8 已定**:长期记忆**只从 @ 交互写入**(被问什么 / 感知的上下文 / agent 结论),**不对全量消息流做后台蒸馏**。
- **Tier-0 与 Tier-1 解耦**:Tier-0(全量推送缓冲)**只服务 L2**,按时间/条数**自由消退,不再需要蒸馏 watermark**;Tier-1(长期记忆)独立地从 @ 交互累积,带 provenance。
- **Blocker 1 闭合**:无后台模型蒸馏;未@消息只在某次**真实 @ 被当作 L2 拉取**时才进模型。隐私表述据此更新(§9)。
- **Blocker 2 仍适用**:L2 取"维持全量推送+消退",敏感权限保留 → D7(专用试点 bot + 入口硬丢弃)维持。

### v2.1 变更摘要(评审驱动,仍生效)
- **接收边界 ≠ 存储边界**:敏感权限下 app 收到所在每个群的消息;用专用试点 bot + 入口硬丢弃来真正限定范围(§2 D7、§9)。
- **Tier-1 保留 provenance**(来源/归属/状态/删除联动)(§5、§10)。
- **执行边界 = 任务级 session + 注入群记忆**,不共享 live session(§7)。
- **L2 背景择优**(thread/引用链/时间/作者),非照单全收(§6)。
- **standing work = 显式命令 + 确认 + 稳定 ID + 时区**;定时外发是唯一授权的非@开口(§8)。
- **媒体生命周期显式化**;**隐私生命周期补全**(consent/audit/加密姿态/禁用即删)(§9、§10)。
- **设计门禁**补全(权限自检、启停归属、事件幂等、可观测、验收标准)(§15)。

---

## 0. 现状与动机

需求方已有一个 Hermes agent 通过飞书渠道在群里运行,**@ 触发响应已正常工作**。实际痛点:

- 被 @ 时只看到当前一句,拿不到**被引用/回复消息**里的图片、文件;
- 看不到 @ 之前连发的**未 @ 背景消息**;
- 对所在群没有**独立的长期记忆**(Hermes 现有记忆是 profile/session 级)。

本方案增强 Feishu adapter,在 agent 被触发时补齐上下文,并给该群一份独立长期记忆。

---

## 1. 目标(锁定范围)

**做:** ① 分层上下文(当前 → 引用消息图片/文件 → @前未@背景);② 群级长期持久记忆(按 chat_id);③ standing work(口头交代→cron,可列出/取消);④ 单群共享 agent + 跨人续接;⑤ 单群试点起步。

**非目标:** 飞书文档/wiki/base 检索 grounding;主动/ambient 自发插话(**唯一例外见 §8 定时外发**);跨群/跨数据源学习;不 fork、不改 core、不等 upstream。

---

## 2. 关键决策(已定)

| # | 决策点 | 选择 | 依据 |
|---|---|---|---|
| D1 | 消息摄取 | **全量推送订阅**(`im:message.group_msg`),非历史回扫 | @已正常,长期记忆需持续摄入,与 L2 合流 |
| D2 | 存储增长 | **两级存储 + TTL 硬删消退** | 全量摄取必须消退防膨胀 |
| D3 | 记忆/上下文边界 | **群级(chat_id)**,非按用户 | 跨人续接 |
| D4 | 落地范围 | **单群试点** | 风险面最小 |
| D5 | 集成形态 | 继承 `FeishuAdapter`,以 `name=feishu` 重注册覆盖 | registry last-writer-wins |
| D6 | 媒体/检索依赖 | 复用 Hermes 内置资源下载;不引入 lark-cli/MCP | 本版不做 docs 检索 |
| **D7** | **接收 vs 存储边界** | **专用试点 bot/app,仅安装于试点群;入口对非 `enabled_chats` 群硬丢弃** | `group_msg` 让 app 收到所在每个群消息,`enabled_chats` 只是存储/处理过滤,不是接收边界 |
| **D8** | **长期记忆的来源** | **只从 @ 交互写入**(被问什么/感知的上下文/agent 结论);**不对全量消息流做后台蒸馏** | 需求方裁决;未@消息不需进长期记忆,避免后台模型处理全量消息,Blocker 1 闭合 |
| **D9** | **L2 背景来源** | **维持全量推送(`group_msg`)+ 短期缓冲 + 自由消退**;@时读缓冲 | 需求方裁决;背景最实时可靠,接受敏感权限成本(配 D7) |

> D8 的连带效应:Tier-0(全量推送缓冲)与 Tier-1(长期记忆)**解耦**。Tier-0 仅服务 L2,可按时间/条数自由消退(无 watermark);Tier-1 独立从 @ 交互累积。

---

## 3. 架构总览

```
飞书事件
  ↓
FeishuTagAdapter(继承 FeishuAdapter,覆盖入站)
  ├─ 入口 admission:非 enabled_chats 群 → 硬丢弃(不落库、不处理)  [D7]
  ├─ 本群每条消息(含未@) → Tier-0 raw journal(全量推送缓冲,仅服务 L2,自由消退)
  └─ 当消息 @ 了 bot:
        当前消息(文本+附件)
        + L1 解析引用消息媒体(parent_id/root_id → 拉父消息 → 下载图片/文件)
        + L2 择优近期未@背景(读 Tier-0;thread/引用链/时间/作者择优,非照单全收)
        + 注入 Tier-1 长期记忆
        ── 预算内合并 ──→ 增强 MessageEvent(text + media_urls/types)
        ──→ Hermes runner(任务级 session + 注入群记忆,非共享 live session)  [§7]
        ── 处理完成后 → 把本次 @ 交互产物写入 Tier-1(带 provenance)  [D8]

Standing work:@ 显式命令 + 确认 → 注册 Hermes cron(scoped chat_id,稳定 ID);@ 列出/取消
            (cron 回贴群 = 唯一授权的非@外发,见 §8)
```

边界原则:未 @ 消息**不触发面向群的回复、不进 Hermes 会话、不进长期记忆、不被后台模型处理**;它们仅落入 Tier-0 缓冲,**只有在某次真实 @ 被当作 L2 拉取时才进模型**(D8)。

---

## 4. 模块职责(概念级)

- **adapter**(继承 `FeishuAdapter`):入口 admission(D7 硬丢弃)→ 未@写 Tier-0 / @构建增强上下文 + @处理后写 Tier-1。复用内置资源下载。
- **context store**:按群 SQLite。三类数据:Tier-0 缓冲、Tier-1 长期记忆、standing-work registry。负责 TTL 消退、清理、禁用即删。
- **context builder**:当前/引用媒体/择优背景/长期记忆按优先级在预算内拼装。
- **interaction-memory writer**:每次 @ 处理后,把本次交互产物(被问/感知上下文/结论)写入 Tier-1,带 provenance。**非**对全量流的后台蒸馏。
- **standing-work manager**:显式命令→cron 映射;确认、列出、按 ID 取消。

---

## 5. 两级存储(已解耦)+ 消退(需求点②核心)

Tier-0 与 Tier-1 **互不依赖**:Tier-0 是 L2 的临时缓冲,Tier-1 是 @ 交互的长期记忆。Tier-0 消退不影响 Tier-1。

- **Tier-0 raw journal(全量推送缓冲,仅服务 L2)**:每条群消息原文。短保留窗口(默认量级 ~72h 或 N 条)。
  - **自由消退**:按 age/count 物理删除即可,**不需要蒸馏 watermark**(记忆不再从它产生,删早了也不丢记忆)。磁盘上界 ≈ 群消息速率 × 窗口。
- **Tier-1 长期记忆(只从 @ 交互写入)**:每次 @ 处理后写入一条紧凑记忆(本次问题、感知的上下文要点、agent 结论/决策/owner)。长保留、体量天然小(只随 @ 频次增长,不随群消息量增长)。**保留 provenance**:触发的 @ message_id / 时间、提问者归属、状态(未决/已决)、与原始的删除联动键。
- **consolidation**:Tier-1 设上限,旧记忆按时间衰减/合并,合并保留可追溯来源/归属。

消退是**物理删除任务**(挂 cron 或随写触发),磁盘真正回收。

---

## 6. 上下文构建与预算

- **分层 + 总预算**(`max_context_chars`)。优先级:当前 > 引用媒体 > 择优背景 > 长期记忆;不足时从低优先级裁剪。
- **L1 引用媒体**:事件取 `parent_id`/`root_id`(无 `upper_message_id`)→ 拉父消息 → 解析 `image_key`/`file_key` → 下载。两条路径:独立图片走 `images/:image_key`,富文本内嵌/文件走 `messages/:id/resources/:file_key?type=image|file`。字节并入 `media_urls/media_types`。上限:条数、单条字节。下载失败 → 文本占位降级,不中断。无独立 `im:resource` scope。
- **L2 择优背景**:不再"上次回复以来全部消息"照单全收(否则 Bob 的无关消息成了 Alice 的上下文;一次他人@+回复会截断 Alice 的铺垫)。改为按 **thread/引用链、时间邻近、显式指代("那个截图")、作者标注** 排序择优;保持群级连续性但只取相关者,且带作者标签入上下文。

---

## 7. 跨人续接与会话归属(评审修订)

- **共享的是"群记忆",不是"live session"。** 执行用 **per-thread / 按请求(任务)级 session**,每次把群记忆 + 择优背景注入。
  - 原因:群级共享 live session 下,不同用户的并发@会互相污染活动任务状态、并发跑竞态、一个人的指令改到另一人正在进行的任务。
- 仅当确认 Hermes 能保证群级 session 的并发安全与归属时,才考虑真正的群级 session。**默认走"群记忆 + 任务级 session"**。

---

## 8. Standing work(需求点③,评审修订)

- **创建需显式 + 确认**:仅显式命令(非任意闲聊)才进入创建;创建前 bot **回确认**("将设定:每周五10:00 总结本群,确认?"),避免"每周五总结会不会太晚"被误建。
- **稳定 job ID**:每个任务有稳定 ID;列出时展示 ID;**取消按 ID 或确认过的精确匹配**,避免"取消每周五总结"误删他人/相似任务。
- registry 映射:`(chat_id, 描述, schedule, cron_job_id, owner, 状态, created_at)`。
- **权限**:定义谁可创建/取消(owner/admin)。
- **时区**:显式定义来源与展示时区,处理 DST。
- **定时外发 = 唯一授权的非@开口**:cron 触发后回贴群属"非@外发",与"无 ambient"非目标的边界处理是——把它定义为**用户显式授权的定时外发模式**,有可见 registry、可暂停/禁用、可审计;不是 bot 自发插话。

---

## 9. 权限与隐私(评审补全)

- **敏感权限 `im:message.group_msg` = 硬前提**(管理员/安审审批,不可自助,非必过)。
- **接收 vs 存储边界(D7)**:该权限下 app 会**接收所在每个群**的消息。真正限定范围靠:**专用试点 bot/app 仅安装于试点群** + **入口对非 `enabled_chats` 群硬丢弃**(收到即弃,不落库/不处理)。文中明确 `enabled_chats` 是存储/处理边界,不是接收边界。
- **模型处理边界(D8)**:**无后台模型蒸馏**。未@消息只落入 Tier-0 本地缓冲;**仅在某次真实 @ 把它们当作 L2 背景拉取时才进模型**。诚实表述:"未@消息本地接收并短期缓冲,不触发回复、不进长期记忆;仅当后续有人 @ 且需要背景时,相关近期消息会随该次请求送入模型。"长期记忆只含 @ 交互产物,不含未被引用的群消息。
- **隐私生命周期(补全)**:
  - **启用告知/consent**:bot 入群或启用增强时,向群一次性告知"本群消息将被记录并短期缓冲,被 @ 时相关消息可能作为背景送入模型;长期记忆仅来自与机器人的 @ 交互,不含未被引用的群消息"。
  - **保留表**:Tier-0/Tier-1/媒体/cron 各自的保留期与删除规则成表。
  - **审计事件**:启用/关闭/清空/创建取消任务/导出 等留审计日志。
  - **加密姿态**:声明 DB 是否加密(SQLCipher 或置于加密卷);默认文件权限 0600。
  - **禁用即删**:对某群关闭增强时,定义是否级联删除 Tier-0/Tier-1/媒体缓存/该群 cron 任务。
  - **媒体删除**:下载的媒体随 Tier-0 TTL 一并清理,不游离于窗口外。
  - **管理控制**:清空/计数/关闭命令限 owner/admin。
  - **未交互成员**:明确从未与 bot 交互的成员消息也会被记录,纳入告知。
- token:沿用现有飞书应用凭据,tenant 身份即可(本版无 docs/wiki 检索,无需 user OAuth);日志不打印 secret/token/完整敏感正文。

---

## 10. 数据模型(概念级,非建表实现)

- **raw_messages**(Tier-0,全量推送缓冲,短 TTL 自由消退):`chat_id, thread_id, message_id, sender_id, sender_name, text, raw_type, mentions_bot, reply_to_message_id, media_meta, created_at`。(无 `distilled_at`——不再蒸馏。)
- **channel_memory**(Tier-1,**只从 @ 交互写入**,长保留 + consolidation,**带 provenance**):`chat_id, thread_id, content(本次问题/上下文要点/结论), trigger_message_id, asked_by, source_message_ids/time_range, status, confidence, updated_at`。
- **standing_work**:`chat_id, description, schedule, timezone, cron_job_id, owner, status, created_at`。
- **媒体生命周期**:定义媒体是否落盘存储、存多久;`image_key/file_key` 可能在 @ 拉取前过期 → 过期则**降级为文本元数据**,长期"视觉记忆"不做承诺(除非显式存原图,并纳入 TTL 与隐私)。

(字段细节/索引/约束属实现,不在本文展开。)

---

## 11. 与 Hermes 集成的风险

- **子类 override 的入站 seam 不稳定**(`_on_message_event`/`_handle_message_event_data`/`normalize_*` 等内部方法,跨版本易变)。
  - **发布门禁**:`plugin.yaml` **pin 一个 Hermes 版本**;override 最小面;启动**签名自检**,不符则**响亮失败**(不静默停止 enrich);优先用基类公开 seam(`handle_message`/`MessageEvent`)。
- 平台覆盖经 registry 以 `name=feishu` 重注册生效;验证一次注册顺序,成立则不需 `feishu_tag` 双名。
- 复用内置下载/cache helper,不重写。

---

## 12. 配置(概念)

```
feishu_tag:
  enabled: true
  enabled_chats: [ <单个 chat_id> ]     # 存储/处理边界(非接收边界,见 D7)
  resolve_reply_media: true
  max_reply_media_items / max_reply_media_bytes
  raw_retention:        # Tier-0:max_age / max_messages;自由消退(无 watermark)
  channel_memory:       # Tier-1:enabled、每次 @ 写入、max_memory_chars、consolidation、provenance
  standing_work:        # enabled、创建需确认、owner 权限、timezone
  privacy:              # 启用告知、加密姿态、禁用即删、审计
```

(相对初版:移除 `docs_rag`/`proactive`/跨群项;`buffer_authors` 由 same_user 改群级。)

---

## 13. 开放问题 → 评审后裁决

1. **会话归属** → 已定:群记忆共享 + 任务级 session;真正群级 session 需先验证 Hermes 并发安全(§7)。
2. **长期记忆来源(原"蒸馏触发")** → 已定(D8):只从 @ 交互写入,不做全量流后台蒸馏;Tier-0 自由消退,二者解耦(§5)。
3. **默认值** → 保守起步:Tier-0 ~72h/限条数,L2 ~最近 20 条/数小时,Tier-1 每次 @ 一条、紧凑且 source-backed。
4. **敏感权限审批失败的降级** → 已定:**降级到仅 L1/当前消息 + @交互记忆**(L2 不可用);**不**用历史抓取假装 L2。
5. **standing work 误触发** → 已定:显式命令 + 确认 + 稳定 ID(§8)。
6. ~~D8 待拍板~~ → **已裁决**(见 D8/D9):长期记忆仅 @ 交互;L2 维持全量推送+消退。**所有开放问题已闭合。**

---

## 14. 实施路线(粗粒度)

1. **闭环一**:admission 硬丢弃 + Tier-0 全量摄取 + 自由 TTL 消退 + @时 L1 引用媒体 + L2 择优背景。
2. **闭环二**:@交互记忆写入 Tier-1(带 provenance)+ @时注入 + 任务级 session 续接。
3. **闭环三**:standing work(确认 + 稳定 ID + 列出/取消 + 时区 + 定时外发授权)。

每闭环独立可用、独立验证。

---

## 15. 设计门禁 / 验收标准(评审补全,非实现细节)

- **权限自检**:启动时校验实际授予的 scope,缺失则关闭对应能力(无 `group_msg` → 关闭 Tier-0 全量摄取与 L2 背景,降级到仅 L1/当前消息;**@ 交互记忆 Tier-1 不依赖 `group_msg`,仍可用**)。
- **启停归属**:逐群启用/禁用有明确 owner/admin 权限;禁用触发禁用即删。
- **事件幂等/重试**:重复投递的消息事件去重(message_id 唯一),摄取幂等。
- **可观测**:Tier-0 缓存条数、消退删除数、Tier-1 记忆条数/写入失败、降级触发、override 自检结果等计数可查。
- **每闭环验收**:以可观察行为定义(如"引用图片消息被@时,media_urls 含该图并走 vision";"禁用某群后该群 Tier-0/Tier-1/媒体/cron 全部清除")。
