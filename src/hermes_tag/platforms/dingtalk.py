from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import os
from types import SimpleNamespace
from typing import Any

from ..base import HermesCronAPI, TagAdapterMixin, assert_real_seams, capture_platform_registration
from ..core import TagConfig, TagStore, default_db_path

BASE_DINGTALK_MODULE = ""


def _load_base_dingtalk_module() -> Any:
    return importlib.import_module("plugins.platforms.dingtalk.adapter")


if os.getenv("HERMES_PLUGIN_DINGTALK_USE_STUBS") != "1":
    from gateway.config import PlatformConfig
    from gateway.platforms.base import MessageEvent, MessageType

    _base_dingtalk = _load_base_dingtalk_module()
    BASE_DINGTALK_MODULE = getattr(_base_dingtalk, "__name__", "")
    DingTalkAdapter = getattr(_base_dingtalk, "DingTalkAdapter")
else:  # explicit contract stubs
    class PlatformConfig:  # type: ignore[no-redef]
        def __init__(self, extra: dict[str, Any] | None = None):
            self.extra = extra or {}

    class MessageType:  # type: ignore[no-redef]
        TEXT = "text"
        COMMAND = "command"

    @dataclass
    class MessageEvent:  # type: ignore[no-redef]
        text: str
        source: Any = None
        raw_message: Any = None
        message_id: str | None = None
        media_urls: list[str] = field(default_factory=list)
        media_types: list[str] = field(default_factory=list)
        media_text_inlined: list[bool | None] = field(default_factory=list)
        channel_prompt: str | None = None
        auto_skill: str | list[str] | None = None
        metadata: dict[str, Any] = field(default_factory=dict)
        reply_to_message_id: str | None = None
        reply_to_text: str | None = None
        channel_context: str | None = None
        message_type: Any = MessageType.TEXT

        def is_command(self) -> bool:
            return self.text.startswith("/")

    class DingTalkAdapter:  # type: ignore[no-redef]
        def __init__(self, config: PlatformConfig):
            self.config = config
            self.dispatched: list[MessageEvent] = []
            self.sent: list[tuple[str, str]] = []

        async def handle_message(self, event: MessageEvent) -> Any:
            self.dispatched.append(event)
            return None

        async def send(self, chat_id: str, content: str, reply_to=None, metadata=None) -> Any:
            self.sent.append((chat_id, content))
            return {"chat_id": chat_id, "content": content, "reply_to": reply_to, "metadata": metadata}

    def _stub_register(ctx):
        ctx.register_platform(
            name="dingtalk", label="DingTalk", adapter_factory=DingTalkAdapter,
            check_fn=lambda: False, apply_yaml_config_fn=lambda yaml_cfg, platform_cfg: None,
            allowed_users_env="DINGTALK_ALLOWED_USERS", allow_all_env="DINGTALK_ALLOW_ALL_USERS",
        )

    _base_dingtalk = SimpleNamespace(register=_stub_register)


_base_registration = capture_platform_registration(_base_dingtalk)
_base_apply_yaml_config = _base_registration["apply_yaml_config_fn"]
_base_build_adapter = _base_registration["adapter_factory"]


def _dingtalk_tag_extra(config: Any) -> dict[str, Any]:
    extra = config.get("extra", config) if isinstance(config, dict) else (getattr(config, "extra", {}) or {})
    data = extra.get("dingtalk_tag", {}) if isinstance(extra, dict) else {}
    return data if isinstance(data, dict) else {}


def _dingtalk_tag_config(config: Any) -> TagConfig:
    data = _dingtalk_tag_extra(config)
    return TagConfig(
        enabled_chats=tuple(data.get("enabled_chats") or ()),
        db_path=str(data.get("db_path") or default_db_path("dingtalk")),
        granted_scopes=frozenset(data.get("granted_scopes") or ()),
        encryption_posture=str(data.get("encryption_posture") or "plaintext-db-on-local-disk").strip(),
        max_context_chars=int(data.get("max_context_chars") or 4000),
        max_reply_media_items=int(data.get("max_reply_media_items") or 4),
        max_reply_media_bytes=int(data.get("max_reply_media_bytes") or 8_000_000),
        tier0_ttl_seconds=int(data.get("tier0_ttl_seconds") or 86400),
        tier0_max_count=int(data.get("tier0_max_count") or 500),
        tier1_max_count=int(data.get("tier1_max_count") or 100),
        media_cache_dir=data.get("media_cache_dir"),
        admins=tuple(data.get("admins") or ()),
        tier1_pending_ttl_seconds=int(data.get("tier1_pending_ttl_seconds") or 3600),
        tier0_context_enabled=bool(data.get("tier0_context_enabled", True)),
    )


