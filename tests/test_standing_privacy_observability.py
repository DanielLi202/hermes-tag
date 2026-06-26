import asyncio
import inspect
import os
import tempfile
import unittest
from types import SimpleNamespace

os.environ.setdefault("HERMES_PLUGIN_FEISHU_USE_STUBS", "1")

from hermes_tag import FeishuTagAdapter, FeishuTagConfig, MessageEvent, PlatformConfig


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

class SessionStore:
    def __init__(self):
        self.reset=[]
        self._entries={"session-key": SimpleNamespace(session_id="old-session")}
    def _generate_session_key(self, source): return "session-key"
    def reset_session(self, session_key):
        self.reset.append(session_key)
        entry=SimpleNamespace(session_id="new-session")
        self._entries[session_key]=entry
        return entry

class Runner:
    def __init__(self):
        self.session_store=SessionStore()
        self.cleared=[]
        self._queued_events={}
        self._session_model_overrides={}
        self._pending_model_notes={}
    def _session_key_for_source(self, source): return "session-key"
    def _invalidate_session_run_generation(self, session_key, reason=None): self.cleared.append(("generation",session_key,reason))
    def _release_running_agent_state(self, session_key): self.cleared.append(("running",session_key))
    def _evict_cached_agent(self, session_key): self.cleared.append(("cache",session_key))
    def _clear_session_boundary_security_state(self, session_key): self.cleared.append(("security",session_key))
    def _set_session_reasoning_override(self, session_key, value): self.cleared.append(("reasoning",session_key,value))
    async def handle(self, event): return "unused"

class StandingPrivacyV2Test(unittest.TestCase):
    def adapter(self, **kw):
        cron=CronAPI(); return FeishuTagAdapter(PlatformConfig(), cfg(**kw), cron), cron

    def test_chitchat_does_not_create_standing_job(self):
        a,cron=self.adapter()
        asyncio.run(a._dispatch_inbound_event(ev("每周五总结会不会太晚", at=False)))
        self.assertEqual(a.store.count_standing_jobs("chat-a"),0); self.assertEqual(cron.created,[])

    def test_explicit_standing_confirmation_then_list_cancel_by_id(self):
        a,cron=self.adapter()
        pending=asyncio.run(a._dispatch_inbound_event(ev("/tag standing add weekly-Friday-10:00 Asia/Shanghai 总结","s1")))
        self.assertTrue(pending["confirmation_required"]); self.assertEqual(a.store.count_standing_jobs("chat-a"),0)
        self.assertEqual(a.sent[-1], ("chat-a", "confirmation_required schedule=0 10 * * 5"))
        made=asyncio.run(a._dispatch_inbound_event(ev("/tag standing confirm","s2")))
        job_id=made["created"]
        self.assertEqual(cron.created[0][3],"0 10 * * 5")
        listed=asyncio.run(a._dispatch_inbound_event(ev("/tag standing list","s3")))
        self.assertEqual(listed["jobs"][0]["id"],job_id)
        cancelled=asyncio.run(a._dispatch_inbound_event(ev(f"/tag standing cancel {job_id}","s4")))
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
        self.assertEqual(asyncio.run(a._dispatch_inbound_event(ev("/tag admin count",user="Bob")))["error"],"permission denied")
        self.assertEqual(a.sent[-1], ("chat-a", "error: permission denied"))
        self.assertEqual(asyncio.run(a._dispatch_inbound_event(ev("/tag standing add weekly-Friday-10:00 Asia/Shanghai 总结",user="Bob")))["error"],"permission denied")
        self.assertEqual(a.sent[-1], ("chat-a", "error: permission denied"))

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
        counts=asyncio.run(a._dispatch_inbound_event(ev("/tag admin count","c")))
        self.assertEqual(counts["tier0"],a.store.count_tier0("chat-a"))
        self.assertEqual(a.sent[-1], ("chat-a", f"tier0={counts['tier0']} tier1={counts['tier1']} standing_jobs={counts['standing_jobs']}"))
        self.assertEqual(set(a.retention_table()),{"Tier-0","Tier-1","media","cron"})
        status=a.preflight_status()
        for key in ["admission_dropped","tier0_rows","tier0_evicted","tier1_memories","tier1_write_failure","command_send_failure","media_download_success","media_download_failure","degraded_no_group_msg","override_selfcheck_ok","standing_jobs"]:
            self.assertIn(key,status["metrics"])
        runner=Runner(); a._message_handler=runner.handle
        asyncio.run(a._dispatch_inbound_event(ev("/tag admin clear","clear")))
        self.assertEqual(a.sent[-1], ("chat-a", "cleared; session reset"))
        self.assertEqual(a.store.count_tier0("chat-a"),0)

    def test_admin_clear_resets_gateway_session_store(self):
        a,_=self.adapter()
        runner=Runner(); a._message_handler=runner.handle
        result=asyncio.run(a._dispatch_inbound_event(ev("/tag admin clear","clear")))
        self.assertTrue(result["cleared"])
        self.assertTrue(result["session_reset"])
        self.assertEqual(runner.session_store.reset, ["session-key"])
        self.assertIn(("cache","session-key"), runner.cleared)
        self.assertTrue(any(r["event"]=="hermes_session_reset" for r in a.store.audit_events("chat-a")))

    def test_group_tag_command_requires_mention(self):
        a,_=self.adapter()
        self.assertIsNone(asyncio.run(a._dispatch_inbound_event(ev("/tag admin count","no-at",at=False))))
        self.assertEqual(a.sent, [])
        self.assertEqual(a.store.count_tier0("chat-a"),1)

    def test_tag_help_status_and_legacy_aliases(self):
        a,_=self.adapter()
        help_result=asyncio.run(a._dispatch_inbound_event(ev("/tag help","help")))
        self.assertIn("/tag admin count", help_result["help"])
        self.assertTrue(a.sent[-1][1].startswith("tag commands:"))
        status=asyncio.run(a._dispatch_inbound_event(ev("/tag status","status")))
        self.assertEqual(status["status"]["adapter"],"FeishuTagAdapter")
        self.assertIn("metrics", a.sent[-1][1])
        legacy=asyncio.run(a._dispatch_inbound_event(ev("/admin count","legacy")))
        self.assertIn("tier0", legacy)

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
        import hermes_tag.adapter as m
        src=inspect.getsource(m.FeishuTagAdapter)
        self.assertEqual(src.count("def disable_chat"),1)
        self.assertNotIn("next" + "_weekly" + "_fire",src)

if __name__ == "__main__": unittest.main()
