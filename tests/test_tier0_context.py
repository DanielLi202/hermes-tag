import os
import tempfile
import unittest

from hermes_plugin_feishu import FeishuTagAdapter, FeishuTagConfig


class BaseFeishu:
    def __init__(self):
        self.handled = []
        self.parents = {}
        self.fail = set()

    def handle_message(self, event):
        self.handled.append(event)
        return event

    def send_message(self, chat_id, text):
        return {"chat_id": chat_id, "text": text}

    def fetch_message(self, message_id):
        return self.parents[message_id]

    def download_image(self, key):
        if key in self.fail:
            raise RuntimeError("download failed")
        return b"image-bytes"

    def download_resource(self, message_id, key, media_type):
        if key in self.fail:
            raise RuntimeError("download failed")
        return b"file-bytes"


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
        "max_context_chars": 80,
        "tier0_ttl_seconds": 86400,
        "tier0_max_count": 99,
    }
    data.update(kw)
    return FeishuTagConfig.from_dict(data)


class Tier0ContextTest(unittest.TestCase):
    def test_at_reply_image_and_file_become_media_urls_for_native_vision(self):
        base = BaseFeishu()
        base.parents["p1"] = {"attachments": [{"kind": "image", "key": "img1"}, {"kind": "file", "key": "f1", "resource_type": "file"}]}
        out = FeishuTagAdapter(base, cfg()).handle_message({"chat_id": "chat-a", "message_id": "m1", "parent_id": "p1", "mentioned": True, "text": "看图", "author": "Alice"})
        self.assertEqual(len(out["media_urls"]), 2)
        self.assertEqual(out["media_types"], ["image", "file"])
        self.assertTrue(out["uses_native_vision"])

    def test_media_download_failure_adds_placeholder_and_continues(self):
        base = BaseFeishu()
        base.fail.add("img1")
        base.parents["p1"] = {"attachments": [{"kind": "image", "key": "img1"}]}
        out = FeishuTagAdapter(base, cfg()).handle_message({"chat_id": "chat-a", "message_id": "m1", "parent_id": "p1", "mentioned": True, "text": "看图", "author": "Alice"})
        self.assertIn("[media unavailable: img1]", out["context_text"])
        self.assertEqual(base.handled[-1]["message_id"], "m1")

    def test_unmentioned_ingests_tier0_but_never_invokes_agent(self):
        base = BaseFeishu()
        adapter = FeishuTagAdapter(base, cfg())
        self.assertIsNone(adapter.handle_message({"chat_id": "chat-a", "message_id": "m1", "mentioned": False, "text": "背景", "author": "Alice"}))
        self.assertEqual(adapter.store.count_tier0("chat-a"), 1)
        self.assertEqual(base.handled, [])

    def test_duplicate_message_id_is_idempotent(self):
        adapter = FeishuTagAdapter(BaseFeishu(), cfg())
        event = {"chat_id": "chat-a", "message_id": "m1", "mentioned": False, "text": "背景", "author": "Alice"}
        adapter.handle_message(event)
        adapter.handle_message(event)
        self.assertEqual(adapter.store.count_tier0("chat-a"), 1)

    def test_l2_selects_relevant_author_tagged_context_not_unrelated_bob(self):
        base = BaseFeishu()
        adapter = FeishuTagAdapter(base, cfg())
        adapter.handle_message({"chat_id": "chat-a", "message_id": "b1", "mentioned": False, "text": "Bob 无关", "author": "Bob"})
        adapter.handle_message({"chat_id": "chat-a", "message_id": "a1", "mentioned": False, "text": "Alice 铺垫", "author": "Alice"})
        out = adapter.handle_message({"chat_id": "chat-a", "message_id": "a2", "mentioned": True, "text": "@bot 那个截图", "author": "Alice"})
        self.assertIn("Alice: Alice 铺垫", out["context_text"])
        self.assertNotIn("Bob 无关", out["context_text"])

    def test_budget_keeps_current_and_media_placeholder_before_background(self):
        base = BaseFeishu()
        base.fail.add("img1")
        base.parents["p1"] = {"attachments": [{"kind": "image", "key": "img1"}]}
        adapter = FeishuTagAdapter(base, cfg(max_context_chars=55))
        adapter.handle_message({"chat_id": "chat-a", "message_id": "a1", "mentioned": False, "text": "很长背景" * 50, "author": "Alice"})
        out = adapter.handle_message({"chat_id": "chat-a", "message_id": "a2", "parent_id": "p1", "mentioned": True, "text": "当前消息", "author": "Alice"})
        self.assertIn("current: 当前消息", out["context_text"])
        self.assertIn("[media unavailable: img1]", out["context_text"])

    def test_tier0_eviction_physically_deletes_rows_and_media(self):
        adapter = FeishuTagAdapter(BaseFeishu(), cfg(tier0_ttl_seconds=1))
        media = os.path.join(adapter.media_cache_dir, "old.bin")
        os.makedirs(adapter.media_cache_dir, exist_ok=True)
        with open(media, "wb") as f:
            f.write(b"x")
        adapter.store.insert_tier0({"chat_id": "chat-a", "message_id": "old", "text": "old", "created_at": 1}, [media])
        self.assertEqual(adapter.store.evict_tier0("chat-a", ttl_seconds=1, max_count=99), 1)
        self.assertEqual(adapter.store.count_tier0("chat-a"), 0)
        self.assertFalse(os.path.exists(media))
        self.assertEqual(adapter.store.metric("tier0_evicted"), 1)

    def test_successful_l1_media_is_linked_to_tier0_and_evicted(self):
        base = BaseFeishu()
        base.parents["p1"] = {"attachments": [{"kind": "image", "key": "img1"}]}
        adapter = FeishuTagAdapter(base, cfg(tier0_ttl_seconds=1))
        out = adapter.handle_message({"chat_id": "chat-a", "message_id": "m1", "parent_id": "p1", "mentioned": True, "text": "看图", "author": "Alice"})
        path = out["media_urls"][0].removeprefix("file://")
        self.assertTrue(os.path.exists(path))
        adapter.store.conn.execute("UPDATE tier0_messages SET created_at=1 WHERE message_id='m1'")
        adapter.store.conn.commit()
        self.assertEqual(adapter.store.evict_tier0("chat-a", ttl_seconds=1, max_count=99), 1)
        self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
