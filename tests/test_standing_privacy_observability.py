import asyncio
import inspect
import os
import tempfile
import unittest
from types import SimpleNamespace

from hermes_plugin_feishu import FeishuTagAdapter, FeishuTagConfig, MessageEvent, PlatformConfig


def source(chat="chat-a", user="Alice"):
    return SimpleNamespace(chat_id=chat, user_id=user, user_name=user, thread_id=None)

def raw(at=True):
    return {"mentions": [{"id": {"open_id": "bot-open"}}] if at else []}

def cfg(**kw):
    tmp=tempfile.NamedTemporaryFile(delete=False); tmp.close(); os.unlink(tmp.name)
    data={"enabled_chats":["chat-a"],"bot_open_id":"bot-open","db_path":tmp.name,"media_cache_dir":tmp.name+".media","granted_scopes":["im:message.group_msg"],"encryption_posture":"plain","admins":["Alice"]}
    data.update(kw); return FeishuTagConfig.from_platform_config(data)

def ev(text, mid="m", user="Alice", at=True):
    return MessageEvent(text, source=source(user=user), raw_message=raw(at), message_id=mid)

def send_reply(adapter, mid, content, chat="chat-a"):
    return asyncio.run(adapter.send(chat, content, metadata={"task_session_id": f"{chat}:{mid}"}))

class CronAPI:
    def __init__(self): self.created=[]; self.cancelled=[]; self.paused=[]; self.enabled=[]
    def create(self, *, chat_id, description, schedule, timezone_name):
        cid=f"cron-{len(self.created)+1}"; self.created.append((cid,chat_id,description,schedule,timezone_name)); return cid
    def cancel(self, job_id): self.cancelled.append(job_id)
    def pause(self, job_id): self.paused.append(job_id)
    def enable(self, job_id): self.enabled.append(job_id)

