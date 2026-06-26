# Hermes Feishu Tag 插件 — 返修 Spec v3(F4 关联缺陷)

> 源自《返修 Spec v2》F4 + 三次验收(2026-06-25)。交给 **dev agent**。
> 只给 **目标 / 缺陷 / 关键技术决策(约束)/ 验收(=验证)**;**不含实现细节**。MUST=必须。
> 范围:**仅修这一处中危缺陷**,静态可完成。F1/F2/F3/F5/F6 已对真源核验通过,**保持不动**。

## 缺陷(精确)

当前 F4 在出站 `send` 捕获 Tier-1 结论(方向正确),但用**每次 `send` 都 `pending_tier1[chat].pop(0)` 的按群 FIFO 队列**(`adapter.py` `_dispatch_inbound_event` 入队、`send` 覆盖出队),**无法区分**"agent 对某条 @ 的回复"与"bot 自发 send"。后果:

1. `trigger_standing_job` 的 send 在有 @ 待处理时触发 → 弹出该 @ 的 pending,把 **"standing job: …" 误当成该用户 @ 的结论**写入 Tier-1。
2. `enable_chat` 告知 send 同理会消费一个 pending @。
3. 多段回复 / 并发乱序回复 → FIFO 与真实回复顺序不一致,**结论张冠李戴**。
4. 某条 @ 没有回复(agent 不响应)→ 其 pending 残留,被**后续任意无关 send** 弹出误写。

现有测试只覆盖"单 @ → 单 send 顺序",测不到以上任何一种。

## 目标

Tier-1 的"结论"必须关联到**正确的触发 @**;**bot 自发 send 不得消费/污染**任何 pending @ 关联;无回复的 @ 不被无关 send 误写。保留 F4 内核(在出站点捕获结论,而非 dispatch 返回值)。

## 关键技术决策(约束)

- **按相关性键关联,而非按群 FIFO**:把待写 Tier-1 的 (event, enhanced) 以**稳定关联键**索引——优先复用已有的 `task_session_id`(或 Hermes 会话键 / 出站 `reply_to` 上下文),使一次回复 send 能定位到**它自己的**那条 @,而不是"该群最早的 pending"。
- **排除 bot 自发 send**:`enable_chat` 告知、`trigger_standing_job` 触发、以及任何**非 agent-回复**的 send,**不得**触发 Tier-1 捕获(例如标记 bot 发起的 send,或仅对"能匹配到 pending @"的回复 send 捕获)。
- **多段回复**:同一 @ 的多次回复 send 只写一条 Tier-1(首条结论或累积,任选其一但须确定),不串到其他 @。
- **无回复的 @**:pending 条目须有**作用域/过期**,不得被其他 @ 的回复或 bot 自发 send 弹出误写(按键回收,不做全局 FIFO 弹出)。
- **并发安全**:pending 关联结构的读写在锁内(与既有 store.lock 一致),避免并发 @/回复竞态。
- 不回退 F1/F2/F3/F5/F6 与 R2;不改 dispatch/send 之外的逻辑。

## 验收(MUST)

- **V1(保留)**:dispatch 本身不写 Tier-1;对应 @ 的回复 send 写入,结论=该回复内容。
- **V2(新,核心)**:某 @ 处于 pending 时触发 `trigger_standing_job` 的 send → **不写、不改**该 @ 的 Tier-1;该 @ 之后的真实回复仍写入**正确**结论。
- **V3(新)**:`enable_chat` 告知 send **不消费**任何 pending @。
- **V4(新,乱序)**:两条 @(@1、@2)各自的回复以**相反顺序**到达 → Tier-1 中 @1↔@1 回复、@2↔@2 回复,**不串**(证明按键关联而非 FIFO)。
- **V5(新)**:某 @ 无回复时,后续无关 send **不**把其内容误写为该 @ 的结论。
- **V6(效力)**:把实现临时换回"按群 FIFO 弹出"写法时,V2/V4/V5 必须**失败**(证明这些测试真能抓到缺陷)。
- **V7(回归)**:provenance、consolidation、delete-linkage、budget 等既有 Tier-1 MUST 全过;36 测试不回退。

## 不在范围内

- R4 活体 smoke(真实 Hermes/飞书/scope,外部前提,仍待)。
- 其他 F 项与 R2(已验收通过)。

## 重新验收门槛(我据此复验)

V1–V7 全过,且按真源核验的 F1/F2/F3/F5/F6 不回退。通过后即"静态返修全部完成",仅余 R4 活体收口。
