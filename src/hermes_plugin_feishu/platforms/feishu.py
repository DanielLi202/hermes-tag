from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import importlib
import json
import os
from types import SimpleNamespace
from typing import Any

from ..base import (
    HermesCronAPI,
    TagAdapterMixin,
    _get_nested,
    _tag_extra,
    assert_real_seams,
)
from ..core import TagConfig as FeishuTagConfig, TagStore as FeishuTagStore

BASE_FEISHU_MODULE = ""
BASE_FEISHU_IMPORT_ERROR = ""
FEISHU_AVAILABLE = False


def _load_base_feishu_module() -> Any:
    errors: list[str] = []
    for module_name in ("plugins.platforms.feishu.adapter", "gateway.platforms.feishu"):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")
    raise ImportError("; ".join(errors))


try:  # real Hermes path
    if os.getenv("HERMES_PLUGIN_FEISHU_USE_STUBS"):
        raise ImportError("forced stub mode")
    from gateway.config import PlatformConfig
    from gateway.platforms.base import MessageEvent, MessageType
    _base_feishu = _load_base_feishu_module()
    BASE_FEISHU_MODULE = getattr(_base_feishu, "__name__", "")
    FEISHU_AVAILABLE = bool(getattr(_base_feishu, "FEISHU_AVAILABLE", False))
    FeishuAdapter = getattr(_base_feishu, "FeishuAdapter")
    normalize_feishu_message = getattr(_base_feishu, "normalize_feishu_message")
    _base_check_requirements = getattr(_base_feishu, "check_feishu_requirements", lambda: FEISHU_AVAILABLE)
    _base_apply_yaml_config = getattr(_base_feishu, "_apply_yaml_config", None)
    _base_interactive_setup = getattr(_base_feishu, "interactive_setup", None)
    _base_standalone_send = getattr(_base_feishu, "_standalone_send", None)
except Exception:  # local tests / scaffold path
    BASE_FEISHU_IMPORT_ERROR = "base Feishu adapter is unavailable"
    FEISHU_AVAILABLE = False
    _base_check_requirements = lambda: FEISHU_AVAILABLE
    _base_apply_yaml_config = None
    _base_interactive_setup = None
    _base_standalone_send = None

    class PlatformConfig:  # type: ignore[no-redef]
        def __init__(self, extra: dict[str, Any] | None = None):
            self.extra = extra or {}

    class MessageType:  # type: ignore[no-redef]
        TEXT = "text"
        COMMAND = "command"

    @dataclass
    class _Source:
        chat_id: str
        user_id: str = ""
        user_name: str = ""
        thread_id: str | None = None

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

    class FeishuAdapter:  # type: ignore[no-redef]
        def __init__(self, config: PlatformConfig):
            self.config = config
            self.dispatched: list[MessageEvent] = []
            self.sent: list[tuple[str, str]] = []

        async def _dispatch_inbound_event(self, event: MessageEvent) -> Any:
            self.dispatched.append(event)
            return None

        async def _download_feishu_image(self, *, message_id: str, image_key: str) -> tuple[str, str]:
            return "", ""

        async def _download_feishu_message_resource(self, *, message_id: str, file_key: str, resource_type: str, fallback_filename: str = "") -> tuple[str, str]:
            return "", ""

        async def send(self, chat_id: str, content: str, reply_to=None, metadata=None) -> Any:
            self.sent.append((chat_id, content))
            return {"chat_id": chat_id, "content": content, "reply_to": reply_to, "metadata": metadata}

    def normalize_feishu_message(*, message_type: str, raw_content: str, mentions=None, bot=None):  # type: ignore[no-redef]
        payload = json.loads(raw_content or "{}")
        return type("Normalized", (), {
            "image_keys": [payload["image_key"]] if payload.get("image_key") else [],
            "media_refs": [type("MediaRef", (), {"file_key": payload.get("file_key", ""), "resource_type": message_type, "file_name": payload.get("file_name", "")})()] if payload.get("file_key") else [],
        })()


