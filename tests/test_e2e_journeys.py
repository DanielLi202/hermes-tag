import asyncio
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from typing import Any

os.environ.setdefault("HERMES_PLUGIN_FEISHU_USE_STUBS", "1")
os.environ["HERMES_PLUGIN_SLACK_USE_STUBS"] = "1"

from hermes_tag import FeishuTagAdapter, FeishuTagConfig, MessageEvent, PlatformConfig
from hermes_tag.i18n import PROMPT_CONTRACT
from hermes_tag.platforms.slack import (
    PlatformConfig as SlackPlatformConfig,
    SlackTagAdapter,
    adapter_factory,
)

SCRIPT = Path(__file__).resolve().parents[1] / "docs" / "slack-manifest-add-tag.py"


def source(chat="chat-a", user="Alice", thread=None):
    return SimpleNamespace(chat_id=chat, user_id=user, user_name=user, thread_id=thread)


def raw(at=False):
    return {"mentions": [{"id": {"open_id": "bot-open"}}] if at else []}


def cfg(**kw):
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.close()
    os.unlink(tmp.name)
    data = {
        "enabled_chats": ["chat-a"],
        "admins": ["Alice"],
        "tier1_max_count": 10,
        "max_context_chars": 500,
        "db_path": tmp.name,
        "media_cache_dir": tmp.name + ".media",
        "encryption_posture": "plain",
        "bot_open_id": "bot-open",
        "granted_scopes": ["im:message.group_msg"],
    }
    data.update(kw)
    return FeishuTagConfig.from_platform_config(data)


def ev(text, mid, user="Alice", at=True, chat="chat-a", thread=None, reply=None):
    return MessageEvent(text, source=source(chat, user, thread), raw_message=raw(at), message_id=mid, reply_to_message_id=reply)


def send_reply(adapter, mid, content, chat="chat-a"):
    return asyncio.run(adapter.send(chat, content, metadata={"response_correlation_key": f"{chat}:{mid}"}))


def scopes(adapter, chat="chat-a"):
    return [json.loads(r["detail"])["scope"] for r in adapter.store.audit_events(chat) if r["event"] == "enhance_event"]


class CronAPI:
    def __init__(self):
        self.created = []
        self.cancelled = []
        self.paused = []
        self.enabled = []

    def create(self, *, chat_id, description, schedule, timezone_name):
        cid = f"cron-{len(self.created) + 1}"
        self.created.append((cid, chat_id, description, schedule, timezone_name))
        return cid

    def cancel(self, job_id):
        self.cancelled.append(job_id)

    def pause(self, job_id):
        self.paused.append(job_id)

    def enable(self, job_id):
        self.enabled.append(job_id)


class MediaAdapter(FeishuTagAdapter):
    async def _download_feishu_image(self, *, message_id, image_key):
        path = self.media_cache_dir / f"{message_id}-{image_key}.jpg"
        path.write_bytes(b"img")
        return str(path), "image/jpeg"

    async def _download_feishu_message_resource(self, *, message_id, file_key, resource_type, fallback_filename=""):
        path = self.media_cache_dir / f"{message_id}-{file_key}.bin"
        path.write_bytes(b"file")
        return str(path), resource_type


@dataclass
class SlackEvent:
    text: str
    source: Any = None
    raw_message: Any = None
    message_id: str | None = None
    media_urls: list[str] = field(default_factory=list)
    media_types: list[str] = field(default_factory=list)
    reply_to_message_id: str | None = None
    reply_to_text: str | None = None
    channel_context: str | None = None
    message_type: str = "text"


