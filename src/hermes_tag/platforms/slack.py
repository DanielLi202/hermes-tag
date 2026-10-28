from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import os
from types import SimpleNamespace
from typing import Any

from ..base import HermesCronAPI, TagAdapterMixin, assert_real_seams, capture_platform_registration
from ..core import TagConfig, TagStore, default_db_path

BASE_SLACK_MODULE = ""


def _load_base_slack_module() -> Any:
    return importlib.import_module("plugins.platforms.slack.adapter")


if os.getenv("HERMES_PLUGIN_SLACK_USE_STUBS") != "1":
    from gateway.config import PlatformConfig
    from gateway.platforms.base import MessageEvent, MessageType

    _base_slack = _load_base_slack_module()
    BASE_SLACK_MODULE = getattr(_base_slack, "__name__", "")
    SlackAdapter = getattr(_base_slack, "SlackAdapter")
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

    class SlackAdapter:  # type: ignore[no-redef]
        def __init__(self, config: PlatformConfig):
            self.config = config
            self._bot_user_id = None
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
            name="slack", label="Slack", adapter_factory=SlackAdapter,
            check_fn=lambda: False, apply_yaml_config_fn=lambda yaml_cfg, platform_cfg: None,
        )

    _base_slack = SimpleNamespace(register=_stub_register)


_base_registration = capture_platform_registration(_base_slack)
_base_apply_yaml_config = _base_registration["apply_yaml_config_fn"]
_base_build_adapter = _base_registration["adapter_factory"]


def _slack_tag_extra(config: Any) -> dict[str, Any]:
    extra = config.get("extra", config) if isinstance(config, dict) else (getattr(config, "extra", {}) or {})
    data = extra.get("slack_tag", {}) if isinstance(extra, dict) else {}
    return data if isinstance(data, dict) else {}


def _slack_tag_config(config: Any) -> TagConfig:
    data = _slack_tag_extra(config)
    return TagConfig(
        enabled_chats=tuple(data.get("enabled_chats") or ()),
        db_path=str(data.get("db_path") or default_db_path("slack")),
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
        # ponytail: Slack history is bot-visible channel stream, not Feishu im:message.group_msg.
        tier0_context_enabled=bool(data.get("tier0_context_enabled", True)),
    )


class SlackTagAdapter(TagAdapterMixin, SlackAdapter):
    base_platform_module = BASE_SLACK_MODULE

    def __init__(self, config: PlatformConfig, tag_config: TagConfig | None = None, cron_api: Any | None = None):
        super().__init__(config, tag_config or _slack_tag_config(config), cron_api)

    @property
    def platform_name(self) -> str:
        return "slack"

    @property
    def receive_all(self) -> bool:
        return True

    async def handle_message(self, event: MessageEvent) -> Any:
        if _chat_id_from(event) not in self.tag.enabled_chats:
            return await super().handle_message(event)
        if _is_native_slack_command(event) and not _is_tag_command(event):
            return await super().handle_message(event)
        return await self.engine.handle_message(event)

    async def dispatch_to_model(self, event: MessageEvent) -> Any:
        return await super().handle_message(event)

    def is_mentioned(self, event: MessageEvent) -> bool:
        if _is_tag_command(event):
            return True
        source = getattr(event, "source", None)
        if getattr(source, "chat_type", "") == "dm" or getattr(source, "is_dm", False):
            return True
        bot = getattr(self, "_bot_user_id", None)
        text = " ".join(filter(None, [getattr(event, "text", "") or "", _raw_slack_text(event)]))
        return bool(bot and f"<@{bot}>" in text)

    def _should_fetch_reply_media(self, event: MessageEvent, reply_id: str) -> bool:
        if any(row["message_id"] == reply_id for row in self.store.tier0_rows(_chat_id_from(event))):
            return False
        self.store.inc("slack_reply_media_unavailable")
        return False

    async def _fetch_reply_media_refs(self, reply_id: str) -> list[dict]:
        return []

    async def _download_media(self, reply_id: str, ref: dict) -> tuple[str, str]:
        return "", ""


def _chat_id_from(event: Any) -> str:
    return str(getattr(getattr(event, "source", None), "chat_id", "") or getattr(event, "chat_id", ""))


def _raw_slack_text(event: Any) -> str:
    raw = getattr(event, "raw_message", None)
    if isinstance(raw, dict):
        return str(raw.get("text") or "")
    return str(getattr(raw, "text", "") or "")


def _native_slack_command(event: Any) -> str:
    raw = getattr(event, "raw_message", None)
    if isinstance(raw, dict):
        return str(raw.get("command") or "")
    return str(getattr(raw, "command", "") or "")


def _is_native_slack_command(event: Any) -> bool:
    return bool(_native_slack_command(event).startswith("/"))


def _is_tag_command(event: Any) -> bool:
    command = _native_slack_command(event).lstrip("/")
    text = (getattr(event, "text", "") or "").strip()
    return command in {"tag", "standing", "admin"} or text == "/tag" or text.startswith(("/tag ", "/standing", "/admin"))


def _merge_slack_tag_extra(target: dict[str, Any], source: Any) -> None:
    if not isinstance(source, dict):
        return
    tag_cfg = source.get("slack_tag")
    if isinstance(tag_cfg, dict):
        target["slack_tag"] = tag_cfg


def apply_yaml_config(yaml_cfg: dict, slack_cfg: dict) -> dict | None:
    seeded: dict[str, Any] = {}
    base_seeded = _base_apply_yaml_config(yaml_cfg, slack_cfg)
    if isinstance(base_seeded, dict):
        seeded.update(base_seeded)

    _merge_slack_tag_extra(seeded, slack_cfg)
    extra = slack_cfg.get("extra") if isinstance(slack_cfg, dict) else None
    _merge_slack_tag_extra(seeded, extra)
    top_extra = yaml_cfg.get("extra") if isinstance(yaml_cfg, dict) else None
    _merge_slack_tag_extra(seeded, top_extra)
    return seeded or None


def adapter_factory(config: PlatformConfig) -> SlackAdapter:
    data = _slack_tag_extra(config)
    if not data.get("enabled"):
        return _base_build_adapter(config)
    try:
        return SlackTagAdapter(config, _slack_tag_config(config))
    except Exception:
        # ponytail: bad slack_tag config must not brick the normal Slack platform.
        return _base_build_adapter(config)


def register(ctx: Any) -> None:
    ctx.register_platform(**{**_base_registration, "label": "Hermes Tag",
                             "adapter_factory": adapter_factory, "apply_yaml_config_fn": apply_yaml_config})


__all__ = [
    "BASE_SLACK_MODULE",
    "HermesCronAPI",
    "MessageEvent",
    "MessageType",
    "PlatformConfig",
    "SlackAdapter",
    "SlackTagAdapter",
    "TagConfig",
    "TagStore",
    "_load_base_slack_module",
    "_merge_slack_tag_extra",
    "_slack_tag_config",
    "adapter_factory",
    "apply_yaml_config",
    "assert_real_seams",
    "register",
]