class FeishuTagAdapter(TagAdapterMixin, FeishuAdapter):
    base_feishu_module = BASE_FEISHU_MODULE
    base_platform_module = BASE_FEISHU_MODULE

    def __init__(self, config: PlatformConfig, tag_config: FeishuTagConfig | None = None, cron_api: Any | None = None):
        super().__init__(config, tag_config or FeishuTagConfig.from_platform_config(config), cron_api)

    @property
    def platform_name(self) -> str:
        return "feishu"

    @property
    def receive_all(self) -> bool:
        return self.tag.has_group_msg_scope

    def is_mentioned(self, event: MessageEvent) -> bool:
        if getattr(getattr(event, "source", None), "chat_type", "") == "dm":
            return True
        raw_message = _raw_feishu_message(event)
        if raw_message is not None and hasattr(self, "_mentions_self"):
            try:
                if self._mentions_self(raw_message):
                    return True
            except Exception:
                pass
        return _is_mentioned(event, self.tag)

    async def _fetch_reply_media_refs(self, reply_id: str) -> list[dict]:
        if hasattr(self, "parent_messages"):
            parent = self.parent_messages.get(reply_id, {})
            return [dict(ref) for ref in parent.get("media_refs", [])]
        client = getattr(self, "_client", None)
        if not client or not hasattr(self, "_build_get_message_request"):
            return []
        request = self._build_get_message_request(reply_id)
        response = await asyncio.to_thread(client.im.v1.message.get, request)
        if not response or not getattr(response, "success", lambda: False)():
            return []
        items = getattr(getattr(response, "data", None), "items", None) or []
        parent = items[0] if items else None
        if not parent:
            return []
        body = getattr(parent, "body", None)
        normalized = normalize_feishu_message(
            message_type=getattr(parent, "msg_type", "") or "",
            raw_content=getattr(body, "content", "") or "",
            mentions=getattr(parent, "mentions", None),
        )
        refs = [{"kind": "image", "key": key} for key in getattr(normalized, "image_keys", [])]
        for media_ref in getattr(normalized, "media_refs", []):
            refs.append({
                "kind": getattr(media_ref, "resource_type", "file"),
                "key": getattr(media_ref, "file_key", ""),
                "resource_type": getattr(media_ref, "resource_type", "file"),
                "filename": getattr(media_ref, "file_name", ""),
            })
        return refs

    async def _fetch_parent_media_refs(self, message_id: str) -> list[dict[str, str]]:
        return await self._fetch_reply_media_refs(message_id)

    async def _download_media(self, reply_id: str, ref: dict) -> tuple[str, str]:
        key = ref.get("key", "")
        if ref.get("kind") == "image":
            return await self._download_feishu_image(message_id=reply_id, image_key=key)
        return await self._download_feishu_message_resource(
            message_id=reply_id,
            file_key=key,
            resource_type=ref.get("resource_type", "file"),
            fallback_filename=ref.get("filename", ""),
        )

    def disable_chat(self, chat_id: str) -> None:
        return super().disable_chat(chat_id)


def check_requirements() -> bool:
    try:
        return bool(_base_check_requirements())
    except Exception:
        return False


def _is_connected(config: Any) -> bool:
    extra = getattr(config, "extra", {}) or {}
    app_id = str(extra.get("app_id") or os.getenv("FEISHU_APP_ID") or "").strip()
    if app_id:
        return True
    try:
        import hermes_cli.gateway as gateway_mod
        return bool(str(gateway_mod.get_env_value("FEISHU_APP_ID") or "").strip())
    except Exception:
        return False


def _merge_feishu_tag_extra(target: dict[str, Any], source: Any) -> None:
    if not isinstance(source, dict):
        return
    tag_cfg = source.get("feishu_tag")
    if isinstance(tag_cfg, dict):
        target["feishu_tag"] = tag_cfg


