import asyncio
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

os.environ.setdefault("HERMES_PLUGIN_FEISHU_USE_STUBS", "1")

import hermes_tag.adapter as adapter_mod
from hermes_tag import FeishuTagAdapter, FeishuTagConfig, MessageEvent, PlatformConfig


def source(chat="chat-a", user="Alice"):
    return SimpleNamespace(chat_id=chat, user_id=user, user_name=user, thread_id=None)

def raw(at=False):
    return {"mentions": [{"id": {"open_id": "bot-open"}}] if at else []}

def cfg(**kw):
    tmp=tempfile.NamedTemporaryFile(delete=False); tmp.close(); os.unlink(tmp.name)
    data={"enabled_chats":["chat-a"],"bot_open_id":"bot-open","db_path":tmp.name,"media_cache_dir":tmp.name+".media","granted_scopes":["im:message.group_msg"],"encryption_posture":"plain","admins":["Alice"],"tier1_max_count":10,"max_context_chars":500}
    data.update(kw); return FeishuTagConfig.from_platform_config(data)

def ev(text, mid, user="Alice", at=True):
    return MessageEvent(text, source=source(user=user), raw_message=raw(at), message_id=mid)

def send_reply(adapter, mid, content, chat="chat-a"):
    return asyncio.run(adapter.send(chat, content, metadata={"response_correlation_key": f"{chat}:{mid}"}))

class CronAPI:
    def __init__(self):
        self.created=[]; self.cancelled=[]; self.paused=[]; self.enabled=[]
    def create(self, *, chat_id, description, schedule, timezone_name):
        cid=f"cron-{len(self.created)+1}"; self.created.append((cid,chat_id,description,schedule,timezone_name)); return cid
    def cancel(self, job_id): self.cancelled.append(job_id)
    def pause(self, job_id): self.paused.append(job_id)
    def enable(self, job_id): self.enabled.append(job_id)

