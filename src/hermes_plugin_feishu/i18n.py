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


def all_locale_markers(markers: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    return tuple(marker for values in markers.values() for marker in values)
