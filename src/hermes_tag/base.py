from __future__ import annotations

import copy
from dataclasses import is_dataclass, replace
from pathlib import Path
import inspect
import json
import mimetypes
import os
import re
import shutil
import time
from typing import Any

from .context import ContextSelector
from .core import TagConfig as FeishuTagConfig, TagEngine, TagStore as FeishuTagStore
from .i18n import ENABLE_NOTICE

HERMES_TAG = "v2026.6.19"
HERMES_COMMIT = "2bd1977d8fad185c9b4be47884f7e87f1add0ce3"
LARK_OAPI_VERSION = "1.6.9"
BOUNDARY_TEXT = "enabled_chats is the storage/processing boundary, not the receive boundary"
_TAG_HELP = [
    "/tag admin count",
    "/tag admin clear",
    "/tag admin disable",
    "/tag standing add <schedule> <timezone> <description>",
    "/tag standing confirm",
    "/tag standing list",
    "/tag standing cancel <job_id>",
    "/tag standing pause <job_id>",
    "/tag standing enable <job_id>",
    "/tag status",
]


class HermesCronAPI:
    def __init__(self, platform: str = "feishu") -> None:
        self.platform = platform

    def create(self, *, chat_id: str, description: str, schedule: str, timezone_name: str) -> str:
        from cron.jobs import create_job
        job = create_job(
            prompt=description,
            schedule=schedule,
            name=description[:50],
            deliver=self.platform,
            origin={"platform": self.platform, "chat_id": chat_id, "timezone": timezone_name},
        )
        return str(job["id"])

    def cancel(self, job_id: str) -> None:
        from cron.jobs import update_job
        update_job(job_id, {"enabled": False, "state": "cancelled"})

    def pause(self, job_id: str) -> None:
        from cron.jobs import update_job
        update_job(job_id, {"enabled": False, "state": "paused"})

    def enable(self, job_id: str) -> None:
        from cron.jobs import update_job
        update_job(job_id, {"enabled": True, "state": "scheduled"})


def _tag_extra(config: Any) -> dict[str, Any]:
    extra = config.get("extra", config) if isinstance(config, dict) else (getattr(config, "extra", {}) or {})
    data = extra.get("feishu_tag", {}) if isinstance(extra, dict) else {}
    return data if isinstance(data, dict) else {}


def _assert_signature(obj: Any, name: str, required: tuple[str, ...], *, async_required: bool = False) -> None:
    method = getattr(obj, name, None)
    if method is None:
        raise RuntimeError(f"Feishu seam missing: {name}")
    if async_required and not inspect.iscoroutinefunction(method):
        raise RuntimeError(f"Feishu seam must be async: {name}")
    params = tuple(inspect.signature(method).parameters)
    if params[: len(required)] != required:
        raise RuntimeError(f"Feishu seam signature mismatch: {name}{params} expected prefix {required}")


def assert_real_seams(adapter: Any, cron_api: Any | None = None) -> None:
    _assert_signature(adapter, "_dispatch_inbound_event", ("event",), async_required=True)
    _assert_signature(adapter, "send", ("chat_id", "content"), async_required=True)
    _assert_signature(adapter, "_fetch_reply_media_refs", ("reply_id",), async_required=True)
    _assert_signature(adapter, "_download_media", ("reply_id", "ref"), async_required=True)
    if cron_api is not None:
        for name in ("create", "cancel", "pause", "enable"):
            if not hasattr(cron_api, name):
                raise RuntimeError(f"Cron seam missing: {name}")