def apply_yaml_config(yaml_cfg: dict, feishu_cfg: dict) -> dict | None:
    seeded: dict[str, Any] = {}
    if callable(_base_apply_yaml_config):
        base_seeded = _base_apply_yaml_config(yaml_cfg, feishu_cfg)
        if isinstance(base_seeded, dict):
            seeded.update(base_seeded)

    _merge_feishu_tag_extra(seeded, feishu_cfg)
    extra = feishu_cfg.get("extra") if isinstance(feishu_cfg, dict) else None
    _merge_feishu_tag_extra(seeded, extra)
    top_extra = yaml_cfg.get("extra") if isinstance(yaml_cfg, dict) else None
    _merge_feishu_tag_extra(seeded, top_extra)
    return seeded or None


def register(ctx: Any) -> None:
    ctx.register_platform(
        name="feishu",
        label="Feishu Tag",
        adapter_factory=adapter_factory,
        check_fn=check_requirements,
        is_connected=_is_connected,
        validate_config=_is_connected,
        required_env=["FEISHU_APP_ID", "FEISHU_APP_SECRET"],
        install_hint="Install Hermes with the Feishu platform dependencies, for example: pip install 'hermes-agent[feishu,cron]'.",
        setup_fn=_base_interactive_setup,
        apply_yaml_config_fn=apply_yaml_config,
        allowed_users_env="FEISHU_ALLOWED_USERS",
        allow_all_env="FEISHU_ALLOW_ALL_USERS",
        cron_deliver_env_var="FEISHU_HOME_CHANNEL",
        standalone_sender_fn=_base_standalone_send,
        max_message_length=8000,
        emoji="🏷️",
        allow_update_command=True,
    )


def adapter_factory(config: PlatformConfig) -> FeishuAdapter:
    data = _tag_extra(config)
    if not data.get("enabled"):
        return FeishuAdapter(config)
    try:
        return FeishuTagAdapter(config, FeishuTagConfig.from_platform_config(config))
    except Exception:
        # ponytail: gateway has no built-in fallback after plugin override; bad tag config must not brick Feishu.
        return FeishuAdapter(config)


def _is_mentioned(event: MessageEvent, config: FeishuTagConfig) -> bool:
    if getattr(getattr(event, "source", None), "chat_type", "") == "dm":
        return True
    bot_open_id = config.bot_open_id
    for mention in _event_mentions(event):
        mention_id = getattr(getattr(mention, "id", None), "open_id", None) or getattr(mention, "open_id", None) or (mention.get("id", {}).get("open_id") if isinstance(mention, dict) else None)
        if bot_open_id and mention_id == bot_open_id:
            return True
    return False


def _event_mentions(event: MessageEvent) -> list[Any]:
    raw = getattr(event, "raw_message", None)
    if raw is None:
        return []
    mentions = getattr(event, "mentions", None)
    if mentions:
        return list(mentions)
    for candidate in (raw, _raw_feishu_message(event)):
        if candidate is None:
            continue
        found = getattr(candidate, "mentions", None) or (candidate.get("mentions", []) if isinstance(candidate, dict) else [])
        if found:
            return list(found)
    return []


def _raw_feishu_message(event: MessageEvent) -> Any | None:
    raw = getattr(event, "raw_message", None)
    if raw is None:
        return None
    message = _get_nested(raw, "event", "message") or _get_nested(raw, "message") or raw
    if isinstance(message, dict):
        return SimpleNamespace(**message)
    return message


__all__ = [
    "BASE_FEISHU_IMPORT_ERROR",
    "BASE_FEISHU_MODULE",
    "FEISHU_AVAILABLE",
    "FeishuAdapter",
    "FeishuTagAdapter",
    "FeishuTagConfig",
    "FeishuTagStore",
    "HermesCronAPI",
    "MessageEvent",
    "MessageType",
    "PlatformConfig",
    "_event_mentions",
    "_is_connected",
    "_is_mentioned",
    "_load_base_feishu_module",
    "_merge_feishu_tag_extra",
    "_raw_feishu_message",
    "adapter_factory",
    "apply_yaml_config",
    "assert_real_seams",
    "check_requirements",
    "normalize_feishu_message",
    "register",
]
