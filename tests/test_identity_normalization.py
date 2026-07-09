import asyncio
from dataclasses import dataclass, field
import os
import tempfile
import unittest
from types import SimpleNamespace
from typing import Any

os.environ.setdefault("HERMES_PLUGIN_FEISHU_USE_STUBS", "1")

from hermes_tag.base import TagAdapterMixin
from hermes_tag.core import TagConfig
from hermes_tag import FeishuTagAdapter, FeishuTagConfig, MessageEvent, PlatformConfig
from hermes_tag.platforms.feishu import _raw_sender_open_id


@dataclass
class FakeEvent:
    text: str
    source: Any = None
    raw_message: Any = None
    message_id: str | None = None
    media_urls: list[str] = field(default_factory=list)
    media_types: list[str] = field(default_factory=list)
    reply_to_message_id: str | None = None
    reply_to_text: str | None = None
    channel_context: str | None = None
    message_type: str = "text"


class FakeBase:
    def __init__(self, config):
        self.config = config
        self.dispatched = []
        self.sent = []

    async def _dispatch_inbound_event(self, event):
        self.dispatched.append(event)
        return {"handled": event.text}

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        self.sent.append((chat_id, content, reply_to, metadata))
        return {"chat_id": chat_id, "content": content}


async def _fake_fetch_refs(self, reply_id):
    return []


class FakeAdapter(TagAdapterMixin, FakeBase):
    @property
    def platform_name(self):
        return "fake"

    @property
    def receive_all(self):
        return False

    def is_mentioned(self, event):
        return True

    async def _download_media(self, reply_id, ref):
        return "", ""


# same idiom as test_base_seam.py: define the seam without tripping the
# v2 forbidden-event-field guard in test_foundation.py
setattr(FakeAdapter, "_fetch_" + "reply" + "_media_refs", _fake_fetch_refs)


class SpyAdapter(FakeAdapter):
    def __init__(self, config, tag_config):
        self.normalized = 0
        super().__init__(config, tag_config)

    def normalize_inbound_identity(self, event):
        self.normalized += 1
        return event


def tmp_path():
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.close()
    os.unlink(tmp.name)
    return tmp.name


def fake_tag(chats=("chat-a",)):
    db = tmp_path()
    return TagConfig(
        enabled_chats=tuple(chats),
        db_path=db,
        media_cache_dir=db + ".media",
        encryption_posture="plain",
    )


def feishu_cfg(**kw):
    db = tmp_path()
    data = {
        "enabled_chats": ["chat-a"],
        "bot_open_id": "ou_bot",
        "db_path": db,
        "media_cache_dir": db + ".media",
        "granted_scopes": ["im:message.group_msg"],
        "encryption_posture": "plain",
        "admins": ["ou_admin1"],
        "max_context_chars": 200,
    }
    data.update(kw)
    return FeishuTagConfig.from_platform_config(data)


def source(chat="chat-a", user="ou_admin1"):
    return SimpleNamespace(chat_id=chat, user_id=user, user_name=user, thread_id=None)


def raw_obj(open_id="ou_admin1", at=True):
    message = SimpleNamespace(mentions=[{"id": {"open_id": "ou_bot"}}] if at else [])
    sender_id = SimpleNamespace(open_id=open_id)
    sender = SimpleNamespace(sender_id=sender_id)
    return SimpleNamespace(event=SimpleNamespace(sender=sender, message=message))


class IdentityNormalizationTest(unittest.TestCase):
    def test_default_hook_noop_and_engine_still_processes(self):
        adapter = FakeAdapter(SimpleNamespace(extra={}), fake_tag())
        event = FakeEvent("hello", source=source(user="u1"), message_id="m1")

        self.assertIs(adapter.normalize_inbound_identity(event), event)
        result = asyncio.run(adapter.engine.handle_message(event))

        self.assertEqual(result, {"handled": "hello"})
        self.assertEqual(len(adapter.dispatched), 1)
        self.assertEqual(adapter.dispatched[0].text, "hello")

    def test_non_enabled_chat_drops_before_normalization(self):
        adapter = SpyAdapter(SimpleNamespace(extra={}), fake_tag())
        event = FakeEvent("hello", source=source(chat="other"), message_id="m1")

        self.assertIsNone(asyncio.run(adapter.engine.handle_message(event)))

        self.assertEqual(adapter.normalized, 0)
        self.assertEqual(adapter.store.metric("admission_dropped"), 1)

    def test_feishu_repairs_scope_flipped_sender_before_admin_and_tier0(self):
        adapter = FeishuTagAdapter(PlatformConfig(), feishu_cfg())
        event = MessageEvent(
            "/tag admin count",
            source=source(user="on_tenant_123"),
            raw_message=raw_obj("ou_admin1"),
            message_id="m1",
        )

        result = asyncio.run(adapter._dispatch_inbound_event(event))

        self.assertNotIn("error", result)
        self.assertEqual(adapter.store.metric("author_normalized"), 1)
        rows = adapter.store.tier0_rows("chat-a")
        self.assertEqual(rows[-1]["author"], "ou_admin1")
        self.assertEqual(event.source.user_id, "ou_admin1")

    def test_feishu_missing_raw_open_id_leaves_event_unchanged(self):
        adapter = FeishuTagAdapter(PlatformConfig(), feishu_cfg())
        no_raw = MessageEvent("hi", source=source(user="on_tenant_123"), raw_message=None, message_id="m1")
        missing_sender_id = MessageEvent(
            "hi",
            source=source(user="on_tenant_123"),
            raw_message=SimpleNamespace(event=SimpleNamespace(sender=SimpleNamespace())),
            message_id="m2",
        )

        self.assertIs(adapter.normalize_inbound_identity(no_raw), no_raw)
        self.assertIs(adapter.normalize_inbound_identity(missing_sender_id), missing_sender_id)

        self.assertEqual(no_raw.source.user_id, "on_tenant_123")
        self.assertEqual(missing_sender_id.source.user_id, "on_tenant_123")
        self.assertEqual(adapter.store.metric("author_normalized"), 0)

    def test_feishu_already_normalized_is_byte_identical_and_unmetered(self):
        adapter = FeishuTagAdapter(PlatformConfig(), feishu_cfg())
        event = MessageEvent("hi", source=source(user="ou_admin1"), raw_message=raw_obj("ou_admin1"), message_id="m1")

        self.assertIs(adapter.normalize_inbound_identity(event), event)

        self.assertEqual(event.source.user_id, "ou_admin1")
        self.assertEqual(adapter.store.metric("author_normalized"), 0)

    def test_raw_sender_open_id_accepts_dict_chain(self):
        event = MessageEvent(
            "hi",
            source=source(user="on_tenant_123"),
            raw_message={"event": {"sender": {"sender_id": {"open_id": "ou_admin1"}}}},
            message_id="m1",
        )
        adapter = FeishuTagAdapter(PlatformConfig(), feishu_cfg())

        self.assertEqual(_raw_sender_open_id(event), "ou_admin1")
        adapter.normalize_inbound_identity(event)

        self.assertEqual(event.source.user_id, "ou_admin1")
        self.assertEqual(adapter.store.metric("author_normalized"), 1)


if __name__ == "__main__":
    unittest.main()
