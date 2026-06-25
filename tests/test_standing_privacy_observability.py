import os
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from hermes_plugin_feishu import FeishuTagAdapter, FeishuTagConfig


class BaseFeishu:
    def __init__(self):
        self.handled = []
        self.sent = []
        self.crons = []
        self.unregistered = []

    def handle_message(self, event):
        self.handled.append(event)
        return event

    def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))
        return {"chat_id": chat_id, "text": text}

    def register_cron(self, chat_id, schedule, timezone, description):
        cron_id = f"cron-{len(self.crons)+1}"
        self.crons.append((cron_id, chat_id, schedule, timezone, description))
        return cron_id

    def unregister_cron(self, cron_job_id):
        self.unregistered.append(cron_job_id)


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
        "admins": ["Alice"],
    }
    data.update(kw)
    return FeishuTagConfig.from_dict(data)


class StandingPrivacyObservabilityTest(unittest.TestCase):
    def adapter(self):
        base = BaseFeishu()
        return FeishuTagAdapter(base, cfg()), base

    def test_chitchat_does_not_create_standing_job(self):
        adapter, base = self.adapter()
        adapter.handle_message({"chat_id": "chat-a", "message_id": "m1", "mentioned": True, "text": "每周五总结会不会太晚", "author": "Alice"})
        self.assertEqual(adapter.store.count_standing_jobs("chat-a"), 0)
        self.assertEqual(base.crons, [])

    def test_explicit_standing_needs_confirmation_then_lists_and_cancels_by_id(self):
        adapter, base = self.adapter()
        pending = adapter.handle_message({"chat_id": "chat-a", "message_id": "m1", "mentioned": True, "text": "/standing add weekly-Friday-10:00 Asia/Shanghai 总结", "author": "Alice"})
        self.assertTrue(pending["confirmation_required"])
        self.assertEqual(adapter.store.count_standing_jobs("chat-a"), 0)
        made = adapter.handle_message({"chat_id": "chat-a", "message_id": "m2", "mentioned": True, "text": "/standing confirm", "author": "Alice"})
        job_id = made["created"]
        self.assertEqual(adapter.store.count_standing_jobs("chat-a"), 1)
        listed = adapter.handle_message({"chat_id": "chat-a", "message_id": "m3", "mentioned": True, "text": "/standing list", "author": "Alice"})
        self.assertEqual(listed["jobs"][0]["id"], job_id)
        cancelled = adapter.handle_message({"chat_id": "chat-a", "message_id": "m4", "mentioned": True, "text": f"/standing cancel {job_id}", "author": "Alice"})
        self.assertTrue(cancelled["cancelled"])
        self.assertEqual(base.unregistered, ["cron-1"])

    def test_standing_trigger_posts_to_scoped_chat_and_pause_disables_trigger(self):
        adapter, base = self.adapter()
        adapter.handle_message({"chat_id": "chat-a", "message_id": "m1", "mentioned": True, "text": "/standing add weekly-Friday-10:00 Asia/Shanghai 总结", "author": "Alice"})
        job_id = adapter.handle_message({"chat_id": "chat-a", "message_id": "m2", "mentioned": True, "text": "/standing confirm", "author": "Alice"})["created"]
        self.assertEqual(adapter.trigger_standing_job(job_id)["sent"]["chat_id"], "chat-a")
        adapter.handle_message({"chat_id": "chat-a", "message_id": "m3", "mentioned": True, "text": f"/standing pause {job_id}", "author": "Alice"})
        self.assertIsNone(adapter.trigger_standing_job(job_id))
        adapter.handle_message({"chat_id": "chat-a", "message_id": "m4", "mentioned": True, "text": f"/standing enable {job_id}", "author": "Alice"})
        self.assertIsNotNone(adapter.trigger_standing_job(job_id))

    def test_non_admin_cannot_manage_standing_or_admin_commands(self):
        adapter, _ = self.adapter()
        denied = adapter.handle_message({"chat_id": "chat-a", "message_id": "m1", "mentioned": True, "text": "/standing add weekly-Friday-10:00 Asia/Shanghai 总结", "author": "Bob"})
        self.assertEqual(denied["error"], "permission denied")
        denied_admin = adapter.handle_message({"chat_id": "chat-a", "message_id": "m2", "mentioned": True, "text": "/admin count", "author": "Bob"})
        self.assertEqual(denied_admin["error"], "permission denied")

    def test_weekly_time_fixture_keeps_local_hour_across_dst(self):
        before = datetime(2026, 3, 6, 12, tzinfo=ZoneInfo("UTC"))
        fire = FeishuTagAdapter.next_weekly_fire("weekly Friday 10:00", "America/New_York", before)
        self.assertEqual((fire.weekday(), fire.hour, fire.minute), (4, 10, 0))
        after = datetime(2026, 3, 9, 12, tzinfo=ZoneInfo("UTC"))
        fire2 = FeishuTagAdapter.next_weekly_fire("weekly Friday 10:00", "America/New_York", after)
        self.assertEqual((fire2.weekday(), fire2.hour, fire2.minute), (4, 10, 0))

    def test_enable_notice_content_and_audit(self):
        adapter, base = self.adapter()
        notice = adapter.enable_chat("chat-a")
        self.assertEqual(base.sent[-1], ("chat-a", notice))
        self.assertIn("所有消息", notice)
        self.assertIn("@ bot 时相关消息才可能进入模型", notice)
        self.assertIn("长期记忆仅来自 @ 交互", notice)
        self.assertTrue(any(row["event"] == "enable_chat" for row in adapter.store.audit_events("chat-a")))

    def test_disable_cascades_tier0_tier1_media_and_cron(self):
        adapter, base = self.adapter()
        media = os.path.join(adapter.media_cache_dir, "m.bin")
        os.makedirs(adapter.media_cache_dir, exist_ok=True)
        with open(media, "wb") as f:
            f.write(b"x")
        adapter.store.insert_tier0({"chat_id": "chat-a", "message_id": "t0", "text": "x"}, [media])
        adapter.handle_message({"chat_id": "chat-a", "message_id": "mem", "mentioned": True, "text": "记忆", "author": "Alice"})
        adapter.handle_message({"chat_id": "chat-a", "message_id": "s1", "mentioned": True, "text": "/standing add weekly-Friday-10:00 Asia/Shanghai 总结", "author": "Alice"})
        adapter.handle_message({"chat_id": "chat-a", "message_id": "s2", "mentioned": True, "text": "/standing confirm", "author": "Alice"})
        adapter.disable_chat("chat-a")
        self.assertEqual(adapter.store.count_tier0("chat-a"), 0)
        self.assertEqual(adapter.store.count_tier1("chat-a"), 0)
        self.assertFalse(os.path.exists(media))
        self.assertEqual(base.unregistered, ["cron-1"])

    def test_admin_count_clear_retention_and_observability(self):
        adapter, _ = self.adapter()
        adapter.handle_message({"chat_id": "chat-a", "message_id": "t0", "mentioned": False, "text": "x", "author": "Alice"})
        counts = adapter.handle_message({"chat_id": "chat-a", "message_id": "c", "mentioned": True, "text": "/admin count", "author": "Alice"})
        self.assertEqual(counts["tier0"], adapter.store.count_tier0("chat-a"))
        table = adapter.retention_table()
        self.assertEqual(set(table), {"Tier-0", "Tier-1", "media", "cron"})
        status = adapter.preflight_status()
        for key in ["admission_dropped", "tier0_rows", "tier0_evicted", "tier1_memories", "tier1_write_failure", "media_download_success", "media_download_failure", "degraded_no_group_msg", "override_selfcheck_ok", "standing_jobs"]:
            self.assertIn(key, status["metrics"])
        adapter.handle_message({"chat_id": "chat-a", "message_id": "clear", "mentioned": True, "text": "/admin clear", "author": "Alice"})
        self.assertEqual(adapter.store.count_tier0("chat-a"), 0)
        self.assertTrue(any(row["event"] == "admin_clear" for row in adapter.store.audit_events("chat-a")))

    def test_no_secret_or_full_sensitive_body_in_audit(self):
        adapter, _ = self.adapter()
        adapter.handle_message({"chat_id": "chat-a", "message_id": "t0", "mentioned": False, "text": "SECRET_TOKEN full body", "author": "Alice"})
        audit_text = "\n".join(row["detail"] for row in adapter.store.audit_events())
        self.assertNotIn("SECRET_TOKEN full body", audit_text)

    def test_tier1_write_failure_metric_is_queryable_and_fixture_updatable(self):
        adapter, _ = self.adapter()
        def fail_write(*args, **kwargs):
            raise RuntimeError("boom")
        adapter.store.write_tier1 = fail_write
        adapter.handle_message({"chat_id": "chat-a", "message_id": "m", "mentioned": True, "text": "q", "author": "Alice"})
        self.assertEqual(adapter.preflight_status()["metrics"]["tier1_write_failure"], 1)


if __name__ == "__main__":
    unittest.main()
