# Hermes Feishu Tag Plugin

Local scaffold for a Hermes `feishu` platform plugin implementing the Feishu Tag repair spec.

Pinned integration targets:

- `NousResearch/hermes-agent` tag `v2026.6.19` (`2bd1977d8fad185c9b4be47884f7e87f1add0ce3`), project version `0.17.0`
- `lark-oapi==1.6.9`

The plugin exposes a root-level `__init__.py` for Hermes directory-plugin installs and delegates to `src/hermes_plugin_feishu.register(ctx)`. It subclasses the real `gateway.platforms.feishu.FeishuAdapter` when Hermes is installed; tests use contract-shaped local stubs.

## Verify

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

## Integration smoke status

Live Hermes/Feishu smoke is not included in this repository. It requires a real Hermes gateway, a real Feishu test app/bot, a pilot group, and current scope approval. See `docs/repair-evidence.md` for the current blocker record.

## Install notes

`plugin.yaml` uses only Hermes directory-plugin manifest fields (`manifest_version`, `name`, `label`, `kind`, `version`, `description`, `author`, `requires_env`). See `after-install.md` for the required Feishu receive-all config and privacy notice.
