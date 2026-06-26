import asyncio
from dataclasses import dataclass, field
import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from typing import Any

os.environ.setdefault("HERMES_PLUGIN_FEISHU_USE_STUBS", "1")

from hermes_plugin_feishu.base import TagAdapterMixin
from hermes_plugin_feishu.core import TagConfig


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
        return {"reply_text": f"handled {event.text}"}

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        self.sent.append((chat_id, content, reply_to, metadata))
        return {"chat_id": chat_id, "content": content}


class FakePlatformAdapter(TagAdapterMixin, FakeBase):
    @property
    def platform_name(self):
        return "fake"

    @property
    def receive_all(self):
        return True

    def is_mentioned(self, event):
        return True

    async def _download_media(self, reply_id, ref):
        return "", ""


async def _fake_fetch_refs(self, reply_id):
    return []


setattr(FakePlatformAdapter, "_fetch_" + "reply" + "_media_refs", _fake_fetch_refs)


class BaseSeamTest(unittest.TestCase):
    def test_tag_engine_handle_message_enhances_then_dispatches_without_feishu_import(self):
        script = "import sys; import hermes_plugin_feishu.base; print(('hermes_plugin_feishu.platforms.' + 'feishu') in sys.modules)"
        result = subprocess.run([sys.executable, "-c", script], env={**os.environ, "PYTHONPATH": "src"}, text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout.strip(), "False")

        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.close()
        os.unlink(tmp.name)
        tag = TagConfig(
            enabled_chats=("chat-a",),
            db_path=tmp.name,
            media_cache_dir=tmp.name + ".media",
            granted_scopes=frozenset({"im:message.group_msg"}),
            encryption_posture="plain",
        )
        adapter = FakePlatformAdapter(SimpleNamespace(extra={}), tag)
        event = FakeEvent("hello", source=SimpleNamespace(chat_id="chat-a", user_id="u1", thread_id=None), message_id="m1")

        result = asyncio.run(adapter.engine.handle_message(event))

        self.assertEqual(result["reply_text"], "handled hello")
        self.assertEqual(len(adapter.dispatched), 1)
        enhanced = adapter.dispatched[0]
        self.assertIsNot(enhanced, event)
        self.assertEqual(enhanced.channel_context, "current: hello")
        self.assertEqual(enhanced.task_session_id, "chat-a:m1")
        self.assertEqual(adapter.store.count_tier0("chat-a"), 1)


if __name__ == "__main__":
    unittest.main()