class E2EJourneysTest(unittest.TestCase):
    def test_feishu_memory_lifecycle_composes_context_dedup_retention_and_audit(self):
        a = FeishuTagAdapter(PlatformConfig(), cfg(tier1_max_count=3, max_context_chars=1200))
        asyncio.run(a.enable_chat("chat-a"))
        after_enable = len(a.sent)

        for msg in [
            ev("deadline is Friday", "bg1", user="Bob", at=False),
            ev("unrelated chit chat", "bg2", user="Carol", at=False),
            ev("SECRET_TOKEN private body", "bg3", user="Dave", at=False),
        ]:
            asyncio.run(a._dispatch_inbound_event(msg))
        self.assertEqual(len(a.sent), after_enable)

        asyncio.run(a._dispatch_inbound_event(ev("when is the deadline", "ask1")))
        ctx = a.dispatched[-1].channel_context
        self.assertTrue(ctx.startswith("current: when is the deadline\n" + PROMPT_CONTRACT))
        self.assertIn("deadline is Friday", ctx)
        self.assertNotIn("unrelated chit chat", ctx)
        send_reply(a, "ask1", "deadline is Friday")
        self.assertEqual(a.store.count_tier1("chat-a"), 1)

        asyncio.run(a._dispatch_inbound_event(ev("when is the deadline", "ask2")))
        send_reply(a, "ask2", "deadline is Friday")
        self.assertEqual(a.store.count_tier1("chat-a"), 1)
        self.assertEqual(a.store.metric("tier1_write_skipped_duplicate"), 1)

        for i in range(5):
            mid = f"distinct-{i}"
            asyncio.run(a._dispatch_inbound_event(ev(f"distinct question {i}", mid)))
            send_reply(a, mid, f"distinct answer {i}")
        self.assertLessEqual(a.store.count_tier1("chat-a"), 3)
        self.assertTrue(all(len(row["summary"]) <= 2000 for row in a.store.tier1_rows("chat-a")))

        result = asyncio.run(a._dispatch_inbound_event(ev("/tag admin audit", "audit")))
        self.assertTrue(all(item["created_at"] is not None for item in result["audit"]))
        rendered = a.sent[-1][1]
        self.assertIn("scope", rendered)
        self.assertNotIn("context_preview", rendered)
        self.assertNotIn("SECRET_TOKEN", rendered)
        self.assertEqual(len(a.sent) - after_enable, 8)  # 7 @ replies + 1 command reply; ambient messages sent nothing.

    def test_feishu_scope_precedence_ladder_sequence(self):
        a = MediaAdapter(PlatformConfig(), cfg(max_context_chars=1200))
        asyncio.run(a._dispatch_inbound_event(ev("plain question", "plain")))

        img = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        img.write(b"png")
        img.close()
        image_event = ev("", "img1", user="Alice", at=False)
        image_event.media_urls = [img.name]
        image_event.media_types = ["image/png"]
        asyncio.run(a._dispatch_inbound_event(image_event))
        asyncio.run(a._dispatch_inbound_event(ev("上面那张图是什么", "deictic")))

        asyncio.run(a._dispatch_inbound_event(ev("thread sibling text", "thread-row", user="Bob", at=False, thread="t1")))
        asyncio.run(a._dispatch_inbound_event(ev("thread question", "thread-ask", thread="t1")))

        focused = ev("focused question", "focused", thread="t1", reply="evicted-parent")
        focused.reply_to_text = "evicted parent text"
        asyncio.run(a._dispatch_inbound_event(focused))

        self.assertEqual(scopes(a)[-4:], ["plain", "deictic_recent", "thread", "focused_reply"])
        self.assertIn("evicted parent text", a.dispatched[-1].channel_context)

    def test_slack_media_observability_and_scope_parity(self):
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.close()
        os.unlink(tmp.name)
        media = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        media.write(b"png")
        media.close()
        adapter = adapter_factory(SlackPlatformConfig({"slack_tag": {"enabled": True, "enabled_chats": ["C1"], "db_path": tmp.name, "media_cache_dir": tmp.name + ".media", "encryption_posture": "plain"}}))
        self.assertIsInstance(adapter, SlackTagAdapter)
        adapter._bot_user_id = "BOT"

        parent = SlackEvent("", source=SimpleNamespace(chat_id="C1", user_id="U1"), message_id="p1", media_urls=[media.name], media_types=["image/png"])
        asyncio.run(adapter.handle_message(parent))
        asyncio.run(adapter.handle_message(SlackEvent("<@BOT> 上面这张图是什么", source=SimpleNamespace(chat_id="C1", user_id="U2"), message_id="m2")))
        self.assertTrue(adapter.dispatched[-1].media_urls)
        self.assertEqual(adapter.store.metric("slack_reply_media_unavailable"), 0)

        asyncio.run(adapter.handle_message(SlackEvent("<@BOT> parent image?", source=SimpleNamespace(chat_id="C1", user_id="U2"), message_id="m3", reply_to_message_id="p1")))
        self.assertTrue(adapter.dispatched[-1].media_urls)
        self.assertEqual(adapter.store.metric("slack_reply_media_unavailable"), 0)

        asyncio.run(adapter.handle_message(SlackEvent("<@BOT> parent image?", source=SimpleNamespace(chat_id="C1", user_id="U2"), message_id="m4", reply_to_message_id="missing-parent")))
        self.assertEqual(adapter.store.metric("slack_reply_media_unavailable"), 1)

        asyncio.run(adapter.handle_message(SlackEvent("<@BOT> top-level", source=SimpleNamespace(chat_id="C1", user_id="U2", thread_id="self-ts"), message_id="self-ts")))
        self.assertEqual(scopes(adapter, "C1")[-1], "plain")

    def test_admin_lifecycle_degradation_and_enabled_chats_boundary(self):
        a = FeishuTagAdapter(PlatformConfig(), cfg())
        asyncio.run(a.enable_chat("chat-a"))
        asyncio.run(a._dispatch_inbound_event(ev("remember", "m1")))
        send_reply(a, "m1", "answer")
        self.assertGreaterEqual(a.store.count_tier1("chat-a"), 1)

        asyncio.run(a._dispatch_inbound_event(ev("outside", "z1", chat="chat-Z")))
        self.assertEqual(a.store.count_tier1("chat-Z"), 0)

        counts = asyncio.run(a._dispatch_inbound_event(ev("/tag admin count", "count")))
        self.assertGreaterEqual(counts["tier1"], 1)
        result = asyncio.run(a._dispatch_inbound_event(ev("/tag admin clear", "clear")))
        self.assertEqual(result, {"cleared": True})
        self.assertEqual(a.sent[-1], ("chat-a", "cleared; send /new to reset the conversation"))
        self.assertEqual(a.preflight_status()["degraded"], [])
        self.assertEqual(a.store.count_tier1("chat-a"), 0)
        self.assertEqual(a.store.count_tier0("chat-a"), 0)

    def test_p1b_generated_config_shape_boots_slack_tag_adapter(self):
        result = subprocess.run([sys.executable, str(SCRIPT)], text=True, capture_output=True, check=True)
        manifest = json.loads(result.stdout)
        self.assertTrue(any(cmd["command"] == "/tag" for cmd in manifest["features"]["slash_commands"]))
        self.assertIn("commands", manifest["oauth_config"]["scopes"]["bot"])
        self.assertIn("slack_tag:", result.stderr)
        self.assertIn("C_TEST_CHANNEL_ID", result.stderr)

        with tempfile.TemporaryDirectory() as td:
            # ponytail: script emits YAML; stdlib test asserts structure plus equivalent-dict adapter boot, not YAML parsing.
            adapter = adapter_factory(SlackPlatformConfig({"slack_tag": {
                "enabled": True,
                "enabled_chats": ["C_TEST_CHANNEL_ID"],
                "encryption_posture": "plaintext-db-on-local-disk",
                "db_path": str(Path(td) / "slack-tag.sqlite3"),
                "media_cache_dir": str(Path(td) / "slack-tag-media"),
            }}))
            self.assertIsInstance(adapter, SlackTagAdapter)
            adapter._bot_user_id = "BOT"
            asyncio.run(adapter.handle_message(SlackEvent("<@BOT> hello", source=SimpleNamespace(chat_id="C_TEST_CHANNEL_ID", user_id="U1"), message_id="hello")))
            self.assertTrue(adapter.dispatched)


if __name__ == "__main__":
    unittest.main()
