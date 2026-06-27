import asyncio
import json
import os
import tempfile
import unittest
from types import SimpleNamespace

os.environ.setdefault("HERMES_PLUGIN_FEISHU_USE_STUBS", "1")

from hermes_tag import FeishuTagAdapter, FeishuTagConfig, MessageEvent, PlatformConfig


def source(chat="chat-a", user="Alice", thread=None):
    return SimpleNamespace(chat_id=chat, user_id=user, user_name=user, thread_id=thread)

def raw(at=False):
    return {"mentions": [{"id": {"open_id": "bot-open"}}] if at else []}

def cfg(**kw):
    tmp=tempfile.NamedTemporaryFile(delete=False); tmp.close(); os.unlink(tmp.name)
    data={"enabled_chats":["chat-a"],"bot_open_id":"bot-open","db_path":tmp.name,"media_cache_dir":tmp.name+".media","granted_scopes":["im:message.group_msg"],"encryption_posture":"plain","admins":["Alice"],"max_context_chars":80}
    data.update(kw); return FeishuTagConfig.from_platform_config(data)

def event(text="hi", mid="m", user="Alice", at=False, reply=None):
    return MessageEvent(text, source=source(user=user), raw_message=raw(at), message_id=mid, reply_to_message_id=reply)

class MediaAdapter(FeishuTagAdapter):
    async def _download_feishu_image(self, *, message_id, image_key):
        if image_key == "bad": raise RuntimeError("bad")
        path=self.media_cache_dir/f"{message_id}-{image_key}.jpg"; path.write_bytes(b"img")
        return str(path), "image/jpeg"
    async def _download_feishu_message_resource(self, *, message_id, file_key, resource_type, fallback_filename=""):
        path=self.media_cache_dir/f"{message_id}-{file_key}.bin"; path.write_bytes(b"file")
        return str(path), resource_type