class DingTalkTagAdapter(TagAdapterMixin, DingTalkAdapter):
    base_platform_module = BASE_DINGTALK_MODULE

    def __init__(self, config: PlatformConfig, tag_config: TagConfig | None = None, cron_api: Any | None = None):
        super().__init__(config, tag_config or _dingtalk_tag_config(config), cron_api)

    @property
    def platform_name(self) -> str:
        return "dingtalk"

    @property
    def receive_all(self) -> bool:
        return True

    async def handle_message(self, event: MessageEvent) -> Any:
        if _chat_id_from(event) not in self.tag.enabled_chats:
            return await super().handle_message(event)
        return await self.engine.handle_message(event)

    async def dispatch_to_model(self, event: MessageEvent) -> Any:
        return await super().handle_message(event)

    def is_mentioned(self, event: MessageEvent) -> bool:
        if getattr(getattr(event, "source", None), "chat_type", "") == "dm":
            return True
        return bool(getattr(getattr(event, "raw_message", None), "is_in_at_list", False))

    def _should_fetch_reply_media(self, event: MessageEvent, reply_id: str) -> bool:
        return False

    async def _fetch_reply_media_refs(self, reply_id: str) -> list[dict]:
        return []

    async def _download_media(self, reply_id: str, ref: dict) -> tuple[str, str]:
        return "", ""


def _chat_id_from(event: Any) -> str:
    return str(getattr(getattr(event, "source", None), "chat_id", "") or getattr(event, "chat_id", ""))


def _merge_dingtalk_tag_extra(target: dict[str, Any], source: Any) -> None:
    if not isinstance(source, dict):
        return
    tag_cfg = source.get("dingtalk_tag")
    if isinstance(tag_cfg, dict):
        target["dingtalk_tag"] = tag_cfg


def apply_yaml_config(yaml_cfg: dict, dingtalk_cfg: dict) -> dict | None:
    seeded: dict[str, Any] = {}
    base_seeded = _base_apply_yaml_config(yaml_cfg, dingtalk_cfg)
    if isinstance(base_seeded, dict):
        seeded.update(base_seeded)

    _merge_dingtalk_tag_extra(seeded, dingtalk_cfg)
    extra = dingtalk_cfg.get("extra") if isinstance(dingtalk_cfg, dict) else None
    _merge_dingtalk_tag_extra(seeded, extra)
    top_extra = yaml_cfg.get("extra") if isinstance(yaml_cfg, dict) else None
    _merge_dingtalk_tag_extra(seeded, top_extra)
    return seeded or None


def adapter_factory(config: PlatformConfig) -> DingTalkAdapter:
    data = _dingtalk_tag_extra(config)
    if not data.get("enabled"):
        return _base_build_adapter(config)
    try:
        return DingTalkTagAdapter(config, _dingtalk_tag_config(config))
    except Exception:
        # ponytail: bad dingtalk_tag config must not brick the normal DingTalk platform.
        return _base_build_adapter(config)


def register(ctx: Any) -> None:
    ctx.register_platform(**{**_base_registration, "label": "Hermes Tag",
                             "adapter_factory": adapter_factory, "apply_yaml_config_fn": apply_yaml_config})


__all__ = [
    "BASE_DINGTALK_MODULE",
    "DingTalkAdapter",
    "DingTalkTagAdapter",
    "HermesCronAPI",
    "MessageEvent",
    "MessageType",
    "PlatformConfig",
    "TagConfig",
    "TagStore",
    "_dingtalk_tag_config",
    "_load_base_dingtalk_module",
    "_merge_dingtalk_tag_extra",
    "adapter_factory",
    "apply_yaml_config",
    "assert_real_seams",
    "register",
]
