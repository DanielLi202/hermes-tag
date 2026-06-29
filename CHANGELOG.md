# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.3.0] - 2026-06-29

### Added

- DingTalk (钉钉) channel support via `DingTalkTagAdapter` (`platforms/dingtalk.py`), wrapping Hermes's
  built-in DingTalk Stream-Mode adapter with the same mixin pattern as Slack; `dingtalk_tag` config block,
  registration with fail-safe fallback to the base adapter, and `tests/test_dingtalk_seam.py`.
- `docs/dingtalk.md` documenting setup and the DingTalk capability limit.

### Notes

- DingTalk has no equivalent of Feishu's `im:message.group_msg`: bots only receive @-mention messages in
  groups, so ambient group context (Tier-0) is unavailable on DingTalk and the plugin degrades to @-only
  Tier-1 memory there. See `docs/dingtalk.md` and `docs/design/0.3.0-dingtalk-plan.md`.

## [0.2.0] - 2026-06-26

### Added

- Per-chat Tier-0 short-term context for enabled chats.
- @-derived Tier-1 long-term memory with consolidation and tombstone handling.
- Explicit `ContextSelector` scopes for `focused_reply`, `deictic_recent`, and plain messages.
- Cron-backed standing jobs with confirmation, listing, cancellation, pause, and enable flows.
- Privacy lifecycle controls around the allowlist boundary, admin clear/disable, and audit logging.
- `/tag` namespaced commands for admin, standing-job, help, and status flows.

### Changed

- Renamed the plugin to `hermes-tag` (package `hermes_tag`, manifest name `hermes-tag`, label "Hermes Tag"); the overridden platform remains `feishu`.
- Refactored the plugin around a platform-agnostic `TagAdapterMixin`, narrowing the per-platform seam.
- Removed obsolete root `channels/` and `core/` import shims after verifying the pinned Hermes loader imports only root `__init__.py` and `plugin.yaml`.
- Kept `manifest_version: 1`; the pinned Hermes installer accepts version 1 and rejects only versions above its supported maximum.
- Cleaned repository hygiene by removing the stray `:memory:` artifact and relocating internal design documents to `docs/design/`.
