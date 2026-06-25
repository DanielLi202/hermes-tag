import os
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from hermes_plugin_feishu import FeishuTagAdapter, FeishuTagConfig


class BaseFeishu:
    def __init__(self):
        self.handled = []

    def handle_message(self, event):
        event = dict(event)
        event["reply_text"] = f"decision-{event['message_id']}"
        self.handled.append(event)
        return event

    def send_message(self, chat_id, text):
        return {"chat_id": chat_id, "text": text}


def cfg(**kw):
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.close()
    os.unlink(tmp.name)
    data = {
        "enabled_chats": ["chat-a"],
        "bot_app_id": "bot",
        "db_path": tmp.name,
        "media_cache_dir": tmp.name + ".media",
        "granted_scopes": ["im:message.group_msg"],
        "encryption_posture": "plaintext test db",
        "max_context_chars": 500,
        "tier1_max_count": 10,
    }
    data.update(kw)
    return FeishuTagConfig.from_dict(data)


class Tier1MemoryTest(unittest.TestCase):
    def test_later_at_injects_prior_memory_with_owner_and_conclusion(self):
        base = BaseFeishu()
        adapter = FeishuTagAdapter(base, cfg())
        adapter.handle_message({"chat_id": "chat-a", "message_id": "m1", "mentioned": True, "text": "记住 owner", "author": "Alice"})
        second = adapter.handle_message({"chat_id": "chat-a", "message_id": "m2", "mentioned": True, "text": "上次结论？", "author": "Alice"})
        self.assertIn("memory(owner=Alice)", second["context_text"])
        self.assertIn("decision-m1", second["context_text"])

    def test_tier1_provenance_only_mentions_trigger_and_selected_sources(self):
        adapter = FeishuTagAdapter(BaseFeishu(), cfg())
        adapter.handle_message({"chat_id": "chat-a", "message_id": "bob", "mentioned": False, "text": "Bob 无关", "author": "Bob"})
        adapter.handle_message({"chat_id": "chat-a", "message_id": "alice-bg", "mentioned": False, "text": "Alice 背景", "author": "Alice"})
        adapter.handle_message({"chat_id": "chat-a", "message_id": "ask", "mentioned": True, "text": "@bot 继续", "author": "Alice"})
        row = adapter.store.tier1_rows("chat-a")[-1]
        sources = json.loads(row["source_message_ids"])
        self.assertIn("ask", sources)
        self.assertIn("alice-bg", sources)
        self.assertNotIn("bob", sources)

    def test_task_session_id_is_per_request_under_parallel_mentions(self):
        base = BaseFeishu()
        adapter = FeishuTagAdapter(base, cfg())
        events = [
            {"chat_id": "chat-a", "message_id": "m1", "mentioned": True, "text": "one", "author": "Alice"},
            {"chat_id": "chat-a", "message_id": "m2", "mentioned": True, "text": "two", "author": "Bob"},
        ]
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(adapter.handle_message, events))
        sessions = {event["task_session_id"] for event in base.handled}
        self.assertEqual(sessions, {"chat-a:m1", "chat-a:m2"})

    def test_disable_chat_clears_tier1_memory(self):
        adapter = FeishuTagAdapter(BaseFeishu(), cfg())
        adapter.handle_message({"chat_id": "chat-a", "message_id": "m1", "mentioned": True, "text": "记忆", "author": "Alice"})
        self.assertEqual(adapter.store.count_tier1("chat-a"), 1)
        adapter.disable_chat("chat-a")
        self.assertEqual(adapter.store.count_tier1("chat-a"), 0)

    def test_delete_linkage_tombstones_derived_memory(self):
        adapter = FeishuTagAdapter(BaseFeishu(), cfg())
        adapter.handle_message({"chat_id": "chat-a", "message_id": "source", "mentioned": False, "text": "source", "author": "Alice"})
        adapter.handle_message({"chat_id": "chat-a", "message_id": "ask", "mentioned": True, "text": "@bot", "author": "Alice"})
        self.assertEqual(adapter.delete_message("chat-a", "source"), 1)
        self.assertEqual(adapter.store.count_tier1("chat-a"), 0)

    def test_consolidation_caps_count_and_preserves_sources(self):
        adapter = FeishuTagAdapter(BaseFeishu(), cfg(tier1_max_count=2))
        for i in range(4):
            adapter.handle_message({"chat_id": "chat-a", "message_id": f"m{i}", "mentioned": True, "text": f"q{i}", "author": "Alice"})
        rows = adapter.store.tier1_rows("chat-a")
        self.assertLessEqual(len(rows), 2)
        self.assertTrue(any("consolidated:" in row["summary"] for row in rows))
        self.assertTrue(all(json.loads(row["source_message_ids"]) for row in rows))

    def test_budget_drops_tier1_before_l2_background(self):
        adapter = FeishuTagAdapter(BaseFeishu(), cfg(max_context_chars=55))
        adapter.handle_message({"chat_id": "chat-a", "message_id": "mem", "mentioned": True, "text": "M" * 20, "author": "Alice"})
        adapter.handle_message({"chat_id": "chat-a", "message_id": "bg", "mentioned": False, "text": "short-bg", "author": "Alice"})
        out = adapter.handle_message({"chat_id": "chat-a", "message_id": "ask", "mentioned": True, "text": "now", "author": "Alice"})
        self.assertIn("Alice: short-bg", out["context_text"])
        self.assertNotIn("memory(owner=Alice)", out["context_text"])


if __name__ == "__main__":
    unittest.main()
