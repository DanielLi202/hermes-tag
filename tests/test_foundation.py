import importlib.util
import inspect
import os
from pathlib import Path
import stat
import tempfile
import unittest

os.environ.setdefault("HERMES_PLUGIN_FEISHU_USE_STUBS", "1")

import hermes_plugin_feishu.adapter as mod
from hermes_plugin_feishu import FeishuTagAdapter, FeishuTagConfig, MessageEvent, PlatformConfig, TagEngine, adapter_factory, assert_real_seams, register


def temp_config(**kw):
    tmp = tempfile.NamedTemporaryFile(delete=False); tmp.close(); os.unlink(tmp.name)
    data = {"enabled_chats":["chat-a"],"bot_app_id":"bot","bot_open_id":"bot-open","db_path":tmp.name,"media_cache_dir":tmp.name+".media","granted_scopes":["im:message.group_msg"],"encryption_posture":"plain","admins":["Alice"]}
    data.update(kw)
    return FeishuTagConfig.from_platform_config(data)

def source(chat="chat-a", user="Alice"):
    return type("S", (), {"chat_id":chat,"user_id":user,"user_name":user,"thread_id":None})()

def dm_source(chat="chat-a", user="Alice"):
    return type("S", (), {"chat_id":chat,"user_id":user,"user_name":user,"thread_id":None,"chat_type":"dm"})()

def raw_feishu_data(message):
    return type("Data", (), {"event": type("Event", (), {"message": message})()})()

class Ctx:
    def __init__(self): self.calls=[]
    def register_platform(self, name, label, adapter_factory, check_fn, validate_config=None, required_env=None, install_hint="", **entry_kwargs):
        self.calls.append({"name":name,"label":label,"adapter_factory":adapter_factory,"check_fn":check_fn,"required_env":required_env,"install_hint":install_hint,"entry_kwargs":entry_kwargs})

