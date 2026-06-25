Hermes Feishu Tag 插件设计文档
背景
用户希望 Hermes 在飞书群聊中的体验接近 Claude Tag：机器人不只是被 @ 后回答当前一句话，而是能理解当前群聊/线程的上下文、引用消息、图片、文件、历史讨论和相关飞书文档，并在明确被 @ 时给出上下文感知的回复。
当前 Hermes 已经有 Feishu/Lark gateway、profile、session、memory、tools、cron 等基础能力，但 Feishu 侧仍缺少一个“频道上下文层”。因此推荐做本地 Hermes 插件增强 Feishu adapter，而不是新造一个独立 agent 系统，也不依赖 upstream PR 合并速度。
问题域
插件要解决的是 Feishu 群聊中的“上下文感知 agent”问题，核心包括：
引用消息上下文丢失
用户 @ bot 时引用了一条历史图片/文件消息，Hermes 当前只看到引用文本或 [Image] 占位符，拿不到真实图片/文件资源，导致 vision 和文件处理无法工作。

未 @ 消息不可用
Hermes 在 require_mention=true 时只处理 @ bot 的消息。用户在群里连续发几条背景说明，最后才 @ bot 时，前面的未 @ 消息已经被丢弃，无法作为上下文。

群聊上下文不是 channel-native
Hermes memory 是 profile 级记忆；session 是 agent 会话级；但 Claude Tag 类体验需要按 Feishu chat_id/thread_id 隔离的 channel memory/journal。

飞书业务知识不在上下文中
真实工作上下文往往在飞书文档、知识库、Base、日历、任务等，而不只在聊天记录里。插件应能通过官方能力检索这些信息。

隐私与成本边界
不能让 agent 常驻处理全群消息、频繁调用模型或无限读取历史。应保持“只有明确 @ bot 才触发 agent 回复”，非 @ 消息只做本地、可配置、可审计的上下文缓存。

目标
插件目标不是替换 Hermes，而是增强 Hermes Feishu adapter，让 “时令 PM” 具备以下能力：
被 @ 时能看到当前消息、引用消息、图片/文件附件。
被 @ 时能带上最近相关的未 @ 群聊上下文。
按群/线程隔离上下文，不跨群泄漏。
能检索飞书文档/知识库作为回答依据。
默认安全保守：不主动回复未 @ 消息，不自动调用模型处理所有群消息。
可通过配置逐群启用、逐项关闭。
非目标
第一版不做：
不做完整 Claude Tag 克隆。
不默认主动发言或监控全公司频道。
不替换 Hermes memory/provider/session 系统。
不重写 Feishu adapter 全部逻辑。
不自己封装全部飞书 API；优先复用官方 larksuite/cli。
不依赖 upstream PR 合并。
推荐形态
插件应以 Hermes user platform plugin 形式存在，放在：
~/.hermes/plugins/feishu-tag/
  plugin.yaml
  adapter.py
  context_store.py
  context_builder.py
  lark_docs.py
  migrations/
  tests/
插件注册同一个 platform name：feishu，覆盖内置 Feishu adapter。Hermes platform registry 支持同名 platform 重新注册，后注册者覆盖前注册者。
实现方式：
from plugins.platforms.feishu.adapter import FeishuAdapter

class FeishuTagAdapter(FeishuAdapter):
    ...
也就是继承官方 Feishu adapter，只覆盖入站消息处理相关方法。不要复制整份官方 adapter。
为什么不是普通插件或 hook
Tool/MCP 插件太晚：模型已经开始执行，无法补齐入站媒体和未 @ 上下文。
Gateway hook 太弱：现有 hook 更偏生命周期通知，不适合稳定改写 MessageEvent。
修改 Hermes core 容易被 hermes update 覆盖。
Platform plugin 位于 Feishu 消息进入 agent 之前，正好能做上下文补全。
核心架构
整体流程：
Feishu event
  ↓
FeishuTagAdapter
  ↓