class StandingPrivacyV2Test(unittest.TestCase):
    def adapter(self, **kw):
        cron=CronAPI(); return FeishuTagAdapter(PlatformConfig(), cfg(**kw), cron), cron

    def test_chitchat_does_not_create_standing_job(self):
        a,cron=self.adapter()
        asyncio.run(a._dispatch_inbound_event(ev("每周五总结会不会太晚", at=False)))
        self.assertEqual(a.store.count_standing_jobs("chat-a"),0); self.assertEqual(cron.created,[])

    def test_explicit_standing_confirmation_then_list_cancel_by_id(self):
        a,cron=self.adapter()
        pending=asyncio.run(a._dispatch_inbound_event(ev("/standing add weekly-Friday-10:00 Asia/Shanghai 总结","s1")))
        self.assertTrue(pending["confirmation_required"]); self.assertEqual(a.store.count_standing_jobs("chat-a"),0)
        made=asyncio.run(a._dispatch_inbound_event(ev("/standing confirm","s2")))
        job_id=made["created"]
        self.assertEqual(cron.created[0][3],"0 10 * * 5")
        listed=asyncio.run(a._dispatch_inbound_event(ev("/standing list","s3")))
        self.assertEqual(listed["jobs"][0]["id"],job_id)
        cancelled=asyncio.run(a._dispatch_inbound_event(ev(f"/standing cancel {job_id}","s4")))
        self.assertTrue(cancelled["cancelled"]); self.assertEqual(cron.cancelled,["cron-1"])

    def test_standing_trigger_scoped_and_pause_enable_updates_cron(self):
        a,cron=self.adapter()
        asyncio.run(a._dispatch_inbound_event(ev("/standing add weekly-Friday-10:00 Asia/Shanghai 总结","s1")))
        job_id=asyncio.run(a._dispatch_inbound_event(ev("/standing confirm","s2")))["created"]
        self.assertEqual(asyncio.run(a.trigger_standing_job(job_id))["sent"]["chat_id"],"chat-a")
        asyncio.run(a._dispatch_inbound_event(ev(f"/standing pause {job_id}","s3")))
        self.assertIsNone(asyncio.run(a.trigger_standing_job(job_id))); self.assertEqual(cron.paused,["cron-1"])
        asyncio.run(a._dispatch_inbound_event(ev(f"/standing enable {job_id}","s4")))
        self.assertIsNotNone(asyncio.run(a.trigger_standing_job(job_id))); self.assertEqual(cron.enabled,["cron-1"])

    def test_admin_and_standing_fail_closed_when_admins_unconfigured(self):
        a,_=self.adapter(admins=[])
        self.assertEqual(asyncio.run(a._dispatch_inbound_event(ev("/admin clear")))["error"],"permission denied")
        self.assertEqual(asyncio.run(a._dispatch_inbound_event(ev("/admin disable")))["error"],"permission denied")
        self.assertEqual(asyncio.run(a._dispatch_inbound_event(ev("/standing add weekly-Friday-10:00 Asia/Shanghai 总结")))["error"],"permission denied")

    def test_non_admin_cannot_manage(self):
        a,_=self.adapter()
        self.assertEqual(asyncio.run(a._dispatch_inbound_event(ev("/admin count",user="Bob")))["error"],"permission denied")
        self.assertEqual(asyncio.run(a._dispatch_inbound_event(ev("/standing add weekly-Friday-10:00 Asia/Shanghai 总结",user="Bob")))["error"],"permission denied")

    def test_disable_cascades_tier0_tier1_media_and_cron(self):
        a,cron=self.adapter()
        media=a.media_cache_dir/"m.bin"; media.write_bytes(b"x")
        a.store.insert_tier0(chat_id="chat-a",message_id="t0",text="x",author="Alice",thread_id=None,media_paths=[str(media)])
        asyncio.run(a._dispatch_inbound_event(ev("remember","mem"))); send_reply(a, "mem", "answer")
        asyncio.run(a._dispatch_inbound_event(ev("/standing add weekly-Friday-10:00 Asia/Shanghai 总结","s1")))
        asyncio.run(a._dispatch_inbound_event(ev("/standing confirm","s2")))
        a.disable_chat("chat-a")
        self.assertEqual(a.store.count_tier0("chat-a"),0); self.assertEqual(a.store.count_tier1("chat-a"),0)
        self.assertFalse(media.exists()); self.assertEqual(cron.cancelled,["cron-1"])

    def test_enable_notice_content_and_audit_uses_async_send(self):
        a,_=self.adapter()
        notice=asyncio.run(a.enable_chat("chat-a"))
        self.assertEqual(a.sent[-1], ("chat-a", notice))
        self.assertIn("所有消息",notice); self.assertIn("@ bot 时相关消息才可能进入模型",notice); self.assertIn("长期记忆仅来自 @ 交互",notice)
        self.assertTrue(any(r["event"]=="enable_chat" for r in a.store.audit_events("chat-a")))

    def test_admin_count_clear_retention_and_observability(self):
        a,_=self.adapter()
        asyncio.run(a._dispatch_inbound_event(ev("bg","b",at=False)))
        counts=asyncio.run(a._dispatch_inbound_event(ev("/admin count","c")))
        self.assertEqual(counts["tier0"],a.store.count_tier0("chat-a"))
        self.assertEqual(set(a.retention_table()),{"Tier-0","Tier-1","media","cron"})
        status=a.preflight_status()
        for key in ["admission_dropped","tier0_rows","tier0_evicted","tier1_memories","tier1_write_failure","media_download_success","media_download_failure","degraded_no_group_msg","override_selfcheck_ok","standing_jobs"]:
            self.assertIn(key,status["metrics"])
        asyncio.run(a._dispatch_inbound_event(ev("/admin clear","clear")))
        self.assertEqual(a.store.count_tier0("chat-a"),0)

    def test_tier1_write_failure_metric_is_updatable(self):
        a,_=self.adapter()
        def fail(*args, **kw): raise RuntimeError("boom")
        a.store.write_tier1=fail
        asyncio.run(a._dispatch_inbound_event(ev("q","m"))); send_reply(a, "m", "answer")
        self.assertEqual(a.preflight_status()["metrics"]["tier1_write_failure"],1)

    def test_no_full_sensitive_body_in_audit(self):
        a,_=self.adapter()
        asyncio.run(a._dispatch_inbound_event(ev("SECRET_TOKEN full body","t",at=False)))
        audit="\n".join(r["detail"] for r in a.store.audit_events())
        self.assertNotIn("SECRET_TOKEN full body",audit)

    def test_no_duplicate_disable_or_detached_weekly_helper(self):
        import hermes_plugin_feishu.adapter as m
        src=inspect.getsource(m.FeishuTagAdapter)
        self.assertEqual(src.count("def disable_chat"),1)
        self.assertNotIn("next" + "_weekly" + "_fire",src)

if __name__ == "__main__": unittest.main()
