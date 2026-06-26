import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


class RealHermesCompatTest(unittest.TestCase):
    def test_current_hermes_feishu_adapter_contract(self):
        hermes_root = Path("/Users/february/.hermes/hermes-agent")
        if not hermes_root.exists():
            self.skipTest("local Hermes checkout is not available")

        env = os.environ.copy()
        env.pop("HERMES_PLUGIN_FEISHU_USE_STUBS", None)
        script = textwrap.dedent(
            f"""
            import json
            import sys
            sys.path.insert(0, {str(hermes_root)!r})
            sys.path.insert(0, {str(Path(__file__).resolve().parents[1] / "src")!r})
            import hermes_tag.adapter as mod

            class Ctx:
                def __init__(self):
                    self.calls = []
                def register_platform(self, name, label, adapter_factory, check_fn, validate_config=None, required_env=None, install_hint="", **entry_kwargs):
                    self.calls.append({{
                        "name": name,
                        "label": label,
                        "check": bool(check_fn()),
                        "validate_config": bool(validate_config),
                        "keys": sorted(entry_kwargs),
                    }})

            ctx = Ctx()
            mod.register(ctx)
            seeded = mod.apply_yaml_config(
                {{"extra": {{"feishu_tag": {{"enabled": True, "enabled_chats": ["oc_top"]}}}}}},
                {{"extra": {{"feishu_tag": {{"enabled": True, "enabled_chats": ["oc_nested"]}}}}}},
            )
            print(json.dumps({{
                "base": mod.BASE_FEISHU_MODULE,
                "check": mod.check_requirements(),
                "registered": ctx.calls,
                "seeded": seeded,
            }}, sort_keys=True))
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        data = json.loads(result.stdout)
        self.assertEqual(data["base"], "plugins.platforms.feishu.adapter")
        self.assertTrue(data["check"])
        self.assertEqual(data["registered"][0]["name"], "feishu")
        self.assertTrue(data["registered"][0]["check"])
        self.assertIn("apply_yaml_config_fn", data["registered"][0]["keys"])
        self.assertIn("standalone_sender_fn", data["registered"][0]["keys"])
        self.assertEqual(data["seeded"]["feishu_tag"]["enabled_chats"], ["oc_top"])


if __name__ == "__main__":
    unittest.main()
