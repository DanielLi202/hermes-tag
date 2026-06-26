import asyncio
from dataclasses import dataclass, field
import os
import tempfile
import unittest
from types import SimpleNamespace
from typing import Any

os.environ["HERMES_PLUGIN_SLACK_USE_STUBS"] = "1"

from hermes_tag.platforms.slack import MessageEvent, PlatformConfig, SlackAdapter, SlackTagAdapter, adapter_factory


@dataclass
class SlackEvent:
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


class SlackSeamTest(unittest.TestCase):
    def test_slack_tag_intercepts_enabled_chats_mentions_and_passthrough(self):
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.close()
        os.unlink(tmp.name)
        cfg = PlatformConfig({
            "slack_tag": {
                "enabled": True,
                "enabled_chats": ["C1"],
                "db_path": tmp.name,
                "media_cache_dir": tmp.name + ".media",
                "encryption_posture": "plain",
            }
        })
        adapter = adapter_factory(cfg)
        self.assertIsInstance(adapter, SlackTagAdapter)
        adapter._bot_user_id = "BOT"

        ambient = SlackEvent("ambient", source=SimpleNamespace(chat_id="C1", user_id="U1"), message_id="m1")
        self.assertIsNone(asyncio.run(adapter.handle_message(ambient)))
        self.assertEqual(adapter.store.count_tier0("C1"), 1)
        self.assertEqual(adapter.dispatched, [])

        mentioned = SlackEvent("<@BOT> ping", source=SimpleNamespace(chat_id="C1", user_id="U1"), message_id="m2")
        self.assertIsNone(asyncio.run(adapter.handle_message(mentioned)))
        self.assertEqual(adapter.store.count_tier0("C1"), 2)
        self.assertEqual(len(adapter.dispatched), 1)
        self.assertEqual(adapter.dispatched[0].channel_context, "current: <@BOT> ping")
        self.assertTrue(adapter.is_mentioned(mentioned))
        self.assertFalse(adapter.is_mentioned(SlackEvent("ping", source=SimpleNamespace(chat_id="C1"))))
        self.assertTrue(adapter.is_mentioned(SlackEvent("dm", source=SimpleNamespace(chat_id="D1", chat_type="dm"))))

        other = SlackEvent("outside", source=SimpleNamespace(chat_id="C2"), message_id="m3")
        self.assertIsNone(asyncio.run(adapter.handle_message(other)))
        self.assertEqual(adapter.store.count_tier0("C2"), 0)
        self.assertEqual(len(adapter.dispatched), 2)

        self.assertIsInstance(adapter_factory(PlatformConfig({"slack_tag": {"enabled": False}})), SlackAdapter)
        self.assertTrue(issubclass(MessageEvent, object))


if __name__ == "__main__":
    unittest.main()