class TagAdapterMixin:
    def __init__(self, config: Any, tag_config: FeishuTagConfig, cron_api: Any | None = None):
        super().__init__(config)
        self.tag = tag_config
        self.store = FeishuTagStore(self.tag.db_path)
        self.media_cache_dir = Path(self.tag.media_cache_dir or f"{self.tag.db_path}.media")
        self.media_cache_dir.mkdir(parents=True, exist_ok=True)
        self.cron_api = cron_api or HermesCronAPI(self.platform_name)
        self.pending_jobs: dict[tuple[str, str], dict[str, str]] = {}
        self.notified_chats: set[str] = set()
        assert_real_seams(self, self.cron_api)
        self.engine = TagEngine(self.tag, self.store, self)
        self.pending_tier1 = self.engine.pending
        for chat_id in self.tag.enabled_chats:
            self.store.audit("startup", chat_id, BOUNDARY_TEXT)

    def preflight_status(self) -> dict[str, Any]:
        chat_id = self.tag.pilot_chat_id
        chat_metrics = {
            enabled_chat_id: {
                "tier0_rows": self.store.count_tier0(enabled_chat_id),
                "tier1_memories": self.store.count_tier1(enabled_chat_id),
                "standing_jobs": self.store.count_standing_jobs(enabled_chat_id),
            }
            for enabled_chat_id in self.tag.enabled_chats
        }
        return {
            "adapter": type(self).__name__,
            "hermes_tag": HERMES_TAG,
            "hermes_commit": HERMES_COMMIT,
            "lark_oapi_version": LARK_OAPI_VERSION,
            "base_feishu_module": getattr(self, "base_feishu_module", ""),
            "bot_app_id": self.tag.bot_app_id,
            "enabled_chats": list(self.tag.enabled_chats),
            "boundary": BOUNDARY_TEXT,
            "encryption_posture": self.tag.encryption_posture,
            "capabilities": {
                "tier0_full_ingest": self.tag.has_group_msg_scope,
                "l2_context": self.tag.has_group_msg_scope,
                "tier1_at_memory": True,
            },
            "seams": {
                "private_selfchecked": ["_dispatch_inbound_event", "_fetch_reply_media_refs", "_download_media"],
                "public": ["register(ctx)", "ctx.register_platform", "MessageEvent", "cron.jobs.create_job"],
            },
            "metrics": {
                "admission_dropped": self.store.metric("admission_dropped"),
                "tier0_rows": self.store.count_tier0(chat_id),
                "tier0_evicted": self.store.metric("tier0_evicted"),
                "tier1_memories": self.store.count_tier1(chat_id),
                "tier1_written": self.store.metric("tier1_written"),
                "tier1_write_failure": self.store.metric("tier1_write_failure"),
                "command_send_failure": self.store.metric("command_send_failure"),
                "media_download_success": self.store.metric("media_download_success"),
                "media_download_failure": self.store.metric("media_download_failure"),
                "degraded_no_group_msg": 0 if self.tag.has_group_msg_scope else 1,
                "standing_jobs": self.store.count_standing_jobs(chat_id),
                "enabled_chat_metrics": chat_metrics,
                "override_selfcheck_ok": 1,
            },
            "retention": self.retention_table(),
        }

    async def _dispatch_inbound_event(self, event: MessageEvent) -> Any:
        if _chat_id(event) not in self.tag.enabled_chats:
            return await super()._dispatch_inbound_event(event)
        return await self.engine.handle_message(event)

    @property
    def cron_delivery(self) -> bool:
        return True

    def handle_command(self, event: MessageEvent) -> Any | None:
        return self._maybe_handle_command(event)

    async def enhance_event(self, event: MessageEvent) -> tuple[MessageEvent, list[str]]:
        return await self._enhance_event(event)

    async def dispatch_to_model(self, event: MessageEvent) -> Any:
        return await super()._dispatch_inbound_event(event)

    async def send_to_platform(self, chat_id: str, content: str, reply_to=None, metadata=None) -> Any:
        return await super().send(chat_id, content, reply_to=reply_to, metadata=metadata)

    def write_tier1_memory(self, event: MessageEvent, enhanced: MessageEvent, result: Any) -> None:
        self._write_tier1_memory(event, enhanced, result)

    def store_tier0(self, event: MessageEvent, media_paths: list[str] | None = None) -> None:
        stored_media_paths = media_paths if media_paths is not None else self._persist_event_media(event)
        inserted = self.store.insert_tier0(
            chat_id=_chat_id(event),
            message_id=event.message_id or "",
            text=event.text,
            author=_author(event),
            thread_id=_thread_id(event) or event.reply_to_message_id,
            media_paths=stored_media_paths,
        )
        if inserted:
            detail = json.dumps(
                {
                    "message_id": event.message_id,
                    "author": _author(event),
                    "thread_id": _thread_id(event) or event.reply_to_message_id,
                    "text_chars": len(event.text or ""),
                    "media_count": len(stored_media_paths or []),
                },
                ensure_ascii=False,
            )
            self.store.audit("tier0_insert", _chat_id(event), detail)

    async def _enhance_event(self, event: MessageEvent) -> tuple[MessageEvent, list[str]]:
        parent_urls, parent_types, placeholders, parent_paths = await self._load_reply_media(event)
        orphan_paths: list[str] = []
        if parent_paths and self.tag.has_group_msg_scope:
            self.store.set_tier0_media_paths(_chat_id(event), event.message_id or "", parent_paths)
        elif parent_paths:
            orphan_paths.extend(parent_paths)
        recent_rows = [r for r in self.store.tier0_rows(_chat_id(event)) if r["message_id"] != event.message_id] if self.tag.has_group_msg_scope else []
        memory_rows = self.store.relevant_tier1(event)
        pack = ContextSelector().select(
            event,
            recent_rows=recent_rows,
            memory_rows=memory_rows,
        )
        related_media_urls, related_media_types, media_notes = self._related_media_from_rows(
            pack.media_rows,
            list(event.media_urls) + parent_urls,
        )
        background = [self._format_l2_row(row) for row in pack.text_rows] + media_notes
        memories = [f"memory(owner={row['owner']}): {row['summary']}" for row in pack.memory_rows]
        explicit_reply_id = getattr(event, "reply_to_message_id", None)
        explicit_anchor_id = explicit_reply_id or _thread_id(event)
        source_ids = _dedupe(
            [row["message_id"] for row in pack.text_rows]
            + [row["message_id"] for row in pack.media_rows]
            + ([explicit_anchor_id] if explicit_anchor_id else [])
        )
        enhanced = _copy_event(event)
        enhanced.media_urls = list(event.media_urls) + parent_urls + related_media_urls
        enhanced.media_types = list(event.media_types) + parent_types + related_media_types
        enhanced.channel_context = self._budget_context(event.text, placeholders, background, memories)
        setattr(enhanced, "tier1_context", memories)
        setattr(enhanced, "l2_context", background)
        setattr(enhanced, "source_message_ids", source_ids)
        setattr(enhanced, "task_session_id", f"{_chat_id(event)}:{event.message_id}")
        # ponytail: Feishu routes quoted replies through reply_to_message_id and/or source.thread_id.
        # Clear both on the dispatched copy so the answer returns to the main chat; keep the parent
        # captured as evidence through media/context/source_message_ids.
        reanchored = bool(explicit_anchor_id)
        if reanchored:
            enhanced.reply_to_message_id = None
            enhanced.source = _source_without_thread(getattr(enhanced, "source", None))
        self.store.audit(
            "enhance_event",
            _chat_id(event),
            json.dumps(
                {
                    "message_id": event.message_id,
                    "scope": pack.scope,
                    "has_explicit_anchor": pack.has_explicit_anchor,
                    "reply_target": event.message_id,
                    "reanchored": reanchored,
                    "media_by_source": {
                        "current": len(getattr(event, "media_urls", []) or []),
                        "parent": len(parent_urls),
                        "related": len(related_media_urls),
                    },
                    "selected_text_ids": [row["message_id"] for row in pack.text_rows],
                    "selected_media_ids": [row["message_id"] for row in pack.media_rows],
                    "excluded": [{"id": message_id, "reason": reason} for message_id, reason in pack.excluded],
                    "tier1_count": len(memories),
                    "context_preview": enhanced.channel_context[:240],
                },
                ensure_ascii=False,
            ),
        )
        return enhanced, orphan_paths

    def _persist_event_media(self, event: MessageEvent) -> list[str]:
        paths: list[str] = []
        media_urls = list(getattr(event, "media_urls", []) or [])
        media_types = list(getattr(event, "media_types", []) or [])
        for idx, value in enumerate(media_urls[: self.tag.max_reply_media_items]):
            source = Path(str(value))
            if not source.exists() or not source.is_file():
                continue
            try:
                size = source.stat().st_size
                if size > self.tag.max_reply_media_bytes:
                    continue
                try:
                    source.relative_to(self.media_cache_dir)
                    paths.append(str(source))
                    continue
                except ValueError:
                    pass
                suffix = source.suffix or mimetypes.guess_extension(media_types[idx] if idx < len(media_types) else "") or ".bin"
                message_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", event.message_id or "message")
                dest = self.media_cache_dir / f"{message_id}-{idx}{suffix}"
                shutil.copy2(source, dest)
                os.chmod(dest, 0o600)
                paths.append(str(dest))
            except Exception:
                self.store.inc("media_download_failure")
        return paths

    def _related_media_from_rows(self, rows: list[Any], existing_paths: list[str]) -> tuple[list[str], list[str], list[str]]:
        urls: list[str] = []
        types: list[str] = []
        notes: list[str] = []
        used_bytes = 0
        seen = {str(path) for path in existing_paths}
        for row in rows:
            try:
                row_paths = json.loads(row["media_paths"] or "[]")
            except Exception:
                row_paths = []
            attached_for_row = 0
            for value in row_paths:
                if len(urls) >= self.tag.max_reply_media_items:
                    break
                path = str(value)
                if path in seen:
                    continue
                file_path = Path(path)
                if not file_path.exists() or not file_path.is_file():
                    continue
                size = file_path.stat().st_size
                if used_bytes + size > self.tag.max_reply_media_bytes:
                    continue
                seen.add(path)
                urls.append(path)
                types.append(mimetypes.guess_type(path)[0] or "file")
                used_bytes += size
                attached_for_row += 1
            if attached_for_row:
                notes.append(f"[related media from {row['message_id']}: {attached_for_row} attachment(s)]")
        return urls, types, notes

    def _format_l2_row(self, row: Any) -> str:
        try:
            media_count = len(json.loads(row["media_paths"] or "[]"))
        except Exception:
            media_count = 0
        text = row["text"] or ""
        if media_count and not text:
            text = f"[media message: {media_count} attachment(s)]"
        elif media_count:
            text = f"{text} [media: {media_count} attachment(s)]"
        return f"{row['author']}: {text}"


    async def _load_reply_media(self, event: MessageEvent) -> tuple[list[str], list[str], list[str], list[str]]:
        reply_id = event.reply_to_message_id
        if not reply_id:
            return [], [], [], []
        raw_refs = await self._fetch_reply_media_refs(reply_id)
        urls: list[str] = []
        types: list[str] = []
        placeholders: list[str] = []
        paths: list[str] = []
        used = 0
        for ref in raw_refs[: self.tag.max_reply_media_items]:
            key = ref.get("key", "")
            try:
                path, media_type = await self._download_media(reply_id, ref)
                if not path:
                    raise RuntimeError("empty download path")
                size = Path(path).stat().st_size if Path(path).exists() else 0
                if used + size > self.tag.max_reply_media_bytes:
                    _unlink_all([path])
                    break
                used += size
                urls.append(path)
                types.append(media_type or ref.get("resource_type", "file"))
                paths.append(path)
                self.store.inc("media_download_success")
            except Exception:
                placeholders.append(f"[media unavailable: {key}]")
                self.store.inc("media_download_failure")
        return urls, types, placeholders, paths

    def _write_tier1_memory(self, event: MessageEvent, enhanced: MessageEvent, result: Any) -> None:
        try:
            conclusion = _result_text(result)
            if not conclusion:
                return
            background = list(getattr(enhanced, "l2_context", []) or [])[:2]
            sources = [event.message_id or ""] + list(getattr(enhanced, "source_message_ids", []) or [])
            summary = f"question={event.text}; context={'; '.join(background)}; conclusion={conclusion}"
            self.store.write_tier1(_chat_id(event), summary, _author(event), event.message_id or "", _author(event), [s for s in sources if s])
            self.store.consolidate_tier1(_chat_id(event), self.tag.tier1_max_count)
        except Exception:
            self.store.inc("tier1_write_failure")

    def _tier1_key_for_event(self, event: MessageEvent) -> str:
        return self.response_correlation_key(event, None)

    def response_correlation_key(self, event: MessageEvent, send_args: Any = None) -> str:
        return f"{_chat_id(event)}:{event.message_id}"

    def _tier1_key_for_response(self, chat_id: str, reply_to: Any = None, metadata: Any = None) -> str | None:
        return self.response_correlation_key_for_response(chat_id, reply_to=reply_to, metadata=metadata)

    def response_correlation_key_for_response(self, chat_id: str, reply_to: Any = None, metadata: Any = None) -> str | None:
        if isinstance(metadata, dict):
            for name in ("response_correlation_key", "task_session_id", "tier1_key"):
                value = metadata.get(name)
                if value:
                    return str(value)
            trigger_message_id = metadata.get("trigger_message_id")
            if trigger_message_id:
                return f"{chat_id}:{trigger_message_id}"
        if reply_to:
            value = str(reply_to)
            with self.store.lock:
                if value in self.pending_tier1:
                    return value
            return f"{chat_id}:{value}"
        return None

    def _prune_pending_tier1_locked(self) -> None:
        self.engine._prune_pending()

    def _budget_context(self, current: str, media_notes: list[str], background: list[str], memories: list[str]) -> str:
        pieces = [f"current: {current}"] + media_notes
        remaining = self.tag.max_context_chars - sum(len(p) + 1 for p in pieces)
        kept: list[str] = []
        for item in background + memories:
            if remaining <= 0:
                break
            item = item[:remaining]
            kept.append(item)
            remaining -= len(item) + 1
        return "\n".join(pieces + kept)[: self.tag.max_context_chars]

    def _maybe_handle_command(self, event: MessageEvent) -> Any | None:
        text = event.text.strip()
        if text == "/tag" or text.startswith("/tag "):
            return self._handle_tag(event)
        if text.startswith("/standing"):
            return self._handle_standing(event)
        if text.startswith("/admin"):
            return self._handle_admin(event)
        return None

    def _handle_tag(self, event: MessageEvent) -> dict[str, Any]:
        text = event.text.strip()
        rest = text[4:].strip()
        if not rest or rest == "help":
            return {"help": _TAG_HELP}
        area, _, args = rest.partition(" ")
        if area == "admin":
            return self._handle_admin(_command_event(event, f"/admin {args}".rstrip()))
        if area == "standing":
            return self._handle_standing(_command_event(event, f"/standing {args}".rstrip()))
        if area == "status":
            if not self._is_admin(_author(event)):
                return {"error": "permission denied"}
            return {"status": self.preflight_status()}
        return {"error": "unknown tag command"}

    def _is_admin(self, user: str) -> bool:
        return bool(self.tag.admins) and user in self.tag.admins

    def _handle_standing(self, event: MessageEvent) -> dict[str, Any]:
        chat_id, user = _chat_id(event), _author(event)
        if not self._is_admin(user):
            return {"error": "permission denied"}
        parts = event.text.split(maxsplit=4)
        cmd = parts[1] if len(parts) > 1 else ""
        if cmd == "add" and len(parts) >= 5:
            schedule = _normalize_schedule(parts[2])
            self.pending_jobs[(chat_id, user)] = {"schedule": schedule, "timezone": parts[3], "description": parts[4]}
            return {"confirmation_required": True, "schedule": schedule}
        if cmd == "confirm":
            pending = self.pending_jobs.pop((chat_id, user), None)
            if not pending:
                return {"error": "no pending standing job"}
            cron_id = self.cron_api.create(chat_id=chat_id, description=pending["description"], schedule=pending["schedule"], timezone_name=pending["timezone"])
            job_id = self.store.create_standing_job(chat_id, pending["description"], pending["schedule"], pending["timezone"], cron_id, user)
            return {"created": job_id, "cron_job_id": cron_id}
        if cmd == "list":
            return {"jobs": [dict(row) for row in self.store.standing_jobs(chat_id)]}
        if cmd == "cancel" and len(parts) >= 3:
            row = self.store.delete_standing_job(chat_id, parts[2])
            if row:
                self.cron_api.cancel(row["cron_job_id"])
            return {"cancelled": bool(row), "job_id": parts[2]}
        if cmd in {"pause", "enable"} and len(parts) >= 3:
            status = "paused" if cmd == "pause" else "active"
            row = self.store.conn.execute("SELECT * FROM standing_jobs WHERE chat_id=? AND id=?", (chat_id, parts[2])).fetchone()
            if row:
                (self.cron_api.pause if cmd == "pause" else self.cron_api.enable)(row["cron_job_id"])
            return {"updated": self.store.set_standing_status(chat_id, parts[2], status), "status": status}
        return {"error": "unknown standing command"}

    def _handle_admin(self, event: MessageEvent) -> dict[str, Any]:
        if not self._is_admin(_author(event)):
            return {"error": "permission denied"}
        chat_id = _chat_id(event)
        cmd = event.text.split(maxsplit=1)[1] if " " in event.text else ""
        if cmd == "count":
            return {"tier0": self.store.count_tier0(chat_id), "tier1": self.store.count_tier1(chat_id), "standing_jobs": self.store.count_standing_jobs(chat_id)}
        if cmd == "clear":
            self.store.clear_chat(chat_id)
            self.store.audit("admin_clear", chat_id, "context cleared")
            reset = self._reset_gateway_session(event)
            return {"cleared": True, "session_reset": reset["ok"], "session_reset_reason": reset.get("reason", "")}
        if cmd == "disable":
            self.disable_chat(chat_id)
            return {"disabled": True}
        return {"error": "unknown admin command"}

    async def enable_chat(self, chat_id: str) -> str:
        notice = ENABLE_NOTICE["zh"]
        if chat_id not in self.notified_chats:
            await self.send(chat_id, notice)
            self.notified_chats.add(chat_id)
        self.store.audit("enable_chat", chat_id, "notice sent")
        return notice

    def disable_chat(self, chat_id: str) -> None:
        for row in list(self.store.standing_jobs(chat_id)):
            self.cron_api.cancel(row["cron_job_id"])
        self.store.clear_chat(chat_id)
        self.store.audit("disable_chat", chat_id, "cleared tier0/tier1/media/cron")

    def delete_message(self, chat_id: str, message_id: str) -> int:
        return self.store.tombstone_tier1_by_message(chat_id, message_id)

    async def trigger_standing_job(self, job_id: str) -> dict[str, Any] | None:
        row = self.store.conn.execute("SELECT * FROM standing_jobs WHERE id=?", (job_id,)).fetchone()
        if not row or row["status"] != "active":
            return None
        result = await self.send(row["chat_id"], f"standing job: {row['description']}")
        self.store.audit("standing_trigger", row["chat_id"], job_id)
        return {"job_id": job_id, "sent": result}

    async def send(self, chat_id: str, content: str, reply_to=None, metadata=None) -> Any:
        return await self.engine.send(chat_id, content, reply_to=reply_to, metadata=metadata)

    def _reset_gateway_session(self, event: MessageEvent) -> dict[str, Any]:
        handler = getattr(self, "_message_handler", None)
        runner = getattr(handler, "__self__", None)
        session_store = getattr(runner, "session_store", None)
        if runner is None or session_store is None or not hasattr(session_store, "reset_session"):
            reason = "gateway runner unavailable"
            self.store.audit("hermes_session_reset_skipped", _chat_id(event), reason)
            return {"ok": False, "reason": reason}
        source = getattr(event, "source", None)
        if source is None:
            reason = "event source unavailable"
            self.store.audit("hermes_session_reset_skipped", _chat_id(event), reason)
            return {"ok": False, "reason": reason}
        try:
            normalize_source = getattr(runner, "_normalize_source_for_session_key", None)
            if callable(normalize_source):
                source = normalize_source(source)
            session_key_for_source = getattr(runner, "_session_key_for_source", None)
            if callable(session_key_for_source):
                session_key = session_key_for_source(source)
            else:
                session_key = session_store._generate_session_key(source)
            if not session_key:
                raise RuntimeError("empty session key")
            old_entry = getattr(session_store, "_entries", {}).get(session_key)
            old_session_id = getattr(old_entry, "session_id", "")
            self._clear_gateway_session_runtime_state(runner, session_key)
            new_entry = session_store.reset_session(session_key)
            if new_entry is None and hasattr(session_store, "get_or_create_session"):
                new_entry = session_store.get_or_create_session(source, force_new=True)
            new_session_id = getattr(new_entry, "session_id", "")
            detail = json.dumps(
                {"session_key": session_key, "old_session_id": old_session_id, "new_session_id": new_session_id},
                ensure_ascii=False,
            )
            self.store.audit("hermes_session_reset", _chat_id(event), detail)
            return {"ok": bool(new_entry), "reason": "" if new_entry else "session entry unavailable", "session_key": session_key, "old_session_id": old_session_id, "new_session_id": new_session_id}
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            self.store.audit("hermes_session_reset_failed", _chat_id(event), reason)
            return {"ok": False, "reason": reason}

    def _clear_gateway_session_runtime_state(self, runner: Any, session_key: str) -> None:
        for name, args in (
            ("_invalidate_session_run_generation", (session_key,)),
            ("_release_running_agent_state", (session_key,)),
            ("_evict_cached_agent", (session_key,)),
            ("_clear_session_boundary_security_state", (session_key,)),
        ):
            method = getattr(runner, name, None)
            if callable(method):
                try:
                    if name == "_invalidate_session_run_generation":
                        method(*args, reason="tag_admin_clear")
                    else:
                        method(*args)
                except Exception:
                    pass
        set_reasoning = getattr(runner, "_set_session_reasoning_override", None)
        if callable(set_reasoning):
            try:
                set_reasoning(session_key, None)
            except Exception:
                pass
        for attr in ("_queued_events", "_session_model_overrides", "_pending_model_notes"):
            value = getattr(runner, attr, None)
            if hasattr(value, "pop"):
                try:
                    value.pop(session_key, None)
                except Exception:
                    pass

    def retention_table(self) -> dict[str, str]:
        return {
            "Tier-0": f"physical delete after {self.tag.tier0_ttl_seconds}s or {self.tag.tier0_max_count} messages",
            "Tier-1": f"consolidate above {self.tag.tier1_max_count}; tombstone on source deletion; clear on disable",
            "media": "deleted with owning Tier-0 row, immediately in no-group-msg degradation, or on chat disable",
            "cron": "stored in Hermes cron API; cancel/pause/disable updates that API and local registry",
        }




