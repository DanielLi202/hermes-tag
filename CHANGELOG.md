# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed

- Renamed the plugin to `hermes-tag` (package `hermes_tag`, manifest name `hermes-tag`, label "Hermes Tag"); the overridden platform remains `feishu`.
- Refactored the plugin around a platform-agnostic `TagAdapterMixin`, narrowing the per-platform seam.
- Cleaned repository hygiene by removing the stray `:memory:` artifact and relocating internal design documents to `docs/design/`.

## [0.2.0] - 2026-06-26

### Added

- Per-chat Tier-0 short-term context for enabled chats.
- @-derived Tier-1 long-term memory with consolidation and tombstone handling.
- Explicit `ContextSelector` scopes for `focused_reply`, `deictic_recent`, and plain messages.
- Cron-backed standing jobs with confirmation, listing, cancellation, pause, and enable flows.
- Privacy lifecycle controls around the allowlist boundary, admin clear/disable, and audit logging.
- `/tag` namespaced commands for admin, standing-job, help, and status flows.
