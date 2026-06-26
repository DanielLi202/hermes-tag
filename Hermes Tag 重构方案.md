# hermes-tag 重构方案 v2(core + feishu 首渠道 + 可官方安装)

> 设计方案,交 Codex review。**design-level,不含实现细节**;只给 目标 / 关键技术决策(约束)/ 验收(=验证)/ 迁移步骤 / 开放问题。MUST=必须。
> v2 = v1 + Codex 评审(已对 cloned v2026.6.19 源码核验)驱动的修订,修掉 3 个 blocker + 3 个 high。

### v2 修订摘要(评审驱动)
- **未@摄取更难**:Feishu `_admit()` 在 `require_mention=true` 时**先丢非@消息再建 `MessageEvent`**(feishu.py:2423-2426,4094-4128)→ 未@ Tier-0 摄取要求**平台 `require_mention=false` + 插件自己做 @ 门控**;`pre_gateway_dispatch` hook 在此之前根本收不到未@(run.py:7172+),hook 降为"仅 receive-all 验证后"的未来优化。
- **`register(ctx)` 无 config**:注册期拿不到 `PlatformConfig`,只能**静态注册**已实现渠道;且 gateway **不会**在插件 factory 失败时回退内置(run.py:6915-6935)→ **启用插件不得 brick 现有 Feishu**:factory 在未配置/未启用时须安全降级为内置等价行为。
- **官方安装不 pip-install 依赖**:`hermes plugins install` 只 clone/move 文件、按 manifest **`requires_env`** 提示;**不装 pyproject 依赖**(plugins_cmd.py:448-545)。需**根级 `__init__.py`**;lark-oapi 复用 Hermes 自带 Feishu 依赖(我们覆盖 feishu,故已在环境)。
- **PlatformSeam 扩面**:不止 reply-media,还含 admission、mention 检测+门控、receive-all 能力、**响应关联键(F4)**、出站捕获、**cron 投递能力**。
- **F4 关联键非跨平台**:用 per-channel `response_correlation_key`,不假设 `task_session_id` 全平台存在。
- **第二渠道验收用真实 Hermes 形状 fixture**(经 `handle_message`/`send`/真 `MessageEvent`),非纯 mock。
- **manifest 更正**:`manifest_version` 可选(安装器只拒**高于** max=1,非"最小");`label` 真实可用(非假字段);用 `requires_env`。

---

## 0. 目标与范围
**目标**:① 易扩展第二渠道(脑子写一次,渠道=薄 seam);② 开发完成后 `hermes plugins install <owner/repo>` 装进真实 Hermes 并生效。
**含**:升级 hermes-tag(平台无关 core + feishu 首渠道)、装机补全、借重构修 **F4**。
**不含**:第二渠道完整实现(留扩展点 + 真实形状脚手架证明)、R4 活体 smoke、R5 敏感 scope 审批(外部前提,须记录状态)。

## 1. 已核实的 Hermes 事实(均来自 cloned v2026.6.19)
- **官方安装** = `hermes plugins install <owner/repo|git-url>` → **git clone 进 `~/.hermes/plugins/<name>/`**(plugins_cmd.py);支持 `owner/repo/subdir`(但 subdir 装后无 `.git`,update 受限,plugins_cmd.py:648-652)、`update/remove/list/enable/disable`、装后跑 `after-install.md`、按 manifest `requires_env` 提示环境变量。**不 pip-install 仓库依赖**。
- **目录插件**:`<dir>/plugin.yaml` + **根级 `<dir>/__init__.py` 暴露 `register(ctx)`**(plugins.py:1598-1634)。manifest 只解析选定字段(name/version/description/author/requires_env/provides_tools/provides_hooks/kind/key,plugins.py:237-269);`manifest_version` 可选,安装器拒**高于** max=1;`label` 被内置平台 manifest 使用。`entrypoint` 字段对目录插件无效;pip 路用 entry-point group `hermes_agent.plugins`(另一条次要路)。
- **跨平台入站**:所有平台 → `BasePlatformAdapter.handle_message(MessageEvent)`(base.py:3926);`MessageEvent` 归一化(source.chat_id/user_id/thread_id、media_urls、reply_to_message_id、reply_to_text、channel_context);原生 `require_mention` + `channel_context`。
- **Feishu 入站门控**:`require_mention=true` 时 `_admit()` 先丢非@、再建 `MessageEvent`(feishu.py:2423-2426)→ **未@消息根本不进 `_dispatch_inbound_event`/hook**,除非 `require_mention=false`。
- **`register(ctx)` 无 config**:`register_platform(...)` 不收 `PlatformConfig`,只有 `adapter_factory(config)` 后续拿到 config(plugins.py:770-817);插件覆盖某平台后,factory 失败 gateway **不回退内置**(run.py:6915-6935)。
- **cron 跨进程投递**:新插件平台需 `cron_deliver_env_var` / `standalone_sender_fn` 才能让 standing work 投递(platform_registry.py:138-159,cron/scheduler.py,send_message_tool.py)。
- **`pre_gateway_dispatch`**:在 `MessageEvent` 到 gateway 后、auth 前触发;Feishu 未@(require_mention=true)时**不触发**;Feishu 媒体在 hook 前已归一化。
- 一个 `register(ctx)` 可多次 `register_platform`(覆盖按名 last-writer-wins)。

