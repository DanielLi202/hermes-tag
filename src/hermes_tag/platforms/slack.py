from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import os
from typing import Any

from ..base import HermesCronAPI, TagAdapterMixin, assert_real_seams
from ..core import TagConfig, TagStore

BASE_SLACK_MODULE = ""
BASE_SLACK_IMPORT_ERROR = ""
SLACK_AVAILABLE = False


def _load_base_slack_module() -> Any:
    return importlib.import_module("plugins.platforms.slack.adapter")


try:  # real Hermes path
    if os.getenv("HERMES_PLUGIN_SLACK_USE_STUBS"):
        raise ImportError("forced stub mode")
    from gateway.config import PlatformConfig
    from gateway.platforms.base import MessageEvent, MessageType

    _base_slack = _load_base_slack_module()
    BASE_SLACK_MODULE = getattr(_base_slack, "__name__", "")
    SLACK_AVAILABLE = bool(getattr(_base_slack, "SLACK_AVAILABLE", False))
    SlackAdapter = getattr(_base_slack, "SlackAdapter")
    _base_check_requirements = getattr(_base_slack, "check_slack_requirements", lambda: SLACK_AVAILABLE)
    _base_build_adapter = getattr(_base_slack, "_build_adapter")
    _base_is_connected = getattr(_base_slack, "_is_connected", None)
    _base_interactive_setup = getattr(_base_slack, "interactive_setup", None)
    _base_apply_yaml_config = getattr(_base_slack, "_apply_yaml_config", None)
    _base_standalone_send = getattr(_base_slack, "_standalone_send", None)
except Exception:  # local tests / scaffold path
    BASE_SLACK_IMPORT_ERROR = "base Slack adapter is unavailable"
    SLACK_AVAILABLE = False
    _base_check_requirements = lambda: SLACK_AVAILABLE
    _base_is_connected = None
    _base_interactive_setup = None
    _base_apply_yaml_config = None
    _base_standalone_send = None

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

    def _base_build_adapter(config: PlatformConfig) -> SlackAdapter:  # type: ignore[no-redef]
        return SlackAdapter(config)


def _slack_tag_extra(config: Any) -> dict[str, Any]:
    extra = config.get("extra", config) if isinstance(config, dict) else (getattr(config, "extra", {}) or {})
    data = extra.get("slack_tag", {}) if isinstance(extra, dict) else {}
    return data if isinstance(data, dict) else {}


def _slack_tag_config(config: Any) -> TagConfig:
    data = _slack_tag_extra(config)
    return TagConfig(
        enabled_chats=tuple(data.get("enabled_chats") or ()),
        db_path=str(data.get("db_path") or "slack-tag.sqlite3"),
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


def check_requirements() -> bool:
    try:
        return bool(_base_check_requirements())
    except Exception:
        return False


def _is_connected(config: Any) -> bool:
    if callable(_base_is_connected):
        try:
            return bool(_base_is_connected(config))
        except Exception:
            pass
    return bool(os.getenv("SLACK_BOT_TOKEN", "").strip())


def _merge_slack_tag_extra(target: dict[str, Any], source: Any) -> None:
    if not isinstance(source, dict):
        return
    tag_cfg = source.get("slack_tag")
    if isinstance(tag_cfg, dict):
        target["slack_tag"] = tag_cfg


def apply_yaml_config(yaml_cfg: dict, slack_cfg: dict) -> dict | None:
    seeded: dict[str, Any] = {}
    if callable(_base_apply_yaml_config):
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
    ctx.register_platform(
        name="slack",
        label="Slack Tag",
        adapter_factory=adapter_factory,
        check_fn=check_requirements,
        is_connected=_is_connected,
        required_env=["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"],
        install_hint="pip install 'hermes-agent[slack]'",
        setup_fn=_base_interactive_setup,
        apply_yaml_config_fn=apply_yaml_config,
        cron_deliver_env_var="SLACK_HOME_CHANNEL",
        standalone_sender_fn=_base_standalone_send,
        max_message_length=39000,
        emoji="🏷️",
        allow_update_command=True,
    )


__all__ = [
    "BASE_SLACK_IMPORT_ERROR",
    "BASE_SLACK_MODULE",
    "SLACK_AVAILABLE",
    "HermesCronAPI",
    "MessageEvent",
    "MessageType",
    "PlatformConfig",
    "SlackAdapter",
    "SlackTagAdapter",
    "TagConfig",
    "TagStore",
    "_is_connected",
    "_load_base_slack_module",
    "_merge_slack_tag_extra",
    "_slack_tag_config",
    "adapter_factory",
    "apply_yaml_config",
    "assert_real_seams",
    "check_requirements",
    "register",
]
