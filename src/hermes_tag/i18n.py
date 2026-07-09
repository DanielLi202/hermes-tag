from __future__ import annotations

DEICTIC_MARKERS = {
    "zh": (
        "上面",
        "上图",
        "这张图",
        "那张图",
        "这张截图",
        "那个截图",
        "这个截图",
        "刚刚",
        "刚才",
        "前面那条",
        "前面那张",
        "这条",
        "那条",
    ),
    "en": (
        "the image above",
        "that screenshot",
        "the picture above",
        "the one above",
        "earlier screenshot",
        "that picture",
        "above image",
        "previous one",
    ),
}

PLURAL_DEICTIC_MARKERS = {
    "zh": ("这几张", "那几张", "这些图", "那些图", "前面几张", "几张图"),
    "en": ("those images", "the images above", "those screenshots", "the few images above"),
}

ENABLE_NOTICE = {
    "zh": "本群所有消息(含从未与 bot 交互的成员)会被本地记录并短期缓冲；只有在 @ bot 时相关消息才可能进入模型；长期记忆仅来自 @ 交互。",
    "en": "All messages in this group, including from members who have never interacted with the bot, are recorded locally and buffered briefly; only relevant messages may enter the model when @ bot is mentioned; long-term memory only comes from @ interactions.",
}

CAPABILITY_MISMATCH_NOTICE = {
    "zh": "配置声明已授予 im:message.group_msg，但飞书应用实际未持有该权限；未 @ 的群消息不会被投递，群上下文会退化为仅 @ 消息。请在开发者后台「权限管理」授予该权限并重新发布应用版本，或从插件配置 granted_scopes 移除它以关闭此提示。",
    "en": "The config claims im:message.group_msg, but the Feishu app does not actually hold it; non-@ group messages are never delivered, so group context falls back to @-only. Grant the scope in Developer Console > Permissions and republish the app version, or remove it from plugin granted_scopes to silence this notice.",
}

CAPABILITY_UPGRADE_NOTICE = {
    "zh": "飞书应用已持有 im:message.group_msg，但插件配置未声明它。请把该权限加入插件配置 granted_scopes，以启用完整群上下文。",
    "en": "The Feishu app holds im:message.group_msg, but the plugin config does not claim it. Add the scope to plugin granted_scopes to enable full group context.",
}

PROMPT_CONTRACT = (
    "Use only current and channel_context as evidence; if evidence is missing or weak, say so. "
    "Do not infer from unrelated chat history."
)


def all_locale_markers(markers: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    return tuple(marker for values in markers.values() for marker in values)
