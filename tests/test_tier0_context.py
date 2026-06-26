import asyncio
import os
import tempfile
import unittest
from types import SimpleNamespace

from hermes_plugin_feishu import FeishuTagAdapter, FeishuTagConfig, MessageEvent, PlatformConfig


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