## 2. 架构:core(脑子,写一次) + seam(触手,每渠道)

### 2.1 复用边界
- **平台无关 core**:Tier-0/Tier-1/standing 存储、记忆(provenance/consolidation/删除联动)、L2 择优 + 预算 + 注入、standing→cron、隐私生命周期、完整 dispatch 流程(含 **F4**)。只吃归一化 `MessageEvent` + `PlatformSeam` + config。
- **平台特定 seam(每渠道)**:见 §2.3,比 v1 想的宽。

### 2.2 包结构(单仓库 / 单已安装插件 / 根级布局)
```
hermes-tag/                  # git repo;装机:hermes plugins install <owner>/hermes-tag
  plugin.yaml                # name / kind: platform / version / description / author / requires_env / 可选 manifest_version:1 / label
  __init__.py                # 根级!def register(ctx): 静态注册已实现渠道(见 §2.5)
  after-install.md           # 敏感 scope 审批、extra.feishu_tag 配置样例、单群 enabled_chats、依赖说明
  core/                      # 平台无关脑子(组合,非 Mixin,避免 MRO 耦合)
    store / memory / builder / standing / privacy / engine(TagEngine) / seam(PlatformSeam) / capabilities
  channels/
    feishu.py                # FeishuTagAdapter(FeishuAdapter) + FeishuSeam(实现 §2.3 全部)
    # 后续 slack.py / dingtalk.py …(只新增,不改 core)
  tests/
  pyproject.toml             # 次要 pip 路 entry-point;声明 hermes-agent(pin v2026.6.19);lark-oapi 复用 Hermes 自带(不靠安装器装)
```
**单仓单插件**是对的(Codex 确认):subdir 每渠道插件会让 core 复用无处安放且 update 语义更弱。clone 整仓后 core 作本地包被各 channel 复用。

### 2.3 PlatformSeam 协议(每渠道实现,扩面版)
- `platform_name`
- **inbound admission / allowed-chat 语义**(各平台 chat 标识/群 DM 区分)。
- **mention 检测 + 自门控**:读该平台原生 mention(feishu `mentions[].id.open_id`)判断是否@bot;**因未@摄取需 `require_mention=false`,门控由插件自己做**(skip ambient)。
- **receive-all 能力位**:能否收未@全量(feishu:敏感 `im:message.group_msg` + 平台 `require_mention=false`);不可得则 L2/Tier-0 降级。
- `async resolve_reply_media(event)`:引用消息媒体解析(feishu:拉父消息 + `_download_feishu_*`)。
- **`response_correlation_key(event, send_args)`**:把出站回复关联回触发 @(F4);各平台不同(base send 传 `reply_to=_reply_anchor_for_event`、metadata 多为 thread_id,**无 task_session_id**)。
- **outbound 捕获点**:在该平台的回复出站处捕获结论(排除 bot 自发 send)。
- **cron 投递能力**:为新插件平台提供 `cron_deliver_env_var`/`standalone_sender_fn`,否则 standing work 不能投递(feishu 为内置平台,复用其投递)。

### 2.4 接入方式:v1 子类 + 组合;hook 为未来
- v1:每渠道 `XxxTagAdapter(XxxAdapter)` + **组合** `TagEngine`(非 Mixin,避免 MRO 耦合),实现 `PlatformSeam`。
- **未@ Tier-0 摄取**必须:平台 `require_mention=false`(否则消息在 `_admit` 被丢)+ `receive-all` 能力 + 插件自门控。摄取发生在入站层(子类的入站处理)。
- **hook 优化(非 v1)**:仅在 receive-all 验证通过后,才考虑把无关脑子搬进 `pre_gateway_dispatch`;且 hook 不处理 Feishu `require_mention=true` 的未@(根本收不到)。列为 §8 开放问题。

### 2.5 注册与"不 brick 内置"(blocker 2 修复)
- `register(ctx)` **静态注册**所有已实现渠道的 platform override(注册期无 config)。
- **factory(config) 做启用/降级**:`extra.<platform>_tag.enabled` 缺失/false 时,factory **必须安全降级为内置等价行为**(透传),**不得抛错**——因为 gateway 不回退内置,抛错会 brick 该平台。仅在显式 opt-in 后才启用增强;启用所需(如敏感 scope)缺失时降级而非崩。

