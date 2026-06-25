# Hermes Feishu Tag Plugin

Local scaffold for a Hermes `feishu` platform plugin implementing the Feishu Tag spec:

- single-pilot-chat admission boundary
- SQLite-backed Tier-0/Tier-1 memory
- reply media enrichment
- standing jobs
- privacy/admin lifecycle controls
- observable preflight metrics

## Verify

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Current tests use local fake Hermes/Feishu seams. Live Hermes registry, Feishu API, model sessions, and cron integration must be verified separately before production deployment.