def _chat_id(event: MessageEvent) -> str:
    return str(getattr(getattr(event, "source", None), "chat_id", "") or getattr(event, "chat_id", ""))


def _author(event: MessageEvent) -> str:
    source = getattr(event, "source", None)
    return str(getattr(source, "user_id", "") or getattr(source, "user_name", "") or getattr(event, "author", ""))


def _thread_id(event: MessageEvent) -> str | None:
    return getattr(getattr(event, "source", None), "thread_id", None) or getattr(event, "thread_id", None)

def _copy_event(event: Any) -> Any:
    cls = type(event)
    kwargs = {
        "text": event.text,
        "message_type": getattr(event, "message_type", "text"),
        "source": getattr(event, "source", None),
        "raw_message": getattr(event, "raw_message", None),
        "message_id": getattr(event, "message_id", None),
        "media_urls": list(getattr(event, "media_urls", []) or []),
        "media_types": list(getattr(event, "media_types", []) or []),
        "reply_to_message_id": getattr(event, "reply_to_message_id", None),
        "reply_to_text": getattr(event, "reply_to_text", None),
        "channel_context": getattr(event, "channel_context", None),
    }
    try:
        return cls(**kwargs)
    except Exception:
        copied = copy.copy(event)
        if hasattr(copied, "media_urls"):
            copied.media_urls = list(getattr(copied, "media_urls", []) or [])
        if hasattr(copied, "media_types"):
            copied.media_types = list(getattr(copied, "media_types", []) or [])
        return copied