## 3. Feishu 首渠道(搬进新形,行为不变)
- 无关部分 → `core/`;feishu 特定(parent fetch、`_download_feishu_*`、`group_msg`、`mentions` 门控、response 关联、内置 cron 投递)→ `channels/feishu.py` 的 `FeishuSeam`。
- 保持 F1/F2/F3/F5/F6 已验收正确;**F4 修复并入 core**(见 §4);factory 实现 §2.5 不-brick 降级。

## 4. F4 修复(进 core,跨平台正确)
- core 在**出站点按 `response_correlation_key`(seam 提供)**把结论关联到正确触发 @;**排除 bot 自发 send**(告知、standing 触发)。**不假设 `task_session_id` 跨平台存在**——关联键由各渠道 seam 给(feishu 可用其 reply/会话锚)。

## 5. 装机补全(目标2,逐项)
- **根级布局**:clone 后 `~/.hermes/plugins/hermes-tag/` 根含 `plugin.yaml` + `__init__.py(register)` + `core/` + `channels/`(现 `src/` 布局改根布局)。
- **manifest**:用真实字段 + 可选 `manifest_version: 1` + `requires_env`(注意是 requires_env,非 required_env);保留 `label`;删 `entrypoint/hermes_version/platform` 等无效字段(版本 pin 移 README/pyproject)。
- **依赖**:**不依赖安装器装 pyproject 依赖**;lark-oapi 复用 Hermes 自带 Feishu 依赖(覆盖 feishu 即已在环境);任何额外依赖在 `after-install.md` 写明手动 `pip install` 步骤;声明同环境 hermes-agent pin v2026.6.19。
- **register/factory**:§2.5。
- **env/config**:`requires_env=FEISHU_APP_ID/FEISHU_APP_SECRET`;`plugins.enabled` 打开;`extra.feishu_tag`(enabled/enabled_chats/bot_open_id/granted_scopes/admins/encryption_posture/上限);平台 `require_mention=false`(配 receive-all)。
- **after-install.md**:敏感 scope 审批、配置样例、require_mention=false 设置、依赖说明、隐私告知。

## 6. 验收门槛(可验证两目标)
- **目标1·可扩展性(MUST)**:加一个**真实 Hermes 形状的第二渠道 fixture**(经 `BasePlatformAdapter.handle_message` + 真 `MessageEvent` + `send`,或最小真插件平台),**不改 core** 跑通其 dispatch/记忆/standing/降级 + **响应关联(F4)**;diff 证明 core 0 改动。**纯 mock 不算**。
- **目标2·安装(MUST,R4 级)**:真实 Hermes `hermes plugins install <repo>` → `hermes plugins list` 可见 → enable 覆盖 feishu adapter 生效 → `after-install.md` 显示。
- **不-brick 内置(MUST)**:**未配置 `extra.feishu_tag` 时启用本插件,Feishu 平台仍正常工作**(factory 安全降级,不抛错)。
- **F4(MUST)**:standing/notice send 不污染 pending@、乱序不串、无回复不误写 + 效力自检;关联走 seam `response_correlation_key`,不依赖 task_session_id。
- **回归(MUST)**:现 36 逻辑测试不退;F1/F2/F3/F5/F6 保持;桩忠实(无猴补字段)。
- **能力降级(MUST)**:无 reply-media/无 receive-all/无 cron 投递时按能力矩阵优雅降级(测试)。

## 7. 迁移步骤(增量,各步独立可测)
1. 抽 `core`(组合式;纯搬移,行为不变,测试绿)。
2. 定义扩面 `PlatformSeam`;feishu 重构为 `seam + core`;factory 实现不-brick 降级(测试绿)。
3. F4 修复并入 core,改用 `response_correlation_key`(新测)。
4. 装机补全(根布局/manifest 更正/requires_env/after-install/依赖说明)。
5. 真实 Hermes 形状第二渠道 fixture,证明 core 0 改动可扩展。
6. R4 活体:feishu smoke + 真实 `hermes plugins install` smoke + 不-brick 验证;R5 scope 记录。

## 8. 开放问题(Codex 已答的记为已定,余待真环境)
1. `pre_gateway_dispatch`:在 MessageEvent 到 gateway 后、auth 前触发;Feishu 未@(require_mention=true)**不触发** → **已定**:hook 不用于未@摄取;v1 不依赖 hook。
2. 单仓单插件 → **已定**为最优。
3. manifest:`manifest_version` 可选(max 1)、根 `__init__.py`、`requires_env` → **已定**。
4. Mixin vs 组合 vs hook → **已定**:v1 子类 + 组合(避 MRO);hook 仅 receive-all 证后。
5. F4 关联键 → **已定**:per-channel `response_correlation_key` seam,不假设 task_session_id。
6. **待真环境验**:require_mention=false + group_msg 下,Feishu 未@消息是否真到达入站层供 Tier-0 摄取(R4 必验)。