Admission / mention check
  ↓
if not mentioned:
    store in channel journal
    do not dispatch to agent
else:
    resolve current message media
    resolve replied message media/text
    fetch buffered context
    fetch channel summary / doc snippets
    build enriched MessageEvent
    dispatch to Hermes runner
模块设计
adapter.py
继承官方 FeishuAdapter。
覆盖入站处理流程。
在非 @ 消息时写入 context store，不进入 agent。
在 @ 消息时构建增强上下文，并合并进 MessageEvent。
复用官方资源下载方法，避免重复实现 image_key/file_key 处理。
context_store.py
本地 SQLite 存储 channel journal。
建议表：
messages(
  id INTEGER PRIMARY KEY,
  platform TEXT,
  chat_id TEXT NOT NULL,
  thread_id TEXT,
  message_id TEXT UNIQUE,
  sender_id TEXT,
  sender_name TEXT,
  text TEXT,
  raw_type TEXT,
  mentions_bot INTEGER,
  reply_to_message_id TEXT,
  media_meta_json TEXT,
  created_at TEXT,
  consumed_at TEXT
);

channel_summaries(
  id INTEGER PRIMARY KEY,
  chat_id TEXT NOT NULL,
  thread_id TEXT,
  summary TEXT NOT NULL,
  updated_at TEXT
);
context_builder.py
负责把上下文组装成 agent 输入。
输入：
当前消息文本
当前消息附件
引用消息文本/附件
最近未 @ 缓冲消息
channel summary
飞书 docs 检索结果
输出：
增强后的 text
合并后的 media_urls/media_types
可选 metadata
lark_docs.py
调用官方 lark-cli。
支持 docs/wiki/base/search 的最小检索。
第一版只需要“按关键词检索文档并返回片段/链接”。
不直接存敏感 token；复用 lark-cli 配置。
第一阶段功能
第一阶段只做最小闭环。
引用媒体补全
当消息有：
parent_id / upper_message_id / root_id
插件调用 Feishu message.get 获取被引用消息，复用官方消息 normalize 和 resource download 逻辑：
图片：下载为 Hermes image cache，加入 media_urls/media_types
文件：下载为 document cache，加入 media_urls/media_types
文本：保留为 reply_to_text
下载失败：降级为文本占位，不中断
限制：
max_reply_media_items: 4
max_reply_media_bytes: 10485760
未 @ 上下文缓冲
当群消息未 @ bot：
如果该群启用了 buffer，则存入 SQLite。
不调用模型。
不回复。
不进入 Hermes session。
当后续同一用户 @ bot：
取该用户在同一 chat_id/thread_id 下、上次 bot 回复之后的消息。
拼接进当前输入。
bot 回复后标记 consumed。
增强输入格式
示例：
[Feishu channel context]
Chat: 产品 PM 群
Thread: om_xxx

[Recent messages before mention]
- Alice 10:21: 这个截图里预算字段不对
- Alice 10:22: 应该看右上角的时间范围
- Bob 10:23: 我觉得是日报统计口径问题

[Replying to message]
Text: [Image]
Attachments: 1 image attached from replied message