class FoundationV2Test(unittest.TestCase):
    def test_register_uses_supported_real_register_platform_signature(self):
        ctx=Ctx(); register(ctx)
        call=ctx.calls[0]
        self.assertEqual(call["name"], "feishu")
        self.assertIn("required_env", call)
        self.assertIn("emoji", call["entry_kwargs"])
        self.assertIn("apply_yaml_config_fn", call["entry_kwargs"])
        self.assertIn("allowed_users_env", call["entry_kwargs"])
        self.assertIn("allow_all_env", call["entry_kwargs"])
        self.assertIn("cron_deliver_env_var", call["entry_kwargs"])
        self.assertIn("standalone_sender_fn", call["entry_kwargs"])
        self.assertFalse(hasattr(mod,"register" + "_plugin"))

    def test_apply_yaml_config_accepts_legacy_and_platform_extra_locations(self):
        top = mod.apply_yaml_config({"extra":{"feishu_tag":{"enabled":True,"enabled_chats":["oc-top"]}}}, {"require_mention":False})
        nested = mod.apply_yaml_config({}, {"extra":{"feishu_tag":{"enabled":True,"enabled_chats":["oc-nested"]}}})
        direct = mod.apply_yaml_config({}, {"feishu_tag":{"enabled":True,"enabled_chats":["oc-direct"]}})
        self.assertEqual(top["feishu_tag"]["enabled_chats"], ["oc-top"])
        self.assertEqual(nested["feishu_tag"]["enabled_chats"], ["oc-nested"])
        self.assertEqual(direct["feishu_tag"]["enabled_chats"], ["oc-direct"])

    def test_factory_falls_back_when_tag_unconfigured_or_disabled(self):
        self.assertNotIsInstance(adapter_factory(PlatformConfig()), FeishuTagAdapter)
        disabled=PlatformConfig({"feishu_tag":{"enabled":False}})
        self.assertNotIsInstance(adapter_factory(disabled), FeishuTagAdapter)

    def test_factory_enables_only_with_valid_tag_config(self):
        cfg=temp_config()
        enabled=PlatformConfig({"feishu_tag":{"enabled":True,"enabled_chats":["chat-a"],"bot_open_id":"bot-open","db_path":cfg.db_path,"media_cache_dir":cfg.media_cache_dir,"encryption_posture":"plain"}})
        self.assertIsInstance(adapter_factory(enabled), FeishuTagAdapter)

    def test_plugin_manifest_uses_official_directory_fields_only(self):
        text=Path("plugin.yaml").read_text(encoding="utf-8")
        self.assertIn("manifest_version: 1", text)
        self.assertIn("requires_env:", text)
        for invalid in ("entrypoint:", "hermes_version:", "hermes_tag:", "hermes_commit:", "lark_oapi_version:", "platform:"):
            self.assertNotIn(invalid, text)

    def test_root_directory_plugin_entrypoint_exposes_register(self):
        spec=importlib.util.spec_from_file_location("hermes_tag_root", "__init__.py")
        root=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(root)
        self.assertIs(root.register, register)

    def test_send_selfcheck_requires_async_content_signature(self):
        a=FeishuTagAdapter(PlatformConfig(), temp_config())
        assert_real_seams(a)
        class TextSend:
            async def _dispatch_inbound_event(self, event): pass
            async def _download_feishu_image(self, *, message_id, image_key): pass
            async def _download_feishu_message_resource(self, *, message_id, file_key, resource_type, fallback_filename=""): pass
            async def send(self, chat_id, text, reply_to=None, metadata=None): pass
        with self.assertRaisesRegex(RuntimeError, "signature mismatch"):
            assert_real_seams(TextSend())
        class SyncSend:
            async def _dispatch_inbound_event(self, event): pass
            async def _download_feishu_image(self, *, message_id, image_key): pass
            async def _download_feishu_message_resource(self, *, message_id, file_key, resource_type, fallback_filename=""): pass
            def send(self, chat_id, content, reply_to=None, metadata=None): pass
        with self.assertRaisesRegex(RuntimeError, "must be async"):
            assert_real_seams(SyncSend())

    def test_production_feishu_path_uses_shared_tag_engine(self):
        a=FeishuTagAdapter(PlatformConfig(), temp_config())
        self.assertIsInstance(a.engine, TagEngine)
        self.assertIs(a.pending_tier1, a.engine.pending)
        src=inspect.getsource(mod.FeishuTagAdapter._dispatch_inbound_event)
        self.assertIn("self.engine.handle_message", src)
        self.assertIn("not in self.tag.enabled_chats", src)
        self.assertIn("super()._dispatch_inbound_event", src)

    def test_core_does_not_import_feishu_adapter_module(self):
        text=Path("src/hermes_plugin_feishu/core.py").read_text()
        self.assertNotIn("from .adapter import", text)
        self.assertNotIn("FeishuTag", text)

    def test_enabled_chats_require_at_least_one_and_db_0600(self):
        cfg=temp_config(); FeishuTagAdapter(PlatformConfig(), cfg)
        self.assertEqual(stat.S_IMODE(os.stat(cfg.db_path).st_mode),0o600)
        with self.assertRaisesRegex(ValueError,"at least one"): temp_config(enabled_chats=[])
        multi=temp_config(enabled_chats=["chat-a","chat-b"])
        self.assertEqual(multi.pilot_chat_id, "chat-a")

    def test_multiple_enabled_chats_are_admitted_and_counted_separately(self):
        a=FeishuTagAdapter(PlatformConfig(), temp_config(enabled_chats=["chat-a","chat-b"], require_mention=False))
        import asyncio
        self.assertIsNone(asyncio.run(a._dispatch_inbound_event(MessageEvent("background", source=source("chat-b"), raw_message={"mentions":[]}, message_id="m-b1"))))
        self.assertEqual(a.store.count_tier0("chat-a"),0)
        self.assertEqual(a.store.count_tier0("chat-b"),1)
        self.assertEqual(a.store.count_tier0("other"),0)
        self.assertEqual(a.dispatched,[])
        metrics=a.preflight_status()["metrics"]["enabled_chat_metrics"]
        self.assertEqual(metrics["chat-a"]["tier0_rows"],0)
        self.assertEqual(metrics["chat-b"]["tier0_rows"],1)
        self.assertEqual([row["chat_id"] for row in a.store.audit_events() if row["event"] == "startup"], ["chat-a","chat-b"])

    def test_non_enabled_chat_passthrough_without_storage(self):
        a=FeishuTagAdapter(PlatformConfig(), temp_config())
        import asyncio
        self.assertIsNone(asyncio.run(a._dispatch_inbound_event(MessageEvent("hi", source=source("other"), message_id="m1"))))
        self.assertEqual(a.store.count_tier0("other"),0)
        self.assertEqual(len(a.dispatched), 1)
        self.assertEqual(a.preflight_status()["metrics"]["admission_dropped"],0)

    def test_receive_all_still_self_gates_unmentioned_messages(self):
        a=FeishuTagAdapter(PlatformConfig(), temp_config(require_mention=False))
        import asyncio
        self.assertIsNone(asyncio.run(a._dispatch_inbound_event(MessageEvent("ambient", source=source(), raw_message={"mentions":[]}, message_id="m1"))))
        self.assertEqual(a.store.count_tier0("chat-a"),1)
        self.assertEqual(a.dispatched,[])

    def test_group_mention_from_real_feishu_raw_message_dispatches(self):
        a=FeishuTagAdapter(PlatformConfig(), temp_config(require_mention=False))
        raw_message=type("RawMessage", (), {"mentions":[{"id":{"open_id":"bot-open"}}], "content":"{}", "message_type":"text"})()
        a._mentions_self=lambda message: bool(getattr(message, "mentions", None))
        import asyncio
        self.assertIsNone(asyncio.run(a._dispatch_inbound_event(MessageEvent("question", source=source(), raw_message=raw_feishu_data(raw_message), message_id="m2"))))
        self.assertEqual(a.store.count_tier0("chat-a"),1)
        self.assertEqual(len(a.dispatched),1)

    def test_dm_pilot_does_not_require_mention(self):
        a=FeishuTagAdapter(PlatformConfig(), temp_config(require_mention=False))
        import asyncio
        self.assertIsNone(asyncio.run(a._dispatch_inbound_event(MessageEvent("dm hello", source=dm_source(), raw_message={"mentions":[]}, message_id="m1"))))
        self.assertEqual(a.store.count_tier0("chat-a"),1)
        self.assertEqual(len(a.dispatched),1)

    def test_without_group_msg_degrades_l2_but_keeps_tier1(self):
        caps=FeishuTagAdapter(PlatformConfig(), temp_config(granted_scopes=[])).preflight_status()["capabilities"]
        self.assertFalse(caps["tier0_full_ingest"]); self.assertFalse(caps["l2_context"]); self.assertTrue(caps["tier1_at_memory"])

    def test_v2_forbidden_event_fields_absent_in_tests(self):
        for path in Path("tests").glob("test_*.py"):
            text=path.read_text()
            self.assertNotIn("." + "mentioned", text)
            self.assertNotIn("reply" + "_media_refs", text)

    def test_repair_evidence_records_live_smoke_blocker(self):
        text=Path("docs/design/repair-evidence.md").read_text(encoding="utf-8")
        self.assertIn("R4 live smoke is blocked", text)

    def test_after_install_documents_receive_all_and_no_brick_fallback(self):
        text=Path("after-install.md").read_text(encoding="utf-8")
        self.assertIn("require_mention: false", text)
        self.assertIn("feishu_tag:", text)
        self.assertIn("enabled: true", text)
        self.assertIn("legacy top-level `extra.feishu_tag`", text)
        self.assertIn("falls back", text)

if __name__ == "__main__": unittest.main()
