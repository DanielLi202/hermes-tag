import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def plugin_yaml_version() -> str:
    for line in (ROOT / "plugin.yaml").read_text().splitlines():
        if line.startswith("version:"):
            return line.split(":", 1)[1].strip().strip("\"'")
    raise AssertionError("plugin.yaml missing version line")


class VersionAgreementTest(unittest.TestCase):
    def test_plugin_yaml_matches_pyproject_version(self):
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
        self.assertEqual(plugin_yaml_version(), pyproject["project"]["version"])


if __name__ == "__main__":
    unittest.main()
