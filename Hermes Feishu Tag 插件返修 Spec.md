# Hermes Feishu Tag 插件 — 返修 Spec

> 源自《实现 Spec》+《验收报告(2026-06-25)》。交给 **dev agent** 的返修契约。
> 只给 **目标 / 关键技术决策(约束)/ 验收(=验证)/ 交给 dev 决定**;**不含实现细节**。MUST=必须。
> **背景(自包含):** 当前实现让 31 个逻辑测试在**虚构的 Hermes/飞书 fake** 上通过;验收认定**逻辑层 PASS、集成层未验收**,且有 6 处缺陷。集成层是对一套**不存在的接口**编码(`register_plugin(registry,...)`、`registry.register`、虚构的 `handle_message/download_image/fetch_message/register_cron`),与设计定的"继承 `FeishuAdapter` + `ctx.register_platform` + 真实 `im.v1` 端点"不一致。本 Spec 定义返修。
> **核心判断:** 允许拉真实源码能消除"对幻觉编码"的根因(解决 HIGH 与缺陷 1/7、把"对 fake"升级为"对真接口"),但**源码 ≠ 运行系统**——集成层 MUST 仍需一次活环境 smoke;纯逻辑缺陷与源码无关,照修。

---

## R0 — 源码接入与约束(前提)

**目标:** 用真实开源源码消除"对虚构接口编码"。

**关键技术决策(约束):**
- 拉 `NousResearch/hermes-agent`,**钉一个明确 tag/release**(不是 main),记录于 `plugin.yaml` 与 README;`larksuite/oapi-sdk-python`(lark-oapi)钉版本。`larksuite/openclaw-lark`、`alwayset/agent-tag` **仅作 pattern 参考,不整体照搬**。
- **只依赖公开 plugin/adapter 契约**:`register(ctx)` / `ctx.register_platform(...)`、基类公开 seam、公开的资源下载/cache helper、`MessageEvent`。**禁止硬耦合下划线内部方法**(`_on_message_event` 等);若确无公开替代而必须用,则该方法须纳入启动签名自检(R1)且 `plugin.yaml` pin 版本。
- **不 vendoring** 整份 Hermes/飞书源码进插件;以依赖 + 版本 pin 引用。

**验收(MUST):**
- R0.1 `plugin.yaml` 的 `hermes_version` = 真实钉定的 Hermes 版本(替掉占位 `0.1.0`),并记录所拉 tag。
- R0.2 代码评审确认:无对内部私有方法的硬依赖,或全部已列入启动自检清单。

**交给 dev:** 依赖/拉取方式;subclass vs compose 的最终取舍(见 R1)。

---

## R1 — 集成 seam 对齐(消除 HIGH / 缺陷 1)

**目标:** 注册、入站、飞书媒体、cron 全部对齐真实 Hermes/飞书契约,替掉虚构接口。

**关键技术决策(约束):**
- **注册:** 经真实 `ctx.register_platform(name="feishu", adapter_factory=...)` 覆盖(last-writer-wins),替掉 `register_plugin(registry,...)` + `registry.register`。
- **adapter 形态:** 按设计**继承真实 `FeishuAdapter`**;若读真实源码后确有更稳妥的公开组合方式,可组合,但**二者都必须复用内置 normalize/资源下载,不重写 image_key/file_key 处理**,且方法名/签名对齐真实基类(替掉虚构的 `download_image/fetch_message/...`)。
- **入站:** 挂到真实入站路径,使 adapter 能接到该群**每条消息(含未@)**;未@只摄取、@ 才增强分发——边界不变(未@不触发回复/不进会话/不进模型,除非作 L2 被本次@拉取)。
- **飞书媒体:** 用 lark-oapi 真实 `im.v1.message.get`(取 `parent_id`/`root_id`)+ `message_resource.get(type=image|file)` 与 `images/:image_key` 两条路径;复用基类 cache helper。`im:message` 即可(无独立 `im:resource`)。
- **cron:** standing work 映射到**真实 Hermes cron API**(替掉假 `register_cron`),scoped `chat_id`。
- **自检:** 启动对**真实依赖到的所有 seam** 做签名自检(不只 `handle_message`/`send`,要含媒体/cron 路径所依赖者),不符**响亮失败**,不静默降级。

**验收(MUST):**
- R1.1 注册经 `ctx.register_platform(name="feishu")`,在真实 Hermes 中覆盖内置 adapter(smoke,R4)。
- R1.2 媒体下载走真实 lark-oapi 端点(代码审 + smoke)。
- R1.3 自检覆盖所有真实依赖 seam;构造签名漂移 → 启动失败(测试断言)。
- R1.4 入站能收到未@消息(smoke,受 R5 scope 约束)。