class Tier0ContextV2Test(unittest.TestCase):
    def test_unmentioned_ingests_tier0_without_agent_dispatch(self):
        a=FeishuTagAdapter(PlatformConfig(), cfg())
        self.assertIsNone(asyncio.run(a._dispatch_inbound_event(event("bg","m1"))))
        self.assertEqual(a.store.count_tier0("chat-a"),1)
        self.assertEqual(a.dispatched,[])

    def test_duplicate_message_id_is_idempotent(self):
        a=FeishuTagAdapter(PlatformConfig(), cfg()); e=event("bg","m1")
        asyncio.run(a._dispatch_inbound_event(e)); asyncio.run(a._dispatch_inbound_event(e))
        self.assertEqual(a.store.count_tier0("chat-a"),1)

    def test_at_reply_image_and_file_resolved_from_parent_message(self):
        a=MediaAdapter(PlatformConfig(), cfg())
        a.parent_messages={"p1":{"media_refs":[{"kind":"image","key":"img1"},{"kind":"file","key":"f1","resource_type":"file"}]}}
        self.assertIsNone(asyncio.run(a._dispatch_inbound_event(event("see","m1",at=True,reply="p1"))))
        out=a.dispatched[-1]
        self.assertEqual(len(out.media_urls),2)
        self.assertEqual(out.media_types,["image/jpeg","file"])

    def test_media_download_failure_adds_placeholder_and_continues(self):
        a=MediaAdapter(PlatformConfig(), cfg()); a.parent_messages={"p1":{"media_refs":[{"kind":"image","key":"bad"}]}}
        asyncio.run(a._dispatch_inbound_event(event("see","m1",at=True,reply="p1")))
        self.assertIn("[media unavailable: bad]", a.dispatched[-1].channel_context)

    def test_no_group_msg_reply_media_has_no_orphan_cache(self):
        a=MediaAdapter(PlatformConfig(), cfg(granted_scopes=[])); a.parent_messages={"p1":{"media_refs":[{"kind":"image","key":"img1"}]}}
        asyncio.run(a._dispatch_inbound_event(event("see","m1",at=True,reply="p1")))
        out=a.dispatched[-1]
        self.assertEqual(a.store.count_tier0("chat-a"),0)
        self.assertFalse(os.path.exists(out.media_urls[0]))

    def test_l2_selects_relevant_author_tagged_context_not_unrelated_bob(self):
        a=FeishuTagAdapter(PlatformConfig(), cfg())
        asyncio.run(a._dispatch_inbound_event(event("Bob unrelated","b1",user="Bob")))
        asyncio.run(a._dispatch_inbound_event(event("Alice setup","a1",user="Alice")))
        asyncio.run(a._dispatch_inbound_event(event("那个截图","a2",user="Alice",at=True)))
        ctx=a.dispatched[-1].channel_context
        self.assertIn("Alice: Alice setup",ctx); self.assertNotIn("Bob unrelated",ctx)

    def test_l2_falls_back_to_recent_same_chat_when_no_author_or_thread_match(self):
        a=FeishuTagAdapter(PlatformConfig(), cfg())
        asyncio.run(a._dispatch_inbound_event(event("deadline is Friday","b1",user="Bob")))
        asyncio.run(a._dispatch_inbound_event(event("when is the deadline","a1",user="Alice",at=True)))
        self.assertIn("Bob: deadline is Friday", a.dispatched[-1].channel_context)

    def test_l2_attaches_previous_media_message_without_feishu_reply(self):
        a=FeishuTagAdapter(PlatformConfig(), cfg(max_context_chars=500))
        incoming=tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        incoming.write(b"image-bytes"); incoming.close()
        image_event=event("", "img1", user="Alice")
        image_event.media_urls=[incoming.name]
        image_event.media_types=["image/png"]
        asyncio.run(a._dispatch_inbound_event(image_event))
        rows=a.store.tier0_rows("chat-a")
        stored_paths=__import__("json").loads(rows[-1]["media_paths"])
        self.assertEqual(len(stored_paths),1)
        self.assertTrue(stored_paths[0].startswith(str(a.media_cache_dir)))
        self.assertTrue(os.path.exists(stored_paths[0]))

        asyncio.run(a._dispatch_inbound_event(event("上面这张图片是什么内容","ask1",user="Alice",at=True)))
        out=a.dispatched[-1]
        self.assertIn(stored_paths[0], out.media_urls)
        self.assertIn("image/png", out.media_types)
        self.assertIn("[media message: 1 attachment(s)]", out.channel_context)
        self.assertIn("[related media from img1: 1 attachment(s)]", out.channel_context)

    def test_synthetic_self_thread_does_not_block_deictic_media(self):
        a=FeishuTagAdapter(PlatformConfig(), cfg(max_context_chars=500))
        incoming=tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        incoming.write(b"image-bytes"); incoming.close()
        img=event("", "img1", user="Alice")
        img.media_urls=[incoming.name]; img.media_types=["image/png"]
        asyncio.run(a._dispatch_inbound_event(img))
        stored_path=json.loads(a.store.tier0_rows("chat-a")[-1]["media_paths"])[0]

        ask=event("上面这张图是什么","ask1",user="Alice",at=True)
        ask.source.thread_id="ask1"
        asyncio.run(a._dispatch_inbound_event(ask))
        out=a.dispatched[-1]
        self.assertIn(stored_path, out.media_urls)
        detail=json.loads([r for r in a.store.audit_events("chat-a") if r["event"]=="enhance_event"][-1]["detail"])
        self.assertEqual(detail["scope"],"deictic_recent")
        self.assertFalse(detail["reanchored"])

    def test_plain_mention_attaches_no_recent_media(self):
        a=FeishuTagAdapter(PlatformConfig(), cfg(max_context_chars=500))
        incoming=tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        incoming.write(b"image-bytes"); incoming.close()
        img=event("Bob image","b1",user="Bob")
        img.media_urls=[incoming.name]
        img.media_types=["image/png"]
        asyncio.run(a._dispatch_inbound_event(img))

        asyncio.run(a._dispatch_inbound_event(event("项目进度如何","a1",user="Alice",at=True)))
        out=a.dispatched[-1]
        self.assertEqual(out.media_urls,[])
        self.assertEqual(out.media_types,[])
        self.assertIn("Bob: Bob image", out.channel_context)

    def test_deictic_singular_attaches_only_nearest_image(self):
        a=FeishuTagAdapter(PlatformConfig(), cfg(max_context_chars=500))
        old=tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        old.write(b"old"); old.close()
        older=event("old image","old",user="Alice")
        older.media_urls=[old.name]; older.media_types=["image/png"]
        asyncio.run(a._dispatch_inbound_event(older))
        new=tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        new.write(b"new"); new.close()
        newer=event("new image","new",user="Alice")
        newer.media_urls=[new.name]; newer.media_types=["image/png"]
        asyncio.run(a._dispatch_inbound_event(newer))
        rows={r["message_id"]:json.loads(r["media_paths"])[0] for r in a.store.tier0_rows("chat-a")}

        asyncio.run(a._dispatch_inbound_event(event("上面这张图是什么","ask",user="Alice",at=True)))
        out=a.dispatched[-1]
        self.assertEqual(out.media_urls,[rows["new"]])
        self.assertNotIn(rows["old"], out.media_urls)

    def test_deictic_plural_attaches_multiple(self):
        a=FeishuTagAdapter(PlatformConfig(), cfg(max_context_chars=500))
        first=tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        first.write(b"1"); first.close()
        e1=event("first image","i1",user="Alice")
        e1.media_urls=[first.name]; e1.media_types=["image/png"]
        asyncio.run(a._dispatch_inbound_event(e1))
        second=tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        second.write(b"2"); second.close()
        e2=event("second image","i2",user="Alice")
        e2.media_urls=[second.name]; e2.media_types=["image/png"]
        asyncio.run(a._dispatch_inbound_event(e2))
        paths={r["message_id"]:json.loads(r["media_paths"])[0] for r in a.store.tier0_rows("chat-a")}

        asyncio.run(a._dispatch_inbound_event(event("这几张图分别是什么","ask",user="Alice",at=True)))
        out=a.dispatched[-1]
        self.assertEqual(set(out.media_urls),{paths["i1"],paths["i2"]})
        self.assertLessEqual(len(out.media_urls),3)

    def test_channel_memory_is_text_never_media(self):
        a=FeishuTagAdapter(PlatformConfig(), cfg(max_context_chars=500))
        a.store.write_tier1("chat-a","deadline stays Friday","Alice","m0","Alice",["m0"])
        asyncio.run(a._dispatch_inbound_event(event("项目进度如何","a1",user="Alice",at=True)))
        out=a.dispatched[-1]
        self.assertIn("memory(owner=Alice): deadline stays Friday", out.channel_context)
        self.assertEqual(out.media_urls,[])

    def test_focused_reply_excludes_unrelated_l2_media(self):
        a=MediaAdapter(PlatformConfig(), cfg(max_context_chars=500))
        incoming=tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        incoming.write(b"image-bytes"); incoming.close()
        img_ev=event("", "b1", user="Bob")
        img_ev.media_urls=[incoming.name]
        img_ev.media_types=["image/png"]
        asyncio.run(a._dispatch_inbound_event(img_ev))
        rows=a.store.tier0_rows("chat-a")
        stored_paths=__import__("json").loads(rows[-1]["media_paths"])
        self.assertEqual(len(stored_paths),1)
        self.assertTrue(stored_paths[0].startswith(str(a.media_cache_dir)))
        self.assertTrue(os.path.exists(stored_paths[0]))

        a.parent_messages={"p1":{"media_refs":[{"kind":"image","key":"img1"}]}}
        asyncio.run(a._dispatch_inbound_event(event("see this", "m1", user="Alice", at=True, reply="p1")))
        out=a.dispatched[-1]
        self.assertEqual(len(out.media_urls),1)
        self.assertIn("p1-img1", out.media_urls[0])
        self.assertNotIn(stored_paths[0], out.media_urls)

    def test_audit_records_scope_and_exclusions(self):
        a=MediaAdapter(PlatformConfig(), cfg(max_context_chars=500))
        incoming=tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        incoming.write(b"image-bytes"); incoming.close()
        img_ev=event("", "b1", user="Bob")
        img_ev.media_urls=[incoming.name]
        img_ev.media_types=["image/png"]
        asyncio.run(a._dispatch_inbound_event(img_ev))

        a.parent_messages={"p1":{"media_refs":[{"kind":"image","key":"img1"}]}}
        asyncio.run(a._dispatch_inbound_event(event("see this", "m1", user="Alice", at=True, reply="p1")))
        audits=[row for row in a.store.audit_events("chat-a") if row["event"]=="enhance_event"]
        detail=json.loads(audits[-1]["detail"])
        self.assertEqual(detail["scope"],"focused_reply")
        excluded={item["id"]:item["reason"] for item in detail["excluded"]}
        self.assertEqual(excluded["b1"],"focused_reply:anchor")

    def test_focused_reply_keeps_user_attached_media(self):
        a=MediaAdapter(PlatformConfig(), cfg(max_context_chars=500))
        a.parent_messages={"p1":{"media_refs":[{"kind":"image","key":"img1"}]}}
        incoming=tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        incoming.write(b"image-bytes"); incoming.close()
        ask=event("compare these", "m2", user="Alice", at=True, reply="p1")
        ask.media_urls=[incoming.name]
        ask.media_types=["image/png"]
        asyncio.run(a._dispatch_inbound_event(ask))
        out=a.dispatched[-1]
        self.assertEqual(len(out.media_urls),2)
        self.assertIn(incoming.name, out.media_urls)
        self.assertTrue(any("p1-img1" in path for path in out.media_urls))

    def test_focused_reply_reanchors_to_triggering_message(self):
        a=MediaAdapter(PlatformConfig(), cfg())
        a.parent_messages={"p1":{"media_refs":[{"kind":"image","key":"img1"}]}}
        ev=event("这是什么","m1",user="Alice",at=True,reply="p1")
        ev.source.thread_id="t1"
        asyncio.run(a._dispatch_inbound_event(ev))
        out=a.dispatched[-1]
        self.assertIsNone(out.reply_to_message_id)          # answer re-anchored off the parent
        self.assertIsNone(out.source.thread_id)              # Feishu must not create/send into the reply thread
        self.assertEqual(ev.reply_to_message_id,"p1")       # original event untouched
        self.assertEqual(ev.source.thread_id,"t1")           # source object was cloned before thread cleanup
        self.assertIn("p1", out.source_message_ids)         # parent kept as evidence provenance

    def test_thread_only_quote_reanchors_to_main_chat_and_keeps_anchor_media(self):
        a=FeishuTagAdapter(PlatformConfig(), cfg(max_context_chars=500))
        incoming=tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        incoming.write(b"image-bytes"); incoming.close()
        img=event("", "img1", user="Alice")
        img.media_urls=[incoming.name]; img.media_types=["image/png"]
        asyncio.run(a._dispatch_inbound_event(img))

        ask=event("这张图片是什么内容","m1",user="Alice",at=True)
        ask.source.thread_id="img1"
        asyncio.run(a._dispatch_inbound_event(ask))
        out=a.dispatched[-1]
        self.assertIsNone(out.reply_to_message_id)
        self.assertIsNone(out.source.thread_id)
        self.assertEqual(ask.source.thread_id,"img1")
        self.assertIn("img1", out.source_message_ids)
        self.assertEqual(len(out.media_urls),1)
        audits=[r for r in a.store.audit_events("chat-a") if r["event"]=="enhance_event"]
        detail=json.loads(audits[-1]["detail"])
        self.assertEqual(detail["scope"],"focused_reply")
        self.assertTrue(detail["reanchored"])

    def test_focused_reply_on_text_parent_suppresses_recent_media(self):
        a=MediaAdapter(PlatformConfig(), cfg(max_context_chars=500))
        incoming=tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        incoming.write(b"image-bytes"); incoming.close()
        img=event("Bob image","b1",user="Bob")
        img.media_urls=[incoming.name]; img.media_types=["image/png"]
        asyncio.run(a._dispatch_inbound_event(img))
        a.parent_messages={"p1":{"media_refs":[]}}          # text-only parent, no media to fetch
        asyncio.run(a._dispatch_inbound_event(event("看看","m1",user="Alice",at=True,reply="p1")))
        out=a.dispatched[-1]
        self.assertEqual(out.media_urls,[])                 # explicit reply still narrows: no recent media
        audits=[r for r in a.store.audit_events("chat-a") if r["event"]=="enhance_event"]
        self.assertEqual(json.loads(audits[-1]["detail"])["scope"],"focused_reply")

    def test_deictic_media_recorded_in_provenance(self):
        a=FeishuTagAdapter(PlatformConfig(), cfg(max_context_chars=500))
        img=tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        img.write(b"image-bytes"); img.close()
        e=event("an image","i1",user="Alice")
        e.media_urls=[img.name]; e.media_types=["image/png"]
        asyncio.run(a._dispatch_inbound_event(e))
        asyncio.run(a._dispatch_inbound_event(event("上面这张图是什么","ask",user="Alice",at=True)))
        out=a.dispatched[-1]
        self.assertIn("i1", out.source_message_ids)         # the image used as evidence is traceable

    def test_budget_keeps_current_before_background(self):
        a=FeishuTagAdapter(PlatformConfig(), cfg(max_context_chars=30))
        asyncio.run(a._dispatch_inbound_event(event("long bg"*20,"a1")))
        asyncio.run(a._dispatch_inbound_event(event("now","a2",at=True)))
        self.assertTrue(a.dispatched[-1].channel_context.startswith("current: now"))

    def test_tier0_eviction_deletes_rows_and_media(self):
        a=FeishuTagAdapter(PlatformConfig(), cfg(tier0_ttl_seconds=1))
        media=a.media_cache_dir/"old.bin"; media.write_bytes(b"x")
        a.store.insert_tier0(chat_id="chat-a",message_id="old",text="old",author="Alice",thread_id=None,media_paths=[str(media)],created_at=1)
        self.assertEqual(a.store.evict_tier0("chat-a",1,99),1)
        self.assertFalse(media.exists()); self.assertEqual(a.store.metric("tier0_evicted"),1)

if __name__ == "__main__": unittest.main()