class Tier1V2Test(unittest.TestCase):
    def test_response_send_writes_tier1_conclusion_not_dispatch_return(self):
        a=FeishuTagAdapter(PlatformConfig(), cfg())
        self.assertIsNone(asyncio.run(a._dispatch_inbound_event(ev("remember","m1"))))
        self.assertEqual(a.store.count_tier1("chat-a"),0)
        asyncio.run(a.send("chat-a", "unrelated bot self-send"))
        self.assertEqual(a.store.count_tier1("chat-a"),0)
        send_reply(a, "m1", "real response m1")
        row=a.store.tier1_rows("chat-a")[-1]
        self.assertIn("real response m1", row["summary"])

    def test_later_at_injects_prior_memory_with_owner_and_conclusion(self):
        a=FeishuTagAdapter(PlatformConfig(), cfg())
        asyncio.run(a._dispatch_inbound_event(ev("remember", "m1")))
        send_reply(a, "m1", "decision-m1")
        asyncio.run(a._dispatch_inbound_event(ev("recall", "m2")))
        self.assertIn("memory(owner=Alice)", a.dispatched[-1].channel_context)
        self.assertIn("decision-m1", a.dispatched[-1].channel_context)

    def test_tier1_provenance_excludes_unselected_unrelated_message(self):
        a=FeishuTagAdapter(PlatformConfig(), cfg())
        asyncio.run(a._dispatch_inbound_event(ev("Bob unrelated","bob",user="Bob",at=False)))
        asyncio.run(a._dispatch_inbound_event(ev("Alice setup","alice-bg",at=False)))
        asyncio.run(a._dispatch_inbound_event(ev("ask","ask")))
        send_reply(a, "ask", "answer")
        sources=json.loads(a.store.tier1_rows("chat-a")[-1]["source_message_ids"])
        self.assertIn("ask",sources); self.assertIn("alice-bg",sources); self.assertNotIn("bob",sources)

    def test_task_session_id_per_request_under_parallel_mentions(self):
        a=FeishuTagAdapter(PlatformConfig(), cfg())
        def run(e): asyncio.run(a._dispatch_inbound_event(e))
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(run, [ev("one","m1"), ev("two","m2",user="Bob")]))
        self.assertEqual({getattr(o,"task_session_id") for o in a.dispatched}, {"chat-a:m1","chat-a:m2"})

    def test_model_dispatch_not_inside_store_lock(self):
        original=adapter_mod.FeishuAdapter._dispatch_inbound_event
        started=__import__("threading").Event()
        async def slow(self,event):
            started.set(); await asyncio.sleep(0.2); self.dispatched.append(event); return None
        adapter_mod.FeishuAdapter._dispatch_inbound_event=slow
        try:
            a=FeishuTagAdapter(PlatformConfig(), cfg())
            async def scenario():
                t1=asyncio.create_task(a._dispatch_inbound_event(ev("slow","m1")))
                await asyncio.to_thread(started.wait)
                await asyncio.wait_for(a._dispatch_inbound_event(ev("bg","m2",at=False)), timeout=0.05)
                await t1
            asyncio.run(scenario())
            self.assertEqual(a.store.count_tier0("chat-a"),2)
        finally:
            adapter_mod.FeishuAdapter._dispatch_inbound_event=original

    def test_disable_chat_clears_tier1_memory(self):
        a=FeishuTagAdapter(PlatformConfig(), cfg())
        asyncio.run(a._dispatch_inbound_event(ev("remember","m1"))); send_reply(a, "m1", "answer")
        a.disable_chat("chat-a")
        self.assertEqual(a.store.count_tier1("chat-a"),0)

    def test_delete_linkage_tombstones_derived_memory(self):
        a=FeishuTagAdapter(PlatformConfig(), cfg())
        asyncio.run(a._dispatch_inbound_event(ev("source","source",at=False)))
        asyncio.run(a._dispatch_inbound_event(ev("ask","ask"))); send_reply(a, "ask", "answer")
        self.assertEqual(a.delete_message("chat-a","source"),1)
        self.assertEqual(a.store.count_tier1("chat-a"),0)

    def test_consolidation_caps_count_and_preserves_sources(self):
        a=FeishuTagAdapter(PlatformConfig(), cfg(tier1_max_count=2))
        for i in range(4):
            asyncio.run(a._dispatch_inbound_event(ev(f"q{i}",f"m{i}"))); send_reply(a, f"m{i}", f"answer{i}")
        rows=a.store.tier1_rows("chat-a")
        self.assertLessEqual(len(rows),2)
        self.assertTrue(all(json.loads(r["source_message_ids"]) for r in rows))

    def test_budget_drops_tier1_before_l2_background(self):
        a=FeishuTagAdapter(PlatformConfig(), cfg(max_context_chars=55))
        asyncio.run(a._dispatch_inbound_event(ev("memory","mem"))); send_reply(a, "mem", "answer")
        asyncio.run(a._dispatch_inbound_event(ev("short-bg","bg",at=False)))
        asyncio.run(a._dispatch_inbound_event(ev("now","ask")))
        self.assertIn("Alice: short-bg", a.dispatched[-1].channel_context)
        self.assertNotIn("memory(owner=Alice)", a.dispatched[-1].channel_context)

    def test_standing_trigger_does_not_consume_pending_tier1(self):
        cron=CronAPI()
        a=FeishuTagAdapter(PlatformConfig(), cfg(), cron)
        asyncio.run(a._dispatch_inbound_event(ev("remember","m1")))
        asyncio.run(a._dispatch_inbound_event(ev("/standing add weekly-Friday-10:00 Asia/Shanghai 总结","s1")))
        job_id=asyncio.run(a._dispatch_inbound_event(ev("/standing confirm","s2")))["created"]
        asyncio.run(a.trigger_standing_job(job_id))
        self.assertEqual(a.store.count_tier1("chat-a"),0)
        self.assertIn("chat-a:m1", a.pending_tier1)
        send_reply(a, "m1", "real decision")
        row=a.store.tier1_rows("chat-a")[-1]
        self.assertIn("real decision", row["summary"])
        self.assertNotIn("standing job", row["summary"])

    def test_enable_chat_notice_does_not_consume_pending_tier1(self):
        a=FeishuTagAdapter(PlatformConfig(), cfg())
        asyncio.run(a._dispatch_inbound_event(ev("remember","m1")))
        asyncio.run(a.enable_chat("chat-a"))
        self.assertEqual(a.store.count_tier1("chat-a"),0)
        self.assertIn("chat-a:m1", a.pending_tier1)
        send_reply(a, "m1", "enabled later response")
        self.assertIn("enabled later response", a.store.tier1_rows("chat-a")[-1]["summary"])

    def test_out_of_order_replies_are_matched_by_tier1_key(self):
        a=FeishuTagAdapter(PlatformConfig(), cfg())
        asyncio.run(a._dispatch_inbound_event(ev("first","m1")))
        asyncio.run(a._dispatch_inbound_event(ev("second","m2",user="Bob")))
        send_reply(a, "m2", "reply for second")
        send_reply(a, "m1", "reply for first")
        rows={row["trigger_message_id"]: row["summary"] for row in a.store.tier1_rows("chat-a")}
        self.assertIn("reply for first", rows["m1"])
        self.assertIn("reply for second", rows["m2"])
        self.assertNotIn("reply for second", rows["m1"])
        self.assertNotIn("reply for first", rows["m2"])

    def test_reply_to_message_id_uses_response_correlation_key_without_metadata(self):
        a=FeishuTagAdapter(PlatformConfig(), cfg())
        asyncio.run(a._dispatch_inbound_event(ev("first","m1")))
        asyncio.run(a.send("chat-a", "reply via reply_to", reply_to="m1"))
        self.assertIn("reply via reply_to", a.store.tier1_rows("chat-a")[-1]["summary"])

    def test_unrelated_send_does_not_write_no_reply_pending(self):
        a=FeishuTagAdapter(PlatformConfig(), cfg())
        asyncio.run(a._dispatch_inbound_event(ev("no reply","m1")))
        asyncio.run(a.send("chat-a", "unrelated later bot send"))
        self.assertEqual(a.store.count_tier1("chat-a"),0)
        self.assertIn("chat-a:m1", a.pending_tier1)

    def test_multi_part_reply_writes_once_for_same_tier1_key(self):
        a=FeishuTagAdapter(PlatformConfig(), cfg())
        asyncio.run(a._dispatch_inbound_event(ev("multi","m1")))
        send_reply(a, "m1", "part one")
        send_reply(a, "m1", "part two")
        rows=a.store.tier1_rows("chat-a")
        self.assertEqual(len(rows),1)
        self.assertIn("part one", rows[0]["summary"])
        self.assertNotIn("part two", rows[0]["summary"])

    def test_old_fifo_would_fail_standing_out_of_order_and_no_reply_cases(self):
        original=adapter_mod.FeishuTagAdapter.send
        async def fifo_send(self, chat_id, content, reply_to=None, metadata=None):
            result=await adapter_mod.FeishuAdapter.send(self, chat_id, content, reply_to=reply_to, metadata=metadata)
            with self.store.lock:
                self._prune_pending_tier1_locked()
                first_key=next(iter(self.pending_tier1), None)
                pending=self.pending_tier1.pop(first_key, None) if first_key else None
            if pending:
                _, event, enhanced=pending
                self._write_tier1_memory(event, enhanced, content)
            return result
        adapter_mod.FeishuTagAdapter.send=fifo_send
        try:
            cron=CronAPI()
            a=FeishuTagAdapter(PlatformConfig(), cfg(), cron)
            asyncio.run(a._dispatch_inbound_event(ev("remember","m1")))
            asyncio.run(a._dispatch_inbound_event(ev("/standing add weekly-Friday-10:00 Asia/Shanghai 总结","s1")))
            job_id=asyncio.run(a._dispatch_inbound_event(ev("/standing confirm","s2")))["created"]
            asyncio.run(a.trigger_standing_job(job_id))
            self.assertIn("standing job", a.store.tier1_rows("chat-a")[-1]["summary"])

            b=FeishuTagAdapter(PlatformConfig(), cfg())
            asyncio.run(b._dispatch_inbound_event(ev("first","m1")))
            asyncio.run(b._dispatch_inbound_event(ev("second","m2")))
            asyncio.run(b.send("chat-a", "reply for second", metadata={"task_session_id":"chat-a:m2"}))
            asyncio.run(b.send("chat-a", "reply for first", metadata={"task_session_id":"chat-a:m1"}))
            rows={row["trigger_message_id"]: row["summary"] for row in b.store.tier1_rows("chat-a")}
            self.assertIn("reply for second", rows["m1"])
            self.assertIn("reply for first", rows["m2"])

            c=FeishuTagAdapter(PlatformConfig(), cfg())
            asyncio.run(c._dispatch_inbound_event(ev("no reply","m1")))
            asyncio.run(c.send("chat-a", "unrelated later bot send"))
            self.assertIn("unrelated later bot send", c.store.tier1_rows("chat-a")[-1]["summary"])
        finally:
            adapter_mod.FeishuTagAdapter.send=original

if __name__ == "__main__": unittest.main()
