import asyncio
from dataclasses import dataclass, field
import os
import tempfile
import unittest
from types import SimpleNamespace
from typing import Any

os.environ.setdefault("HERMES_PLUGIN_FEISHU_USE_STUBS", "1")

from hermes_tag.base import TagAdapterMixin
from hermes_tag.core import TagConfig
from hermes_tag.i18n import CAPABILITY_MISMATCH_NOTICE, CAPABILITY_UPGRADE_NOTICE
from hermes_tag.platforms.feishu import _scopes_from_response


@dataclass
class FakeEvent:
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


class FakeBase:
    def __init__(self, config):
        self.config = config
        self.dispatched = []
        self.sent = []

    async def _dispatch_inbound_event(self, event):
        self.dispatched.append(event)
        return {"handled": event.text}

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        self.sent.append((chat_id, content, reply_to, metadata))
        return {"chat_id": chat_id, "content": content}


async def _fake_fetch_refs(self, reply_id):
    return []


class FakeAdapter(TagAdapterMixin, FakeBase):
    @property
    def platform_name(self):
        return "fake"

    @property
    def receive_all(self):
        return self.tag.has_group_msg_scope

    def is_mentioned(self, event):
        return True

    async def _download_media(self, reply_id, ref):
        return "", ""


setattr(FakeAdapter, "_fetch_" + "reply" + "_media_refs", _fake_fetch_refs)


def tmp_path():
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.close()
    os.unlink(tmp.name)
    return tmp.name


def tag_config(**kw):
    db = tmp_path()
    data = {
        "enabled_chats": ("chat-a",),
        "db_path": db,
        "media_cache_dir": db + ".media",
        "granted_scopes": frozenset({"im:message.group_msg"}),
        "admins": ("ou_admin1",),
        "encryption_posture": "plain",
    }
    data.update(kw)
    return TagConfig(**data)


def source(chat="chat-a", user="ou_user"):
    return SimpleNamespace(chat_id=chat, user_id=user, user_name=user, thread_id=None)


def event(message_id="m1", text="hello"):
    return FakeEvent(text, source=source(), message_id=message_id)


def audit_rows(adapter, event_type):
    return [row for row in adapter.store.audit_events("chat-a") if row["event"] == event_type]


class ProbeAdapter(FakeAdapter):
    def __init__(self, config, tag_config, scopes=None, error=None):
        self.probe_calls = 0
        self._probe_scopes = scopes
        self._probe_error = error
        super().__init__(config, tag_config)

    async def probe_granted_scopes(self):
        self.probe_calls += 1
        if self._probe_error:
            raise self._probe_error
        return self._probe_scopes


class CapabilityCheckTest(unittest.TestCase):
    def test_default_probe_is_unknown_and_silent(self):
        adapter = FakeAdapter(SimpleNamespace(extra={}), tag_config())

        asyncio.run(adapter._dispatch_inbound_event(event()))

        self.assertEqual(adapter.capability_check, {"status": "unknown"})
        self.assertEqual(adapter.sent, [])
        self.assertEqual(audit_rows(adapter, "capability_mismatch"), [])

    def test_mismatch_sends_one_admin_dm_and_audits_once(self):
        adapter = ProbeAdapter(SimpleNamespace(extra={}), tag_config(admins=("ou_admin1",)), {"im:message.group_msg": False})

        with self.assertLogs("hermes_tag.base", level="WARNING"):
            asyncio.run(adapter._dispatch_inbound_event(event("m1")))
        asyncio.run(adapter._dispatch_inbound_event(event("m2")))

        self.assertEqual(adapter.probe_calls, 1)
        self.assertEqual(len(adapter.sent), 1)
        self.assertEqual(adapter.sent[0][0], "ou_admin1")
        self.assertIn(CAPABILITY_MISMATCH_NOTICE["zh"], adapter.sent[0][1])
        self.assertEqual(len(audit_rows(adapter, "capability_mismatch")), 1)
        self.assertEqual(adapter.capability_check["status"], "mismatch")

    def test_ok_status_has_no_notice(self):
        adapter = ProbeAdapter(SimpleNamespace(extra={}), tag_config(), {"im:message.group_msg": True})

        asyncio.run(adapter._dispatch_inbound_event(event()))

        self.assertEqual(adapter.capability_check["status"], "ok")
        self.assertEqual(adapter.sent, [])

    def test_upgrade_available_reports_without_changing_ingest(self):
        adapter = ProbeAdapter(SimpleNamespace(extra={}), tag_config(granted_scopes=frozenset()), {"im:message.group_msg": True})

        asyncio.run(adapter._dispatch_inbound_event(event()))

        self.assertEqual(adapter.capability_check["status"], "upgrade_available")
        self.assertFalse(adapter.receive_all)
        self.assertEqual(len(adapter.sent), 1)
        self.assertIn(CAPABILITY_UPGRADE_NOTICE["zh"], adapter.sent[0][1])
        self.assertEqual(len(audit_rows(adapter, "capability_upgrade")), 1)
        self.assertEqual(adapter.store.count_tier0("chat-a"), 0)

    def test_probe_failure_is_harmless(self):
        adapter = ProbeAdapter(SimpleNamespace(extra={}), tag_config(), error=RuntimeError("boom"))

        result = asyncio.run(adapter._dispatch_inbound_event(event()))

        self.assertEqual(result, {"handled": "hello"})
        self.assertEqual(adapter.capability_check, {"status": "unknown"})

    def test_scopes_from_response_parses_success_and_rejects_bad_shapes(self):
        response = SimpleNamespace(
            success=lambda: True,
            data=SimpleNamespace(scopes=[
                SimpleNamespace(scope_name="im:message.group_msg", grant_status=1),
                SimpleNamespace(scope_name="other", grant_status=0),
            ]),
        )

        self.assertEqual(_scopes_from_response(response), {"im:message.group_msg": True, "other": False})
        self.assertIsNone(_scopes_from_response(SimpleNamespace(success=lambda: False)))
        self.assertIsNone(_scopes_from_response(SimpleNamespace(success=lambda: True, data=SimpleNamespace())))

    def test_preflight_status_surfaces_cached_verdict(self):
        adapter = ProbeAdapter(SimpleNamespace(extra={}), tag_config(), {"im:message.group_msg": True})
        asyncio.run(adapter._dispatch_inbound_event(event()))

        self.assertEqual(adapter.preflight_status()["capability_check"], adapter.capability_check)

    def test_status_command_renders_capability_check(self):
        from hermes_tag.core import format_command_result

        adapter = ProbeAdapter(SimpleNamespace(extra={}), tag_config(), {"im:message.group_msg": True})
        asyncio.run(adapter._dispatch_inbound_event(event()))

        rendered = format_command_result({"status": adapter.preflight_status()})
        self.assertIn("capability_check=ok", rendered.splitlines()[0])


if __name__ == "__main__":
    unittest.main()