[Current request]
@时令 PM 判断这张截图是不是口径错了
图片不只写文本说明，还必须合并进 media_urls，让 Hermes 原生 vision 流程处理。
第二阶段功能
Channel Journal 检索
当 @ 请求里出现“刚才”“上面”“前面说的”“那个截图”等指代时，自动检索最近消息。
Channel Summary
定期或按阈值总结 channel buffer：
本群正在讨论什么
未解决问题
当前任务/owner
重要决策
摘要按 chat_id/thread_id 隔离。
飞书文档 grounding
接入 lark-cli：
检索 wiki/docs
拉取相关文档片段
回答中引用文档标题/链接
默认只在 @ 请求需要外部资料时触发
第三阶段功能
主动/异步任务
通过 Hermes cron 实现：
每天总结某个群的阻塞事项
跟进未完成任务
检查飞书文档更新
到点提醒
默认关闭，只对 allowlist 群启用。
Standing Work 管理
支持用户问：
@时令 PM 你在这个群里有哪些自动任务？
@时令 PM 取消每周五总结
插件把 standing work 映射到 Hermes cron job。
配置建议
feishu_tag:
  enabled: true

  # 保持 Hermes 安全行为：只有 @ 才触发 agent
  require_mention: true

  # 非 @ 消息只缓存，不回复
  buffer_unmentioned_context: true
  buffer_scope: since_last_bot_reply
  buffer_authors: same_user
  max_buffer_messages: 20
  max_buffer_age_minutes: 180
  max_context_chars: 12000

  # 引用媒体补全
  resolve_reply_media: true
  max_reply_media_items: 4
  max_reply_media_bytes: 10485760

  # 逐群启用，避免默认读取所有群
  enabled_chats:
    - oc_xxx

  # 文档检索
  docs_rag:
    enabled: false
    provider: lark-cli
    max_results: 5
    max_chars: 6000

  # 长期 channel memory
  channel_memory:
    enabled: false
    summarize_after_messages: 50
    max_summary_chars: 4000

  # 主动任务
  proactive:
    enabled: false
隐私与安全原则
默认只对 enabled_chats 生效。
非 @ 消息只本地落库，不进模型。
@ 时才把必要上下文送入 agent。
所有缓存按 chat_id/thread_id 隔离。
默认不跨群检索。
默认不读取飞书文档，除非启用 docs_rag。
提供清理命令或管理接口：清空某群上下文
查看缓存条数
关闭某群增强

日志不打印 app secret、用户 token、完整敏感文档。
与现有开源项目的关系
不直接替换 Hermes，但复用/借鉴：
larksuite/cli
官方 Feishu/Lark CLI，作为 docs/wiki/base/calendar/tasks 等 API 入口。

alwayset/agent-tag
借鉴 per-channel isolated memory、Lark wiki FTS5 corpus、docs grounding。项目很新，适合作为参考，不宜直接替换 Hermes。

shareAI-lab/lark-channel
借鉴“每个飞书群是一个 workspace”和 Feishu streaming cards。它偏 Claude Code 工作区桥，不适合作为 Hermes 的直接替代。

CowAgent
长期记忆与知识库架构可参考，但它是完整 agent stack，不适合作为 Hermes 插件基础。

开发路线
第一轮：MVP
创建 ~/.hermes/plugins/feishu-tag
注册覆盖 feishu platform
继承官方 FeishuAdapter
实现引用媒体补全
实现未 @ 消息 buffer
实现 @ 时上下文拼接
SQLite journal
基础测试
第二轮：知识增强
接入 lark-cli
docs/wiki 检索
channel summary
上下文预算裁剪
第三轮：Claude Tag 类能力
standing work
cron follow-up
channel memory 管理
管理命令
审计视图
关键风险
Hermes 内置 Feishu adapter 更新后接口变化
插件继承官方类，需跟随 hermes update 做兼容测试。

同名 platform 覆盖顺序
需要验证 user plugin 是否在 bundled Feishu 后注册。如果顺序不符合预期，可用不同 platform name feishu_tag 作为 fallback，但会增加配置迁移成本。

权限不足
引用媒体、文档检索、消息读取需要 Feishu app 权限。插件应在启动时检测权限，给出明确提示。

上下文过量
群聊噪声很大。必须限制 message count、age、chars，并按相关性裁剪。

隐私争议
即使不进模型，缓存未 @ 群消息也需要明确启用和可清理机制。

最终建议
做成本地 Hermes platform plugin：feishu-tag。
它覆盖 Feishu 入站边界，保持 “只有 @ 才触发 agent”，但在触发时补齐引用媒体、最近上下文和飞书文档 grounding。这样既不等 upstream PR，也不 fork Hermes，还能保持 hermes update 基本可用。