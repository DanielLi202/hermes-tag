# Hermes Feishu Tag 插件 — 返修 Spec v2(活体接线对齐)

> 源自《返修 Spec》+《二次验收(2026-06-25)》。交给 **dev agent**。
> 只给 **目标 / 关键技术决策(约束)/ 验收(=验证)**;**不含实现细节**。MUST=必须。
> **背景(自包含):** 上一轮已把插件**对准真实 Hermes v2026.6.19**(真实类/方法/cron/pin 均正确)并修复 5 个逻辑缺陷——这些**保持**。二次验收按**真源核对**发现:**活体接线在 4 处与真实契约不符**,且 register_platform 入参未核;测试桩在**正是这 4 处**不忠实,导致 35 个绿测测不到真机会炸的地方。本 Spec 修这些。**全部可静态完成,不依赖 scope 审批/活环境**(末尾 smoke 除外)。

## 真实契约事实(已联网核对 `NousResearch/hermes-agent` @ `v2026.6.19`,dev 据此修)

- `send` 真实签名:**`async def send(self, chat_id: str, content: str, reply_to=None, metadata=None) -> SendResult`**(`gateway/platforms/feishu.py:1774`)。
- `_dispatch_inbound_event(self, event: MessageEvent) -> None`(`feishu.py:3179`)是 **突发保护/入队层**:text 事件 `_enqueue_text_event` 后即返回,**返回 None**,模型在别处异步运行。
- `MessageEvent`(`gateway/platforms/base.py:1423`)字段:`text, message_type, source(SessionSource), raw_message, message_id, media_urls, media_types, reply_to_message_id, reply_to_text, channel_context, internal …` —— **无 `mentioned` / `author` / `chat_id` / `reply_media_refs`**。
- 原生 @ 门控:**`require_mention` + `mentions[].open_id`**。
- 媒体下载 seam(**已正确引用,保持**):`_download_feishu_image(*, message_id, image_key) -> tuple[str,str]`(`feishu.py:3706`)、`_download_feishu_message_resource(*, message_id, file_key, resource_type, fallback_filename="")`(`3737`)。

---

## F1 — `send` 对齐真实异步契约

**目标:** 出站真正能发(告知、standing 回贴)。
**关键技术决策(约束):**
- 所有出站走真实 `await self.send(chat_id, content, ...)`(第二参 `content`,**async**)。
- 启动自检对 `send` 期望前缀 **`("chat_id", "content")`**(非 `"text"`)。
- 测试桩 `send` 改为 **async**、签名 `(chat_id, content, reply_to=None, metadata=None)`。
**验收(MUST):**
- F1.1 代码无同步 `self.send(...)` 调用;全部 `await`,第二参为 content。
- F1.2 启动自检:对真实形状 `send` 通过;对 `(chat_id, text)`/同步桩 **fail-closed 报错**(回归保留)。
- F1.3 `enable_chat` / `trigger_standing_job` 测试:await 后桩记录到真实发送。

## F2 — 引用媒体改由父消息解析(删幻觉字段)

**目标:** 引用图片/文件在真机能解析进 `media_urls`。
**关键技术决策(约束):**
- **删除对 `event.reply_media_refs` 的依赖**(真实 `MessageEvent` 无此字段)。
- 由 `reply_to_message_id` **拉取父消息**得到 image_key/file_key(走真实 message-get 路径),再喂 `_download_feishu_image` / `_download_feishu_message_resource`(这两个已是真实 seam,保持)。
**验收(MUST):**
- F2.1 全仓 `grep reply_media_refs` = 0。
- F2.2 测试桩按真实形状提供"由 `reply_to_message_id` → 父消息 → media keys";断言引用图片/文件经真实下载 seam 进 `media_urls`,走原生 vision。
- F2.3 媒体字节上限、失败降级占位、降级模式不留孤儿(既有 R2.1)——仍过。

## F3 — @ 判定复用 Hermes 原生机制(删幻觉字段)

**目标:** 与 Hermes 真实门控一致,不自造。
**关键技术决策(约束):**
- **删除对 `event.mentioned` 的依赖**;复用原生 `require_mention` + `mentions[].open_id` 判定(从真实事件/`source`/`mentions` 推导,不加真实不存在的字段)。
- 不重复实现一套与 Hermes 冲突的 @ 门控。
**验收(MUST):**
- F3.1 全仓 `grep "\.mentioned"` 对 event 的依赖 = 0。
- F3.2 测试桩用真实 mention 信号(`mentions`/`require_mention`)区分 @ 与非@;@ 触发增强分发、非@ 仅 Tier-0。

## F4 — Tier-1 写入改到响应产生之后

**目标:** Tier-1 "结论"是真实模型响应,非 None。
**关键技术决策(约束):**
- **不**用 `_dispatch_inbound_event` 的返回值当结论(真实恒 None,模型异步在别处跑)。
- 改在**响应实际产生后**捕获(post-response / 出站点 / Hermes 响应机制);找不到同步返回则挂到响应/出站事件。
**验收(MUST):**
- F4.1 构造"响应在别处异步产生"的桩,断言 Tier-1 `conclusion` **非空且来自真实响应**;旧的"取 dispatch 返回值"写法在此桩下应**失败**(证明测试有效)。
- F4.2 provenance、consolidation、删除联动(既有 R2/A2.x)仍过。

## F5 — 核实 `register_platform` 入参

**目标:** 注册不传真实 ctx 不支持的 kwargs。
**关键技术决策(约束):** 对照真源 `register_platform` 定义,只传被支持的参数;`required_env`/`install_hint` 若不支持则删/改正。
**验收(MUST):** F5.1 列出真实 `register_platform` 签名出处;F5.2 注册对真实 ctx 形状无"未知 kwarg"。

## F6 — 忠实桩(横切,根因)

**目标:** 让测试桩与真实契约一致,使 F1–F4 的真机错误**能被测出**。
**关键技术决策(约束):**
- 测试桩按**真实** `MessageEvent` 字段集、**async** `send`、`_dispatch_inbound_event` 入队/返回 None 语义构造。
- **禁止**给事件猴补真实不存在的字段(`mentioned` / `reply_media_refs`);所需信号从真实形状(`source`/`mentions`/`reply_to_message_id`)派生。
- 现有 35 个逻辑 MUST **不得回退**,但其断言须经由真实形状达成。
**验收(MUST):**
- F6.1 `grep` 测试:无 `mentioned=` / `reply_media_refs=` 猴补;桩 `send` 为 async、签名含 `content`。
- F6.2 **测试有效性自检**:把忠实桩接上后,F1–F4 中**未修复**的旧写法会让对应测试**失败**(即测试真的能抓到这些发散点)。
- F6.3 全套(≥35)逻辑测试在忠实桩上通过。

---

## 重新验收门槛(round 2,我据此复验)

1. **F1–F5** 修复,各有验证;按真源核对接线一致(send / 引用媒体 / @判定 / dispatch 语义 / register 入参)。
2. **F6** 桩忠实;35 逻辑 MUST 不回退,且 F6.2 测试有效性自检成立。
3. 启动自检:真实签名通过、错误签名 fail-closed。
4. 仍需 **R4 活体 smoke** 最终收口(R5 scope 约束下至少 R4.1 覆盖生效 + R4.2 带引用图@往返);本轮先在忠实桩上预证 1–4 不再发散。

> F1–F6 全部静态可完成(真源在手,无需 scope/活环境)。R4 活体仍是集成层最终硬门槛。
