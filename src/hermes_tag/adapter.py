from __future__ import annotations

from .base import (
    BOUNDARY_TEXT,
    HERMES_COMMIT,
    HERMES_TAG,
    LARK_OAPI_VERSION,
    HermesCronAPI,
    TagAdapterMixin,
    _assert_signature,
    _author,
    _chat_id,
    _command_event,
    _dedupe,
    _get_nested,
    _normalize_schedule,
    _result_text,
    _source_without_thread,
    _tag_extra,
    _thread_id,
    _unlink_all,
    assert_real_seams,
)
from .core import TagConfig as FeishuTagConfig, TagEngine, TagStore as FeishuTagStore
from .platforms.feishu import (
    BASE_FEISHU_MODULE,
    FeishuAdapter,
    FeishuTagAdapter,
    MessageEvent,
    MessageType,
    PlatformConfig,
    _event_mentions,
    _is_mentioned,
    _load_base_feishu_module,
    _merge_feishu_tag_extra,
    _raw_feishu_message,
    adapter_factory,
    apply_yaml_config,
    normalize_feishu_message,
)

# The package-level register (tag command + feishu/slack/dingtalk), not the
# feishu-only one — 712968e moved command registration up to __init__ but left
# this shim exporting platforms.feishu.register, so adapter.register lost /tag.
from . import register

__all__ = [
    "FeishuTagAdapter",
    "FeishuTagConfig",
    "FeishuTagStore",
    "HermesCronAPI",
    "MessageEvent",
    "PlatformConfig",
    "register",
    "assert_real_seams",
    "apply_yaml_config",
]