def _command_event(event: MessageEvent, text: str) -> MessageEvent:
    copied = _copy_event(event)
    copied.text = text
    return copied


def _get_nested(value: Any, *path: str) -> Any | None:
    current = value
    for name in path:
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(name)
        else:
            current = getattr(current, name, None)
    return current


def _result_text(result: Any) -> str:
    if hasattr(result, "text"):
        return str(result.text)
    if isinstance(result, dict):
        return str(result.get("reply_text") or result.get("text") or result)
    return str(result)


def _normalize_schedule(schedule: str) -> str:
    # User shorthand kept at the command boundary; storage and cron both use the returned cron expr.
    match = re.fullmatch(r"weekly-([A-Za-z]+)-(\d{1,2}:\d{2})", schedule)
    if not match:
        return schedule
    day, hm = match.groups()
    weekday = {"monday": 1, "tuesday": 2, "wednesday": 3, "thursday": 4, "friday": 5, "saturday": 6, "sunday": 0}[day.lower()]
    hour, minute = hm.split(":")
    return f"{int(minute)} {int(hour)} * * {weekday}"


def _unlink_all(paths: list[str]) -> None:
    for path in paths:
        Path(path).unlink(missing_ok=True)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _source_without_thread(source: Any) -> Any:
    if source is None or getattr(source, "thread_id", None) is None:
        return source
    try:
        if is_dataclass(source):
            return replace(source, thread_id=None)
        cloned = copy.copy(source)
        setattr(cloned, "thread_id", None)
        return cloned
    except Exception:
        return source




__all__ = [
    "BOUNDARY_TEXT",
    "HERMES_COMMIT",
    "HERMES_TAG",
    "HermesCronAPI",
    "LARK_OAPI_VERSION",
    "TagAdapterMixin",
    "_assert_signature",
    "_author",
    "_chat_id",
    "_command_event",
    "_copy_event",
    "_dedupe",
    "_get_nested",
    "_normalize_schedule",
    "_result_text",
    "_source_without_thread",
    "_tag_extra",
    "_thread_id",
    "_unlink_all",
    "assert_real_seams",
]
