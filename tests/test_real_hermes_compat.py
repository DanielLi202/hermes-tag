import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


class RealHermesCompatTest(unittest.TestCase):
    def test_v0225_runtime_contract(self):
        env = {key: value for key, value in os.environ.items()
               if not (key.startswith('HERMES_PLUGIN_') and key.endswith('_USE_STUBS'))
               and not key.startswith(('FEISHU_', 'SLACK_', 'DINGTALK_'))}
        env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src')
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        with tempfile.TemporaryDirectory() as home:
            env['HERMES_HOME'] = home
            probe = subprocess.run([sys.executable, '-c',
                "import importlib.util; import sys; sys.exit(0 if importlib.util.find_spec('hermes_cli') else 1)"],
                env=env, text=True, capture_output=True)
            if probe.returncode:
                if os.environ.get('HERMES_TAG_REQUIRE_REAL_HERMES') == '1':
                    self.fail(f'Hermes is not importable by {sys.executable}: {probe.stderr}')
                self.skipTest(f'Hermes is not importable by {sys.executable}')
            Path(home, '.env').write_text(
                'FEISHU_APP_ID=cli_test_app\nFEISHU_APP_SECRET=test_secret_not_real\n'
                'FEISHU_HOME_CHANNEL=oc_probe_home\n')
            Path(home, 'config.yaml').write_text(textwrap.dedent('''\
                platforms:
                  feishu:
                    enabled: true
                    require_mention: false
                    extra:
                      feishu_tag:
                        enabled: true
                        enabled_chats: [oc_probe_home]
                        bot_open_id: ou_probe_bot
                        granted_scopes: [im:message.group_msg]
                        encryption_posture: plaintext-db-on-local-disk
                '''))
            script = textwrap.dedent('''\
                import asyncio
                import json
                import os
                from pathlib import Path
                from types import SimpleNamespace
                from unittest.mock import AsyncMock, patch

                from hermes_cli.env_loader import load_hermes_dotenv
                load_hermes_dotenv(hermes_home=os.environ['HERMES_HOME'])
                from hermes_cli.plugins import discover_plugins, get_plugin_manager, PluginContext
                from hermes_cli.plugins_manifest import PluginManifest
                discover_plugins()
                import hermes_tag
                from hermes_tag.platforms import feishu, slack, dingtalk
                from hermes_tag.base import capture_platform_registration, _command_event
                from hermes_tag.core import copy_event
                from gateway.config import load_gateway_config, Platform
                from gateway.platform_registry import platform_registry
                from gateway.platforms.base import MessageEvent, MessageType
                from gateway.session import SessionSource

                manifest = PluginManifest(name='hermes-tag', version='0.5.0', source='user', kind='platform')
                hermes_tag.register(PluginContext(manifest, get_plugin_manager()))
                for mod, name in ((feishu, 'feishu'), (slack, 'slack'), (dingtalk, 'dingtalk')):
                    upstream = capture_platform_registration(getattr(mod, f'_base_{name}'))
                    entry = platform_registry.get(name)
                    assert entry.env_overrides, name
                    assert entry.ensure_deps_fn is upstream['ensure_deps_fn'], name
                    assert entry.check_fn is upstream['check_fn'], name
                    assert entry.check_fn.__name__ == f'{name}_deps_present', name
                    assert entry.check_fn is not entry.ensure_deps_fn, name
                    assert entry.adapter_factory is mod.adapter_factory, name
                    assert mod._base_apply_yaml_config is upstream['apply_yaml_config_fn'], name
                    assert mod._base_registration.keys() >= upstream.keys(), name

                cfg = load_gateway_config()
                pc = cfg.platforms[Platform.FEISHU]
                assert pc.home_channel.chat_id == 'oc_probe_home', pc.home_channel
                entry = platform_registry.get('feishu')
                # Refuse an accidental dependency install: all SDKs must already be present.
                assert entry.check_fn(), 'Feishu dependencies missing'
                adapter = platform_registry.create_adapter('feishu', pc)
                assert type(adapter) is feishu.FeishuTagAdapter, type(adapter)
                assert adapter._app_id == 'cli_test_app', adapter._app_id
                expected_db = Path(os.environ['HERMES_HOME']) / 'plugin-data/hermes-tag/feishu-tag.sqlite3'
                assert adapter.store.path == expected_db, adapter.store.path

                async def exercise():
                    slack_adapter = slack.SlackTagAdapter(slack.PlatformConfig(),
                        slack.TagConfig(enabled_chats=('C',), db_path=str(Path(os.environ['HERMES_HOME']) / 'slack.db'), max_context_chars=1600))
                    messages = [{'ts': str(i + 1), 'user': f'U{i}', 'text': f'message {i} ' + 'x' * 60}
                                for i in range(30)]
                    for authorized in (True, False):
                        with patch.object(slack_adapter, '_resolve_user_name', AsyncMock(side_effect=lambda user, **kwargs: user)), patch.object(slack_adapter, '_is_sender_authorized', return_value=authorized):
                            native, _ = await slack.SlackAdapter._format_thread_context(slack_adapter, messages,
                                thread_ts='1', current_ts='31', team_id='T', channel_id='C')
                        context = slack_adapter._budget_context('question', [], ['deadline Friday'], [], native)
                        header, footer = native.rstrip().splitlines()[0], native.rstrip().splitlines()[-1]
                        assert header in context and footer in context, context
                        assert 'U29: message 29 ' + 'x' * 60 in context, context
                        assert 'earlier thread messages omitted]' in context, context
                        assert 'deadline Friday' in context, context
                        assert len(context) <= 1600, len(context)
                    slack_adapter.store.conn.close()
                    message = SimpleNamespace(content=json.dumps({'text': 'hello probe'}),
                        message_type='text', message_id='om_probe', mentions=None)
                    result = await adapter._extract_message_content(message)
                    assert len(result) == 6, result
                    assert result[0] == 'hello probe', result
                    assert result[4] == [] and result[5] == [], result
                    # The real extractor must keep the flag in slot 5, mentions in slot 6.
                    with patch.object(adapter, '_download_feishu_message_resources', AsyncMock(return_value=(['data.csv'], ['text/csv']))), patch.object(adapter, '_maybe_extract_text_document', AsyncMock(return_value='')):
                        document = await adapter._extract_message_content(message)
                    assert document[4] == [False] and document[5] == [], document
                    event = MessageEvent(text='question', message_type=MessageType.DOCUMENT,
                        source=SessionSource(platform=Platform.FEISHU, chat_id='oc_probe_home', user_id='ou_user'),
                        message_id='om_event', reply_to_message_id='om_parent',
                        media_urls=['data.csv'], media_types=['text/csv'], media_text_inlined=[False],
                        channel_prompt='bound prompt', auto_skill='bound skill', metadata={'probe': True})
                    event._gateway_accepted = True
                    event._notification_reply_muted = True
                    with patch.object(adapter, '_load_reply_media', AsyncMock(return_value=(['parent.png'], ['image/png'], [], []))):
                        enhanced, _ = await adapter._enhance_event(event)
                    for copied in (copy_event(event), _command_event(event, '/tag status'), enhanced):
                        assert copied.channel_prompt == 'bound prompt'
                        assert copied.auto_skill == 'bound skill'
                        assert copied.metadata == {'probe': True} and copied.metadata is not event.metadata
                        assert copied._gateway_accepted and copied._notification_reply_muted
                        for attr in ('media_urls', 'media_types', 'media_text_inlined'):
                            assert getattr(copied, attr) is not getattr(event, attr), attr
                    assert enhanced.media_text_inlined == [False, False], enhanced.media_text_inlined
                    assert len(enhanced.media_text_inlined) == len(enhanced.media_urls)
                    assert event.media_text_inlined == [False]
                asyncio.run(exercise())
                adapter.store.conn.close()
                print('real Hermes: extraction, registration, home_channel, adapter identity, storage, event preservation PASS')
                ''')
            result = subprocess.run([sys.executable, '-c', script], env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('event preservation PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
