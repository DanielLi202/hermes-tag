from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import inspect
import json
import os
import sqlite3
import time
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Callable

BOUNDARY_TEXT = "enabled_chats is the storage/processing boundary, not the receive boundary"
REQUIRED_SEAMS = {
    "handle_message": ("event",),
    "send_message": ("chat_id", "text"),
}


@dataclass(frozen=True)
class FeishuTagConfig:
    enabled_chats: tuple[str, ...]
    bot_app_id: str
    db_path: str
    granted_scopes: frozenset[str] = field(default_factory=frozenset)
    encryption_posture: str = "plaintext-db-on-local-disk"
    max_context_chars: int = 4000
    max_reply_media_items: int = 4
    max_reply_media_bytes: int = 8_000_000
    tier0_ttl_seconds: int = 86400
    tier0_max_count: int = 500
    media_cache_dir: str | None = None
    tier1_max_count: int = 100
    admins: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.enabled_chats) != 1:
            raise ValueError("single pilot requires exactly one enabled_chats chat_id")
        if not self.encryption_posture.strip():
            raise ValueError("encryption_posture must be declared")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FeishuTagConfig":
        return cls(
            enabled_chats=tuple(data.get("enabled_chats") or ()),
            bot_app_id=str(data.get("bot_app_id") or "").strip(),
            db_path=str(data.get("db_path") or "feishu-tag.sqlite3"),
            granted_scopes=frozenset(data.get("granted_scopes") or ()),
            encryption_posture=str(data.get("encryption_posture") or "").strip(),
            max_context_chars=int(data.get("max_context_chars") or 4000),
            max_reply_media_items=int(data.get("max_reply_media_items") or 4),
            max_reply_media_bytes=int(data.get("max_reply_media_bytes") or 8_000_000),
            tier0_ttl_seconds=int(data.get("tier0_ttl_seconds") or 86400),
            tier0_max_count=int(data.get("tier0_max_count") or 500),
            media_cache_dir=data.get("media_cache_dir"),
            tier1_max_count=int(data.get("tier1_max_count") or 100),
            admins=tuple(data.get("admins") or ()),
        )

    @property
    def pilot_chat_id(self) -> str:
        return self.enabled_chats[0]

    @property
    def has_group_msg_scope(self) -> bool:
        return "im:message.group_msg" in self.granted_scopes


class FeishuTagStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS metrics(name TEXT PRIMARY KEY, value INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS audit_events(id INTEGER PRIMARY KEY, event TEXT NOT NULL, chat_id TEXT, detail TEXT);
            CREATE TABLE IF NOT EXISTS tier0_messages(
                chat_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                text TEXT,
                author TEXT,
                thread_id TEXT,
                created_at REAL NOT NULL,
                media_paths TEXT NOT NULL DEFAULT '[]',
                PRIMARY KEY(chat_id, message_id)
            );
            CREATE TABLE IF NOT EXISTS tier1_memories(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                summary TEXT NOT NULL,
                owner TEXT,
                trigger_message_id TEXT NOT NULL,
                asked_by TEXT,
                source_message_ids TEXT NOT NULL,
                status TEXT NOT NULL,
                confidence REAL NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS standing_jobs(
                id TEXT PRIMARY KEY,
                chat_id TEXT NOT NULL,
                description TEXT NOT NULL,
                schedule TEXT NOT NULL,
                timezone TEXT NOT NULL,
                cron_job_id TEXT NOT NULL,
                owner TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            """
        )
        self.conn.commit()

    def inc(self, name: str, amount: int = 1) -> None:
        self.conn.execute(
            "INSERT INTO metrics(name, value) VALUES(?, ?) "
            "ON CONFLICT(name) DO UPDATE SET value = value + excluded.value",
            (name, amount),
        )
        self.conn.commit()

    def metric(self, name: str) -> int:
        row = self.conn.execute("SELECT value FROM metrics WHERE name=?", (name,)).fetchone()
        return int(row[0]) if row else 0

    def audit(self, event: str, chat_id: str | None = None, detail: str = "") -> None:
        self.conn.execute("INSERT INTO audit_events(event, chat_id, detail) VALUES(?,?,?)", (event, chat_id, detail))
        self.conn.commit()

    def audit_events(self, chat_id: str | None = None) -> list[sqlite3.Row]:
        if chat_id is None:
            return list(self.conn.execute("SELECT * FROM audit_events ORDER BY id"))
        return list(self.conn.execute("SELECT * FROM audit_events WHERE chat_id=? ORDER BY id", (chat_id,)))

    def insert_tier0(self, event: dict[str, Any], media_paths: list[str] | None = None) -> bool:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO tier0_messages(chat_id, message_id, text, author, thread_id, created_at, media_paths) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                event.get("chat_id"),
                event.get("message_id", ""),
                event.get("text", ""),
                event.get("author", ""),
                event.get("thread_id") or event.get("root_id") or event.get("parent_id") or event.get("message_id", ""),
                float(event.get("created_at") or time.time()),
                json.dumps(media_paths or event.get("media_paths") or []),
            ),
        )
        self.conn.commit()
        return cur.rowcount == 1

    def count_tier0(self, chat_id: str) -> int:
        return int(self.conn.execute("SELECT count(*) FROM tier0_messages WHERE chat_id=?", (chat_id,)).fetchone()[0])

    def tier0_rows(self, chat_id: str) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM tier0_messages WHERE chat_id=? ORDER BY created_at", (chat_id,)))

    def related_tier0(self, event: dict[str, Any], limit: int = 8) -> list[sqlite3.Row]:
        rows = self.tier0_rows(event["chat_id"])
        current_id = event.get("message_id")
        author = event.get("author")
        thread = event.get("thread_id") or event.get("root_id") or event.get("parent_id")
        text = event.get("text", "")

        def score(row: sqlite3.Row) -> tuple[int, float]:
            s = 0
            if row["message_id"] == current_id:
                return (-999, row["created_at"])
            if thread and row["thread_id"] == thread:
                s += 10
            if author and row["author"] == author:
                s += 5
            if "那个截图" in text and json.loads(row["media_paths"] or "[]"):
                s += 3
            return (s, row["created_at"])

        picked = [r for r in sorted(rows, key=score, reverse=True) if score(r)[0] > 0]
        return picked[:limit]

    def set_tier0_media_paths(self, chat_id: str, message_id: str, media_paths: list[str]) -> None:
        self.conn.execute(
            "UPDATE tier0_messages SET media_paths=? WHERE chat_id=? AND message_id=?",
            (json.dumps(media_paths), chat_id, message_id),
        )
        self.conn.commit()

    def write_tier1(self, chat_id: str, summary: str, owner: str, trigger_message_id: str, asked_by: str, source_message_ids: list[str], confidence: float = 1.0) -> None:
        self.conn.execute(
            "INSERT INTO tier1_memories(chat_id, summary, owner, trigger_message_id, asked_by, source_message_ids, status, confidence, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (chat_id, summary, owner, trigger_message_id, asked_by, json.dumps(source_message_ids), "active", confidence, time.time()),
        )
        self.inc("tier1_written")
        self.conn.commit()

    def tier1_rows(self, chat_id: str, active_only: bool = True) -> list[sqlite3.Row]:
        where = "WHERE chat_id=?" + (" AND status='active'" if active_only else "")
        return list(self.conn.execute(f"SELECT * FROM tier1_memories {where} ORDER BY created_at", (chat_id,)))

    def count_tier1(self, chat_id: str) -> int:
        return len(self.tier1_rows(chat_id))

    def relevant_tier1(self, event: dict[str, Any], limit: int = 4) -> list[sqlite3.Row]:
        owner = event.get("author", "")
        rows = self.tier1_rows(event["chat_id"])
        rows.sort(key=lambda r: (r["owner"] == owner, r["created_at"]), reverse=True)
        return rows[:limit]

    def consolidate_tier1(self, chat_id: str, max_count: int) -> None:
        while self.count_tier1(chat_id) > max_count:
            rows = self.tier1_rows(chat_id)[:2]
            if len(rows) < 2:
                return
            source_ids: list[str] = []
            for row in rows:
                source_ids.extend(json.loads(row["source_message_ids"] or "[]"))
            summary = "consolidated: " + " | ".join(row["summary"] for row in rows)
            owner = ",".join(sorted({row["owner"] for row in rows if row["owner"]}))
            self.conn.executemany("DELETE FROM tier1_memories WHERE id=?", [(row["id"],) for row in rows])
            self.conn.execute(
                "INSERT INTO tier1_memories(chat_id, summary, owner, trigger_message_id, asked_by, source_message_ids, status, confidence, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (chat_id, summary, owner, rows[-1]["trigger_message_id"], owner, json.dumps(sorted(set(source_ids))), "active", min(row["confidence"] for row in rows), time.time()),
            )
            self.conn.commit()

    def tombstone_tier1_by_message(self, chat_id: str, message_id: str) -> int:
        rows = self.tier1_rows(chat_id)
        changed = 0
        for row in rows:
            sources = set(json.loads(row["source_message_ids"] or "[]"))
            if row["trigger_message_id"] == message_id or message_id in sources:
                self.conn.execute("UPDATE tier1_memories SET status='tombstoned' WHERE id=?", (row["id"],))
                changed += 1
        self.conn.commit()
        return changed

    def create_standing_job(self, chat_id: str, description: str, schedule: str, timezone_name: str, cron_job_id: str, owner: str) -> str:
        job_id = f"job-{int(time.time() * 1000)}-{abs(hash((chat_id, description, schedule))) % 10000}"
        self.conn.execute(
            "INSERT INTO standing_jobs(id, chat_id, description, schedule, timezone, cron_job_id, owner, status, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (job_id, chat_id, description, schedule, timezone_name, cron_job_id, owner, "active", time.time()),
        )
        self.audit("standing_create", chat_id, job_id)
        self.conn.commit()
        return job_id

    def standing_jobs(self, chat_id: str, active_only: bool = False) -> list[sqlite3.Row]:
        suffix = " AND status='active'" if active_only else ""
        return list(self.conn.execute(f"SELECT * FROM standing_jobs WHERE chat_id=?{suffix} ORDER BY created_at", (chat_id,)))

    def count_standing_jobs(self, chat_id: str) -> int:
        return len(self.standing_jobs(chat_id, active_only=True))

    def set_standing_status(self, chat_id: str, job_id: str, status: str) -> int:
        cur = self.conn.execute("UPDATE standing_jobs SET status=? WHERE chat_id=? AND id=?", (status, chat_id, job_id))
        self.audit(f"standing_{status}", chat_id, job_id)
        self.conn.commit()
        return cur.rowcount

    def delete_standing_job(self, chat_id: str, job_id: str) -> sqlite3.Row | None:
        row = self.conn.execute("SELECT * FROM standing_jobs WHERE chat_id=? AND id=?", (chat_id, job_id)).fetchone()
        if row:
            self.conn.execute("DELETE FROM standing_jobs WHERE chat_id=? AND id=?", (chat_id, job_id))
            self.audit("standing_cancel", chat_id, job_id)
            self.conn.commit()
        return row

    def clear_chat(self, chat_id: str) -> None:
        for row in self.tier0_rows(chat_id):
            for path in json.loads(row["media_paths"] or "[]"):
                Path(path).unlink(missing_ok=True)
        self.conn.execute("DELETE FROM tier0_messages WHERE chat_id=?", (chat_id,))
        self.conn.execute("DELETE FROM tier1_memories WHERE chat_id=?", (chat_id,))
        self.conn.execute("DELETE FROM standing_jobs WHERE chat_id=?", (chat_id,))
        self.conn.commit()

    def evict_tier0(self, chat_id: str, ttl_seconds: int, max_count: int) -> int:
        now = time.time()
        victims = list(
            self.conn.execute(
                "SELECT * FROM tier0_messages WHERE chat_id=? AND created_at < ?",
                (chat_id, now - ttl_seconds),
            )
        )
        extra = list(
            self.conn.execute(
                "SELECT * FROM tier0_messages WHERE chat_id=? ORDER BY created_at DESC LIMIT -1 OFFSET ?",
                (chat_id, max_count),
            )
        )
        by_key = {(r["chat_id"], r["message_id"]): r for r in victims + extra}
        for row in by_key.values():
            for path in json.loads(row["media_paths"] or "[]"):
                Path(path).unlink(missing_ok=True)
            self.conn.execute("DELETE FROM tier0_messages WHERE chat_id=? AND message_id=?", (row["chat_id"], row["message_id"]))
        if by_key:
            self.inc("tier0_evicted", len(by_key))
        self.conn.commit()
        return len(by_key)

    def close(self) -> None:
        self.conn.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


class FeishuTagAdapter:
    def __init__(self, base_adapter: Any, config: FeishuTagConfig):
        self.base = base_adapter
        self.config = config
        self._assert_base_seams(base_adapter)
        self.store = FeishuTagStore(config.db_path)
        self.pending_jobs: dict[tuple[str, str], dict[str, str]] = {}
        self.notified_chats: set[str] = set()
        self.media_cache_dir = Path(config.media_cache_dir or f"{config.db_path}.media")
        self.media_cache_dir.mkdir(parents=True, exist_ok=True)
        self.store.audit("startup", config.pilot_chat_id, self.preflight_status()["boundary"])

    @staticmethod
    def _assert_base_seams(base_adapter: Any) -> None:
        for name, required in REQUIRED_SEAMS.items():
            method = getattr(base_adapter, name, None)
            if method is None:
                raise RuntimeError(f"Feishu base seam missing: {name}")
            params = tuple(inspect.signature(method).parameters)
            if params != required:
                raise RuntimeError(f"Feishu base seam signature mismatch: {name}{params} expected {required}")

    def preflight_status(self) -> dict[str, Any]:
        return {
            "adapter": type(self).__name__,
            "bot_app_id": self.config.bot_app_id,
            "enabled_chats": list(self.config.enabled_chats),
            "boundary": BOUNDARY_TEXT,
            "encryption_posture": self.config.encryption_posture,
            "capabilities": {
                "tier0_full_ingest": self.config.has_group_msg_scope,
                "l2_context": self.config.has_group_msg_scope,
                "tier1_at_memory": True,
            },
            "metrics": {
                "admission_dropped": self.store.metric("admission_dropped"),
                "tier0_rows": self.store.count_tier0(self.config.pilot_chat_id),
                "tier0_evicted": self.store.metric("tier0_evicted"),
                "tier1_memories": self.store.count_tier1(self.config.pilot_chat_id),
                "tier1_written": self.store.metric("tier1_written"),
                "tier1_write_failure": self.store.metric("tier1_write_failure"),
                "media_download_success": self.store.metric("media_download_success"),
                "media_download_failure": self.store.metric("media_download_failure"),
                "degraded_no_group_msg": 0 if self.config.has_group_msg_scope else 1,
                "standing_jobs": self.store.count_standing_jobs(self.config.pilot_chat_id),
                "override_selfcheck_ok": 1,
            },
            "retention": self.retention_table(),
        }

    def handle_message(self, event: dict[str, Any]) -> Any:
        with self.store.lock:
            chat_id = event.get("chat_id")
            if chat_id not in self.config.enabled_chats:
                self.store.inc("admission_dropped")
                return None
            if self.config.has_group_msg_scope:
                self.store.insert_tier0(event)
                self.store.evict_tier0(chat_id, self.config.tier0_ttl_seconds, self.config.tier0_max_count)
            if not event.get("mentioned"):
                return None
            standing = self._maybe_handle_standing_command(event)
            if standing is not None:
                return standing
            admin = self._maybe_handle_admin_command(event)
            if admin is not None:
                return admin
            enhanced = self._enhance_at_event(event)
            result = self.base.handle_message(enhanced)
            self._write_tier1_memory(event, enhanced, result)
            return result

    def _enhance_at_event(self, event: dict[str, Any]) -> dict[str, Any]:
        enhanced = dict(event)
        media_urls, media_types, placeholders, media_paths = self._load_reply_media(event)
        if self.config.has_group_msg_scope and media_paths:
            self.store.set_tier0_media_paths(event["chat_id"], event.get("message_id", ""), media_paths)
        l2_rows = self.store.related_tier0(event) if self.config.has_group_msg_scope else []
        background = self._format_l2_background(l2_rows)
        memories = self._select_tier1_memories(event)
        context = self._budget_context(event.get("text", ""), placeholders, background, memories)
        enhanced.update(
            {
                "media_urls": media_urls,
                "media_types": media_types,
                "context_text": context,
                "l2_context": background,
                "tier1_context": memories,
                "source_message_ids": [row["message_id"] for row in l2_rows],
                "task_session_id": f"{event.get('chat_id')}:{event.get('message_id')}",
                "uses_native_vision": bool(media_urls),
            }
        )
        return enhanced

    def _load_reply_media(self, event: dict[str, Any]) -> tuple[list[str], list[str], list[str], list[str]]:
        parent_id = event.get("parent_id") or event.get("root_id")
        if not parent_id or not hasattr(self.base, "fetch_message"):
            return [], [], [], []
        parent = self.base.fetch_message(parent_id)
        urls: list[str] = []
        types: list[str] = []
        placeholders: list[str] = []
        cache_paths: list[str] = []
        used_bytes = 0
        for item in parent.get("attachments", [])[: self.config.max_reply_media_items]:
            kind = item.get("kind") or item.get("type")
            key = item.get("key") or item.get("image_key") or item.get("file_key")
            try:
                if kind == "image":
                    blob = self.base.download_image(key)
                    media_type = "image"
                else:
                    media_type = item.get("resource_type") or kind or "file"
                    blob = self.base.download_resource(parent_id, key, media_type)
                data = blob if isinstance(blob, bytes) else bytes(str(blob), "utf-8")
                if used_bytes + len(data) > self.config.max_reply_media_bytes:
                    break
                used_bytes += len(data)
                path = self.media_cache_dir / f"{parent_id}-{key}"
                path.write_bytes(data)
                urls.append(path.as_uri())
                types.append(media_type)
                cache_paths.append(str(path))
                self.store.inc("media_download_success")
            except Exception:
                placeholders.append(f"[media unavailable: {key}]")
                self.store.inc("media_download_failure")
        return urls, types, placeholders, cache_paths

    def _format_l2_background(self, rows: list[sqlite3.Row]) -> list[str]:
        return [f"{row['author']}: {row['text']}" for row in rows]

    def _select_tier1_memories(self, event: dict[str, Any]) -> list[str]:
        return [f"memory(owner={row['owner']}): {row['summary']}" for row in self.store.relevant_tier1(event)]

    def _write_tier1_memory(self, event: dict[str, Any], enhanced: dict[str, Any], result: Any) -> None:
        text = (result.get("reply_text") or result.get("text")) if isinstance(result, dict) else str(result)
        summary = f"question={event.get('text','')}; context={'; '.join(enhanced.get('l2_context', [])[:2])}; conclusion={text}"
        sources = [event.get("message_id", "")] + list(enhanced.get("source_message_ids") or [])
        try:
            self.store.write_tier1(event["chat_id"], summary, event.get("author", ""), event.get("message_id", ""), event.get("author", ""), [s for s in sources if s])
            self.store.consolidate_tier1(event["chat_id"], self.config.tier1_max_count)
        except Exception:
            self.store.inc("tier1_write_failure")

    def delete_message(self, chat_id: str, message_id: str) -> int:
        return self.store.tombstone_tier1_by_message(chat_id, message_id)

    def disable_chat(self, chat_id: str) -> None:
        self.store.clear_chat(chat_id)
        self.store.audit("disable_chat", chat_id, "cleared tier0/tier1")

    def _budget_context(self, current: str, media_notes: list[str], background: list[str], memories: list[str]) -> str:
        pieces = [f"current: {current}"] + media_notes
        remaining = self.config.max_context_chars - sum(len(p) + 1 for p in pieces)
        kept: list[str] = []
        for item in background + memories:
            if remaining <= 0:
                break
            kept_item = item[:remaining]
            kept.append(kept_item)
            remaining -= len(kept_item) + 1
        return "\n".join(pieces + kept)[: self.config.max_context_chars]


    def _is_admin(self, user: str) -> bool:
        return not self.config.admins or user in self.config.admins

    def _maybe_handle_standing_command(self, event: dict[str, Any]) -> dict[str, Any] | None:
        text = event.get("text", "").strip()
        chat_id = event["chat_id"]
        user = event.get("author", "")
        if not text.startswith("/standing"):
            return None
        if not self._is_admin(user):
            return {"error": "permission denied"}
        parts = text.split(maxsplit=4)
        cmd = parts[1] if len(parts) > 1 else ""
        if cmd == "add" and len(parts) >= 5:
            self.pending_jobs[(chat_id, user)] = {"schedule": parts[2], "timezone": parts[3], "description": parts[4]}
            return {"confirmation_required": True, "text": "confirm standing job before registration"}
        if cmd == "confirm":
            pending = self.pending_jobs.pop((chat_id, user), None)
            if not pending:
                return {"error": "no pending standing job"}
            cron_id = self.base.register_cron(chat_id, pending["schedule"], pending["timezone"], pending["description"]) if hasattr(self.base, "register_cron") else f"cron-{int(time.time())}"
            job_id = self.store.create_standing_job(chat_id, pending["description"], pending["schedule"], pending["timezone"], cron_id, user)
            return {"created": job_id, "cron_job_id": cron_id}
        if cmd == "list":
            return {"jobs": [dict(row) for row in self.store.standing_jobs(chat_id)]}
        if cmd == "cancel" and len(parts) >= 3:
            row = self.store.delete_standing_job(chat_id, parts[2])
            if row and hasattr(self.base, "unregister_cron"):
                self.base.unregister_cron(row["cron_job_id"])
            return {"cancelled": bool(row), "job_id": parts[2]}
        if cmd in {"pause", "enable"} and len(parts) >= 3:
            status = "paused" if cmd == "pause" else "active"
            return {"updated": self.store.set_standing_status(chat_id, parts[2], status), "status": status}
        return {"error": "unknown standing command"}

    def _maybe_handle_admin_command(self, event: dict[str, Any]) -> dict[str, Any] | None:
        text = event.get("text", "").strip()
        if not text.startswith("/admin"):
            return None
        if not self._is_admin(event.get("author", "")):
            return {"error": "permission denied"}
        chat_id = event["chat_id"]
        cmd = text.split(maxsplit=1)[1] if " " in text else ""
        if cmd == "count":
            return {"tier0": self.store.count_tier0(chat_id), "tier1": self.store.count_tier1(chat_id), "standing_jobs": self.store.count_standing_jobs(chat_id)}
        if cmd == "clear":
            self.store.clear_chat(chat_id)
            self.store.audit("admin_clear", chat_id, "context cleared")
            return {"cleared": True}
        if cmd == "disable":
            self.disable_chat(chat_id)
            return {"disabled": True}
        return {"error": "unknown admin command"}

    def enable_chat(self, chat_id: str) -> str:
        notice = (
            "本群所有消息(含从未与 bot 交互的成员)会被本地记录并短期缓冲；"
            "只有在 @ bot 时相关消息才可能进入模型；"
            "长期记忆仅来自 @ 交互。"
        )
        if chat_id not in self.notified_chats:
            self.base.send_message(chat_id, notice)
            self.notified_chats.add(chat_id)
        self.store.audit("enable_chat", chat_id, "notice sent")
        return notice

    def disable_chat(self, chat_id: str) -> None:
        for row in list(self.store.standing_jobs(chat_id)):
            if hasattr(self.base, "unregister_cron"):
                self.base.unregister_cron(row["cron_job_id"])
        self.store.clear_chat(chat_id)
        self.store.audit("disable_chat", chat_id, "cleared tier0/tier1/media/cron")

    def trigger_standing_job(self, job_id: str) -> dict[str, Any] | None:
        row = self.store.conn.execute("SELECT * FROM standing_jobs WHERE id=?", (job_id,)).fetchone()
        if not row or row["status"] != "active":
            return None
        text = f"standing job: {row['description']}"
        result = self.base.send_message(row["chat_id"], text)
        self.store.audit("standing_trigger", row["chat_id"], job_id)
        return {"job_id": job_id, "sent": result}

    def retention_table(self) -> dict[str, str]:
        return {
            "Tier-0": f"physical delete after {self.config.tier0_ttl_seconds}s or {self.config.tier0_max_count} messages",
            "Tier-1": f"consolidate above {self.config.tier1_max_count}; tombstone on source deletion; clear on disable",
            "media": "deleted with owning Tier-0 row or chat disable",
            "cron": "active until cancel/pause/disable; removed on chat disable",
        }

    @staticmethod
    def next_weekly_fire(schedule: str, timezone_name: str, now: datetime) -> datetime:
        # ponytail: supports the only shipped fixture form; replace with Hermes cron parser if exposed.
        _, day_name, hm = schedule.split()
        weekdays = {"Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3, "Friday": 4, "Saturday": 5, "Sunday": 6}
        hour, minute = map(int, hm.split(":"))
        tz = ZoneInfo(timezone_name)
        local_now = now.astimezone(tz)
        days = (weekdays[day_name] - local_now.weekday()) % 7
        candidate = (local_now + timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= local_now:
            candidate += timedelta(days=7)
        return candidate


def register_plugin(registry: Any, base_adapter: Any, config: dict[str, Any] | FeishuTagConfig) -> Callable[..., FeishuTagAdapter]:
    cfg = config if isinstance(config, FeishuTagConfig) else FeishuTagConfig.from_dict(config)

    def factory() -> FeishuTagAdapter:
        return FeishuTagAdapter(base_adapter, cfg)

    registry.register("feishu", factory)
    return factory
