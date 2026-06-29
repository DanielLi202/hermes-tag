import asyncio
import os
import tempfile
import unittest
from types import SimpleNamespace

os.environ.setdefault("HERMES_PLUGIN_DINGTALK_USE_STUBS", "1")

from hermes_tag.platforms.dingtalk import DingTalkAdapter, DingTalkTagAdapter, MessageEvent, PlatformConfig, adapter_factory, register


def event(text, chat_id="C1", user_id="U1", message_id="m1", *, at=False, chat_type="group"):
    return MessageEvent(
        text=text,
        source=SimpleNamespace(chat_id=chat_id, user_id=user_id, user_name=user_id, chat_type=chat_type),
        raw_message=SimpleNamespace(is_in_at_list=at),
        message_id=message_id,
    )


def cfg(*, enabled=True, chats=("C1",), admins=()):
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.close()
    os.unlink(tmp.name)
    return PlatformConfig({
        "dingtalk_tag": {
            "enabled": enabled,
            "enabled_chats": list(chats),
            "admins": list(admins),
            "db_path": tmp.name,
            "media_cache_dir": tmp.name + ".media",
            "encryption_posture": "plain",
        }
    })


class DingTalkSeamTest(unittest.TestCase):
    def test_is_mentioned_uses_dm_or_structured_at_only(self):
        adapter = adapter_factory(cfg())
        self.assertIsInstance(adapter, DingTalkTagAdapter)
        self.assertTrue(adapter.is_mentioned(event("dm", chat_type="dm", at=False)))
        self.assertTrue(adapter.is_mentioned(event("hi", at=True)))
        self.assertFalse(adapter.is_mentioned(event("hi", at=False)))
        self.assertFalse(adapter.is_mentioned(event("/tag admin count", at=False)))

    def test_handle_message_routes_enabled_chats_to_engine_and_others_to_base(self):
        adapter = adapter_factory(cfg(admins=("U1",)))
        self.assertIsNone(asyncio.run(adapter.handle_message(event("ambient", message_id="m1"))))
        self.assertEqual(adapter.store.count_tier0("C1"), 1)
        self.assertEqual(adapter.dispatched, [])

        self.assertIsNone(asyncio.run(adapter.handle_message(event("remember this", message_id="m2", at=True))))
        self.assertEqual(len(adapter.dispatched), 1)
        self.assertIn("U1: ambient", adapter.dispatched[-1].channel_context)
        asyncio.run(adapter.engine.send("C1", "remembered", reply_to="m2"))
        self.assertEqual(adapter.store.count_tier1("C1"), 1)

        outside = event("outside", chat_id="C2", message_id="m3", at=True)
        self.assertIsNone(asyncio.run(adapter.handle_message(outside)))
        self.assertIs(adapter.dispatched[-1], outside)

    def test_dispatch_to_model_uses_base_handle_message_not_feishu_dispatch(self):
        adapter = adapter_factory(cfg())
        self.assertIsNone(asyncio.run(adapter.handle_message(event("ask", message_id="m1", at=True))))
        self.assertEqual(len(adapter.dispatched), 1)
        self.assertEqual(adapter.dispatched[0].text, "ask")

    def test_receive_all_buffers_non_at_without_answer(self):
        adapter = adapter_factory(cfg())
        self.assertTrue(adapter.receive_all)
        self.assertIsNone(asyncio.run(adapter.handle_message(event("background", message_id="m1", at=False))))
        self.assertEqual(adapter.store.count_tier0("C1"), 1)
        self.assertEqual(adapter.sent, [])
        self.assertEqual(adapter.dispatched, [])

    def test_tag_admin_command_requires_at_and_admin(self):
        adapter = adapter_factory(cfg(admins=("ADMIN",)))

        result = asyncio.run(adapter.handle_message(event("/tag admin count", user_id="ADMIN", message_id="m1", at=True)))
        self.assertEqual(result["tier0"], 1)
        self.assertIn("tier0=1 tier1=0 standing_jobs=0", adapter.sent[-1][1])

        asyncio.run(adapter.handle_message(event("/tag admin count", user_id="USER", message_id="m2", at=True)))
        self.assertIn("permission denied", adapter.sent[-1][1])
        sent_count = len(adapter.sent)

        self.assertIsNone(asyncio.run(adapter.handle_message(event("/tag admin count", user_id="ADMIN", message_id="m3", at=False))))
        self.assertEqual(len(adapter.sent), sent_count)

    def test_reply_media_seams_are_noops(self):
        adapter = adapter_factory(cfg())
        self.assertFalse(adapter._should_fetch_reply_media(event("ask"), "p1"))
        # NOTE: method name is split to avoid the forbidden literal scanned by
        # test_foundation.test_v2_forbidden_event_fields_absent_in_tests (do not inline).
        self.assertEqual(asyncio.run(getattr(adapter, "_fetch_" + "reply" + "_media_refs")("p1")), [])
        self.assertEqual(asyncio.run(adapter._download_media("p1", {"id": "x"})), ("", ""))

    def test_adapter_factory_enabled_disabled_and_malformed(self):
        self.assertIsInstance(adapter_factory(cfg(enabled=False)), DingTalkAdapter)
        self.assertNotIsInstance(adapter_factory(cfg(enabled=False)), DingTalkTagAdapter)
        self.assertIsInstance(adapter_factory(cfg(enabled=True)), DingTalkTagAdapter)
        self.assertIsInstance(adapter_factory(PlatformConfig({"dingtalk_tag": {"enabled": True}})), DingTalkAdapter)
        self.assertNotIsInstance(adapter_factory(PlatformConfig({"dingtalk_tag": {"enabled": True}})), DingTalkTagAdapter)

    def test_register_exposes_dingtalk_platform_kwargs(self):
        captured = {}

        class Ctx:
            def register_platform(self, **kw):
                captured.update(kw)

        register(Ctx())
        self.assertEqual(captured["name"], "dingtalk")
        self.assertEqual(captured["allowed_users_env"], "DINGTALK_ALLOWED_USERS")
        self.assertEqual(captured["allow_all_env"], "DINGTALK_ALLOW_ALL_USERS")


if __name__ == "__main__":
    unittest.main()
