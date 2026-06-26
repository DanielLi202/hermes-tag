import asyncio
import os
import tempfile
import unittest
from types import SimpleNamespace

os.environ.setdefault("HERMES_PLUGIN_FEISHU_USE_STUBS", "1")

from hermes_tag import FeishuTagConfig, FeishuTagStore, MessageEvent, TagEngine
from hermes_tag.core import author_of, chat_id_of, copy_event, thread_id_of


def cfg(**kw):
    tmp=tempfile.NamedTemporaryFile(delete=False); tmp.close(); os.unlink(tmp.name)
    data={"enabled_chats":["chat-b"],"bot_open_id":"bot-open","db_path":tmp.name,"media_cache_dir":tmp.name+".media","granted_scopes":["im:message.group_msg"],"encryption_posture":"plain","max_context_chars":500}
    data.update(kw)
    return FeishuTagConfig.from_platform_config(data)


def ev(text, mid, at=False, user="user-b"):
    source=SimpleNamespace(chat_id="chat-b", user_id=user, user_name=user, thread_id=None)
    raw={"mentions":[{"id":{"open_id":"demo-bot"}}] if at else []}
    return MessageEvent(text, source=source, raw_message=raw, message_id=mid)


class DemoSeam:
    platform_name="demo"
    receive_all=True
    cron_delivery=False

    def __init__(self, store):
        self.store=store
        self.dispatched=[]
        self.sent=[]

    def is_mentioned(self, event):
        return event.is_command() or any(m.get("id",{}).get("open_id")=="demo-bot" for m in event.raw_message.get("mentions",[]))

    def response_correlation_key(self, event, send_args=None):
        return f"demo:{event.source.chat_id}:{event.message_id}"

    def response_correlation_key_for_response(self, chat_id, reply_to=None, metadata=None):
        if isinstance(metadata, dict) and metadata.get("response_correlation_key"):
            return metadata["response_correlation_key"]
        return f"demo:{chat_id}:{reply_to}" if reply_to else None

    def store_tier0(self, event):
        self.store.insert_tier0(chat_id=chat_id_of(event), message_id=event.message_id or "", text=event.text, author=author_of(event), thread_id=thread_id_of(event))

    def handle_command(self, event):
        if event.text.startswith("/standing") and not self.cron_delivery:
            return {"error":"cron unsupported"}
        return None

    async def enhance_event(self, event):
        enhanced=copy_event(event)
        rows=[r for r in self.store.tier0_rows(chat_id_of(event)) if r["message_id"]!=event.message_id]
        enhanced.channel_context="\n".join([f"current: {event.text}"]+[f"{r['author']}: {r['text']}" for r in rows])
        setattr(enhanced, "source_message_ids", [r["message_id"] for r in rows])
        return enhanced, []

    async def dispatch_to_model(self, event):
        self.dispatched.append(event)
        return {"handled": event.message_id}

    async def send_to_platform(self, chat_id, content, reply_to=None, metadata=None):
        self.sent.append((chat_id, content, reply_to, metadata))
        return {"chat_id": chat_id, "content": content, "reply_to": reply_to, "metadata": metadata}

    def write_tier1_memory(self, event, enhanced, result):
        sources=[event.message_id or ""]+list(getattr(enhanced, "source_message_ids", []) or [])
        self.store.write_tier1(chat_id_of(event), f"question={event.text}; conclusion={result}", author_of(event), event.message_id or "", author_of(event), [s for s in sources if s])


class SecondChannelFixtureTest(unittest.TestCase):
    def test_second_channel_real_messageevent_dispatch_memory_degrade_and_f4(self):
        tag=cfg()
        store=FeishuTagStore(tag.db_path)
        seam=DemoSeam(store)
        engine=TagEngine(tag, store, seam)

        self.assertIsNone(asyncio.run(engine.handle_message(ev("ambient background", "b1"))))
        self.assertEqual(engine.store.count_tier0("chat-b"), 1)
        self.assertEqual(seam.dispatched, [])

        result=asyncio.run(engine.handle_message(ev("ask with @", "m1", at=True)))
        self.assertEqual(result, {"handled":"m1"})
        self.assertIn("ambient background", seam.dispatched[-1].channel_context)
        self.assertEqual(getattr(seam.dispatched[-1], "task_session_id"), "demo:chat-b:m1")

        asyncio.run(engine.send("chat-b", "demo answer", metadata={"response_correlation_key":"demo:chat-b:m1"}))
        self.assertEqual(engine.store.count_tier1("chat-b"), 1)
        self.assertIn("demo answer", engine.store.tier1_rows("chat-b")[-1]["summary"])

        degraded=asyncio.run(engine.handle_message(ev("/standing add weekly-Friday-10:00 Asia/Shanghai summary", "s1", at=True)))
        self.assertEqual(degraded, {"error":"cron unsupported"})
        self.assertEqual(seam.sent[-1], ("chat-b", "error: cron unsupported", "s1", {"tag_command": True}))
        self.assertFalse(engine.preflight_status()["capabilities"]["cron_delivery"])

    def test_second_channel_fixture_does_not_use_feishu_adapter_subclass(self):
        self.assertEqual(DemoSeam.platform_name, "demo")
        self.assertFalse(any("FeishuTagAdapter" in base.__name__ for base in DemoSeam.__mro__))


if __name__ == "__main__": unittest.main()
