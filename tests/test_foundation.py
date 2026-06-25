import os
import stat
import tempfile
import unittest

from hermes_plugin_feishu import FeishuTagAdapter, FeishuTagConfig, register_plugin


class BaseFeishu:
    def __init__(self):
        self.handled = []

    def handle_message(self, event):
        self.handled.append(event)
        return "handled"

    def send_message(self, chat_id, text):
        return {"chat_id": chat_id, "text": text}


class Registry:
    def __init__(self):
        self.factories = {}

    def register(self, name, factory):
        self.factories[name] = factory


class FoundationTest(unittest.TestCase):
    def cfg(self, **kw):
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.close()
        os.unlink(tmp.name)
        data = {
            "enabled_chats": ["chat-a"],
            "bot_app_id": "cli_test_bot",
            "db_path": tmp.name,
            "granted_scopes": ["im:message"],
            "encryption_posture": "plaintext test db",
        }
        data.update(kw)
        return FeishuTagConfig.from_dict(data)

    def test_registers_feishu_override_factory(self):
        reg = Registry()
        factory = register_plugin(reg, BaseFeishu(), self.cfg())
        self.assertIs(reg.factories["feishu"], factory)
        self.assertIsInstance(factory(), FeishuTagAdapter)

    def test_base_seam_mismatch_fails_loudly(self):
        class BadBase:
            def handle_message(self):
                pass
            def send_message(self, chat_id, text):
                pass
        with self.assertRaisesRegex(RuntimeError, "signature mismatch"):
            FeishuTagAdapter(BadBase(), self.cfg())

        class ExtraArgBase(BaseFeishu):
            def handle_message(self, event, extra):
                return "bad"

        with self.assertRaisesRegex(RuntimeError, "signature mismatch"):
            FeishuTagAdapter(ExtraArgBase(), self.cfg())

    def test_non_enabled_chat_is_dropped_without_processing_or_storage(self):
        base = BaseFeishu()
        adapter = FeishuTagAdapter(base, self.cfg(granted_scopes=["im:message.group_msg"]))
        self.assertIsNone(adapter.handle_message({"chat_id": "other", "message_id": "m1", "text": "secret"}))
        self.assertEqual(base.handled, [])
        self.assertEqual(adapter.store.count_tier0("other"), 0)
        self.assertEqual(adapter.preflight_status()["metrics"]["admission_dropped"], 1)

    def test_without_group_msg_scope_disables_tier0_l2_but_keeps_tier1(self):
        adapter = FeishuTagAdapter(BaseFeishu(), self.cfg(granted_scopes=["im:message"] ))
        caps = adapter.preflight_status()["capabilities"]
        self.assertFalse(caps["tier0_full_ingest"])
        self.assertFalse(caps["l2_context"])
        self.assertTrue(caps["tier1_at_memory"])

    def test_db_is_0600_and_pilot_chat_count_is_enforced(self):
        cfg = self.cfg()
        FeishuTagAdapter(BaseFeishu(), cfg)
        mode = stat.S_IMODE(os.stat(cfg.db_path).st_mode)
        self.assertEqual(mode, 0o600)
        with self.assertRaisesRegex(ValueError, "exactly one"):
            self.cfg(enabled_chats=[])
        with self.assertRaisesRegex(ValueError, "exactly one"):
            self.cfg(enabled_chats=["a", "b"])
        with self.assertRaisesRegex(ValueError, "exactly one"):
            FeishuTagConfig(("a", "b"), "bot", cfg.db_path, frozenset(), "plaintext")

    def test_preflight_exposes_boundary_bot_and_encryption_posture(self):
        status = FeishuTagAdapter(BaseFeishu(), self.cfg()).preflight_status()
        self.assertEqual(status["adapter"], "FeishuTagAdapter")
        self.assertEqual(status["bot_app_id"], "cli_test_bot")
        self.assertEqual(status["enabled_chats"], ["chat-a"])
        self.assertIn("not the receive boundary", status["boundary"])
        self.assertTrue(status["encryption_posture"])


if __name__ == "__main__":
    unittest.main()