**交给 dev:** subclass vs compose 终选、具体 SDK 调用、入站挂载点、cron 注册细节。

---

## R2 — 逻辑缺陷修复(与源码无关,照修)

每条修复须留可运行验证。

- **R2.1 缺陷2(降级模式媒体泄漏):** 无 `group_msg` 时,引用媒体**要么不落盘,要么有独立于 Tier-0 行的生命周期清理**。验收:无 `group_msg` 下@带引用图,处理后媒体缓存被清理,**无孤儿文件**。
- **R2.2 缺陷4(特权命令默认开放):** `_is_admin` 改为 **fail-closed**——未配置 `admins` 时,破坏性命令(`/admin clear`、`/admin disable`、standing 建/取消)默认**拒绝**(或要求显式开关)。验收:默认配置下非授权 `/admin clear|disable` 被拒。
- **R2.3 缺陷5(全局锁横跨模型调用):** 锁的临界区**不得包住 `base.handle_message`(模型/agent 调用)**;锁只护存储读写。验收:构造慢 `base.handle_message`,断言一个@的模型调用**不在锁内**、不阻塞另一个@的存储操作(代码审 + 计时)。*ponytail:单群低并发本可接受,但锁住模型调用是真问题,改。*
- **R2.4 缺陷6(重复 `disable_chat`):** 删除死定义,保留含 cron 注销的版本。验收:仅一个定义;disable 级联清 DB/媒体/cron 的测试仍过。
- **R2.5 缺陷3(`next_weekly_fire` 脱节):** 要么接入真实 cron 调度路径(用真实 cron API,R1),要么删掉这个测试专用 helper;`schedule` 字符串格式在**创建/存储/调度三处统一**。验收:standing job 的 schedule 经真实 cron 按其时区/DST 触发(smoke,R4),**无脱节 helper 充数**。

---

## R3 — 接口忠实的测试(升级 fake,不回退)

**目标:** 把"虚构 fake"升级为"由真实签名派生的忠实桩/契约测试",且现有逻辑测试继续通过。

**关键技术决策(约束):**
- fake/桩按**真实 Hermes/飞书签名**派生(方法名、参数、返回类型一致),使逻辑测试对真实契约成立。
- 现有 **31 个逻辑 MUST 测试不得回退**。

**验收(MUST):** R3.1 全套测试通过;R3.2 桩签名与真实基类/SDK 对齐(代码审)。

---

## R4 — 活环境 smoke(集成层验收硬门槛)

**目标:** 至少一条真实端到端 smoke,证明"真能在 Hermes 里跑"。源码替代不了这步。

**关键技术决策(约束):** 真实 Hermes 实例 + 真实飞书测试 app/bot(试点群)。

**验收(MUST)——三点,留可复核证据(日志/截图/记录):**
- R4.1 插件以 `name=feishu` 覆盖内置 adapter,真实生效。
- R4.2 一条**带引用图片的 @** 往返:图片进 `media_urls`、走原生 vision。
- R4.3 一个 standing cron 按其时区**按时触发**回贴该群(受 R5 约束)。

**交给 dev:** smoke 脚手架、测试 app 配置。

---

## R5 — 组织前提(代码解决不了,须记录状态)

- 敏感 scope `im:message.group_msg` 的管理员/安审审批走**组织流程**。未获批 → Tier-0/L2 降级到 L1(A0.4 已设)。
- smoke 在降级模式下至少跑 R4.1 + R4.2;R4.3 与未@摄取(R1.4)待 scope 获批后补。
- 这不是 dev 的代码任务,但**必须在验收记录里写明 scope 审批状态**。

---

## 重新验收门槛(我据此复验)

1. **R0/R1** seam 全用真实契约(注册/入站/媒体/cron);版本 pin 真实;无内部硬耦合。
2. **R2** 缺陷 2/3/4/5/6 全部修复,各有验证。
3. **R3** 测试忠实,31 个逻辑 MUST 不回退。
4. **R4** 至少一条活环境 smoke,三点通过(R4.3 受 R5 约束,须注明)。
5. 逻辑层已通过的 MUST 维持通过。

> 不达上述任一项即不通过。R5 scope 未获批可有条件验收(降级模式),但须显式标注未覆盖项(R4.3、R1.4 实时未@摄取)。
