from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class TagConfig:
    enabled_chats: tuple[str, ...]
    bot_app_id: str = ""
    db_path: str = "feishu-tag.sqlite3"
    granted_scopes: frozenset[str] = field(default_factory=frozenset)
    encryption_posture: str = "plaintext-db-on-local-disk"
    max_context_chars: int = 4000
    max_reply_media_items: int = 4
    max_reply_media_bytes: int = 8_000_000
    tier0_ttl_seconds: int = 86400
    tier0_max_count: int = 500
    tier1_max_count: int = 100
    media_cache_dir: str | None = None
    admins: tuple[str, ...] = ()
    require_mention: bool = True
    bot_open_id: str = ""
    tier1_pending_ttl_seconds: int = 3600

    def __post_init__(self) -> None:
        if not self.enabled_chats:
            raise ValueError("enabled_chats requires at least one chat_id")
        if not self.encryption_posture.strip():
            raise ValueError("encryption_posture must be declared")

    @classmethod
    def from_platform_config(cls, config: PlatformConfig | dict[str, Any]) -> "TagConfig":
        extra = config.get("extra", config) if isinstance(config, dict) else (getattr(config, "extra", {}) or {})
        data = extra.get("feishu_tag", extra)
        return cls(
            enabled_chats=tuple(data.get("enabled_chats") or ()),
            bot_app_id=str(data.get("bot_app_id") or data.get("app_id") or "").strip(),
            db_path=str(data.get("db_path") or "feishu-tag.sqlite3"),
            granted_scopes=frozenset(data.get("granted_scopes") or ()),
            encryption_posture=str(data.get("encryption_posture") or "plaintext-db-on-local-disk").strip(),
            max_context_chars=int(data.get("max_context_chars") or 4000),
            max_reply_media_items=int(data.get("max_reply_media_items") or 4),
            max_reply_media_bytes=int(data.get("max_reply_media_bytes") or 8_000_000),
            tier0_ttl_seconds=int(data.get("tier0_ttl_seconds") or 86400),
            tier0_max_count=int(data.get("tier0_max_count") or 500),
            tier1_max_count=int(data.get("tier1_max_count") or 100),
            media_cache_dir=data.get("media_cache_dir"),
            admins=tuple(data.get("admins") or ()),
            require_mention=bool(data.get("require_mention", True)),
            bot_open_id=str(data.get("bot_open_id") or data.get("bot_open_id_for_mentions") or "").strip(),
            tier1_pending_ttl_seconds=int(data.get("tier1_pending_ttl_seconds") or 3600),
        )

    @property
    def pilot_chat_id(self) -> str:
        return self.enabled_chats[0]

    @property
    def has_group_msg_scope(self) -> bool:
        return "im:message.group_msg" in self.granted_scopes


class TagStore:
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
                chat_id TEXT NOT NULL, message_id TEXT NOT NULL, text TEXT, author TEXT,
                thread_id TEXT, created_at REAL NOT NULL, media_paths TEXT NOT NULL DEFAULT '[]',
                PRIMARY KEY(chat_id, message_id)
            );
            CREATE TABLE IF NOT EXISTS tier1_memories(
                id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL, summary TEXT NOT NULL,
                owner TEXT, trigger_message_id TEXT NOT NULL, asked_by TEXT,
                source_message_ids TEXT NOT NULL, status TEXT NOT NULL, confidence REAL NOT NULL, created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS standing_jobs(
                id TEXT PRIMARY KEY, chat_id TEXT NOT NULL, description TEXT NOT NULL, schedule TEXT NOT NULL,
                timezone TEXT NOT NULL, cron_job_id TEXT NOT NULL, owner TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL
            );
            """
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def inc(self, name: str, amount: int = 1) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO metrics(name,value) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=value+excluded.value",
                (name, amount),
            )
            self.conn.commit()

    def metric(self, name: str) -> int:
        with self.lock:
            row = self.conn.execute("SELECT value FROM metrics WHERE name=?", (name,)).fetchone()
            return int(row[0]) if row else 0

    def audit(self, event: str, chat_id: str | None = None, detail: str = "") -> None:
        with self.lock:
            self.conn.execute("INSERT INTO audit_events(event,chat_id,detail) VALUES(?,?,?)", (event, chat_id, detail))
            self.conn.commit()

    def audit_events(self, chat_id: str | None = None) -> list[sqlite3.Row]:
        with self.lock:
            if chat_id is None:
                return list(self.conn.execute("SELECT * FROM audit_events ORDER BY id"))
            return list(self.conn.execute("SELECT * FROM audit_events WHERE chat_id=? ORDER BY id", (chat_id,)))

    def insert_tier0(self, *, chat_id: str, message_id: str, text: str, author: str, thread_id: str | None, media_paths: list[str] | None = None, created_at: float | None = None) -> bool:
        with self.lock:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO tier0_messages(chat_id,message_id,text,author,thread_id,created_at,media_paths) VALUES(?,?,?,?,?,?,?)",
                (chat_id, message_id, text, author, thread_id or message_id, created_at or time.time(), json.dumps(media_paths or [])),
            )
            self.conn.commit()
            return cur.rowcount == 1

    def set_tier0_media_paths(self, chat_id: str, message_id: str, paths: list[str]) -> None:
        with self.lock:
            self.conn.execute("UPDATE tier0_messages SET media_paths=? WHERE chat_id=? AND message_id=?", (json.dumps(paths), chat_id, message_id))
            self.conn.commit()

    def count_tier0(self, chat_id: str) -> int:
        with self.lock:
            return int(self.conn.execute("SELECT count(*) FROM tier0_messages WHERE chat_id=?", (chat_id,)).fetchone()[0])

    def tier0_rows(self, chat_id: str) -> list[sqlite3.Row]:
        with self.lock:
            return list(self.conn.execute("SELECT * FROM tier0_messages WHERE chat_id=? ORDER BY created_at", (chat_id,)))

    def evict_tier0(self, chat_id: str, ttl_seconds: int, max_count: int) -> int:
        with self.lock:
            victims = list(self.conn.execute("SELECT * FROM tier0_messages WHERE chat_id=? AND created_at < ?", (chat_id, time.time() - ttl_seconds)))
            extra = list(self.conn.execute("SELECT * FROM tier0_messages WHERE chat_id=? ORDER BY created_at DESC LIMIT -1 OFFSET ?", (chat_id, max_count)))
            by_key = {(r["chat_id"], r["message_id"]): r for r in victims + extra}
            for row in by_key.values():
                for path in json.loads(row["media_paths"] or "[]"):
                    Path(path).unlink(missing_ok=True)
                self.conn.execute("DELETE FROM tier0_messages WHERE chat_id=? AND message_id=?", (row["chat_id"], row["message_id"]))
            self.conn.commit()
        if by_key:
            self.inc("tier0_evicted", len(by_key))
        return len(by_key)

    def write_tier1(self, chat_id: str, summary: str, owner: str, trigger_message_id: str, asked_by: str, source_message_ids: list[str], confidence: float = 1.0) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO tier1_memories(chat_id,summary,owner,trigger_message_id,asked_by,source_message_ids,status,confidence,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (chat_id, summary, owner, trigger_message_id, asked_by, json.dumps(source_message_ids), "active", confidence, time.time()),
            )
            self.conn.commit()
        self.inc("tier1_written")

    def tier1_rows(self, chat_id: str, active_only: bool = True) -> list[sqlite3.Row]:
        with self.lock:
            where = "WHERE chat_id=?" + (" AND status='active'" if active_only else "")
            return list(self.conn.execute(f"SELECT * FROM tier1_memories {where} ORDER BY created_at", (chat_id,)))

    def count_tier1(self, chat_id: str) -> int:
        return len(self.tier1_rows(chat_id))

    def relevant_tier1(self, event: Any, limit: int = 4) -> list[sqlite3.Row]:
        owner = author_of(event)
        rows = self.tier1_rows(chat_id_of(event))
        rows.sort(key=lambda r: (r["owner"] == owner, r["created_at"]), reverse=True)
        return rows[:limit]

    def consolidate_tier1(self, chat_id: str, max_count: int) -> None:
        while self.count_tier1(chat_id) > max_count:
            rows = self.tier1_rows(chat_id)[:2]
            if len(rows) < 2:
                return
            sources: list[str] = []
            for row in rows:
                sources.extend(json.loads(row["source_message_ids"] or "[]"))
            summary = "consolidated: " + " | ".join(row["summary"] for row in rows)
            owner = ",".join(sorted({row["owner"] for row in rows if row["owner"]}))
            with self.lock:
                self.conn.executemany("DELETE FROM tier1_memories WHERE id=?", [(row["id"],) for row in rows])
                self.conn.execute(
                    "INSERT INTO tier1_memories(chat_id,summary,owner,trigger_message_id,asked_by,source_message_ids,status,confidence,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (chat_id, summary, owner, rows[-1]["trigger_message_id"], owner, json.dumps(sorted(set(sources))), "active", min(row["confidence"] for row in rows), time.time()),
                )
                self.conn.commit()

    def tombstone_tier1_by_message(self, chat_id: str, message_id: str) -> int:
        changed = 0
        with self.lock:
            for row in self.tier1_rows(chat_id):
                if row["trigger_message_id"] == message_id or message_id in set(json.loads(row["source_message_ids"] or "[]")):
                    self.conn.execute("UPDATE tier1_memories SET status='tombstoned' WHERE id=?", (row["id"],))
                    changed += 1
            self.conn.commit()
        return changed

    def create_standing_job(self, chat_id: str, description: str, schedule: str, timezone_name: str, cron_job_id: str, owner: str) -> str:
        job_id = f"job-{int(time.time() * 1000)}-{abs(hash((chat_id, description, schedule))) % 10000}"
        with self.lock:
            self.conn.execute(
                "INSERT INTO standing_jobs(id,chat_id,description,schedule,timezone,cron_job_id,owner,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (job_id, chat_id, description, schedule, timezone_name, cron_job_id, owner, "active", time.time()),
            )
            self.conn.commit()
        self.audit("standing_create", chat_id, job_id)
        return job_id

    def standing_jobs(self, chat_id: str, active_only: bool = False) -> list[sqlite3.Row]:
        with self.lock:
            suffix = " AND status='active'" if active_only else ""
            return list(self.conn.execute(f"SELECT * FROM standing_jobs WHERE chat_id=?{suffix} ORDER BY created_at", (chat_id,)))

    def count_standing_jobs(self, chat_id: str) -> int:
        return len(self.standing_jobs(chat_id, active_only=True))

    def set_standing_status(self, chat_id: str, job_id: str, status: str) -> int:
        with self.lock:
            cur = self.conn.execute("UPDATE standing_jobs SET status=? WHERE chat_id=? AND id=?", (status, chat_id, job_id))
            self.conn.commit()
        self.audit(f"standing_{status}", chat_id, job_id)
        return cur.rowcount

    def delete_standing_job(self, chat_id: str, job_id: str) -> sqlite3.Row | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM standing_jobs WHERE chat_id=? AND id=?", (chat_id, job_id)).fetchone()
            if row:
                self.conn.execute("DELETE FROM standing_jobs WHERE chat_id=? AND id=?", (chat_id, job_id))
                self.conn.commit()
        if row:
            self.audit("standing_cancel", chat_id, job_id)
        return row

    def clear_chat(self, chat_id: str) -> None:
        for row in self.tier0_rows(chat_id):
            for path in json.loads(row["media_paths"] or "[]"):
                Path(path).unlink(missing_ok=True)
        with self.lock:
            self.conn.execute("DELETE FROM tier0_messages WHERE chat_id=?", (chat_id,))
            self.conn.execute("DELETE FROM tier1_memories WHERE chat_id=?", (chat_id,))
            self.conn.execute("DELETE FROM standing_jobs WHERE chat_id=?", (chat_id,))
            self.conn.commit()


class PlatformSeam(Protocol):
    platform_name: str
    receive_all: bool
    cron_delivery: bool

    def is_mentioned(self, event: Any) -> bool: ...
    def response_correlation_key(self, event: Any, send_args: Any = None) -> str: ...
    def response_correlation_key_for_response(self, chat_id: str, reply_to: Any = None, metadata: Any = None) -> str | None: ...
    def store_tier0(self, event: Any) -> None: ...
    def handle_command(self, event: Any) -> Any | None: ...
    async def enhance_event(self, event: Any) -> tuple[Any, list[str]]: ...
    async def dispatch_to_model(self, event: Any) -> Any: ...
    async def send_to_platform(self, chat_id: str, content: str, reply_to=None, metadata=None) -> Any: ...
    def write_tier1_memory(self, event: Any, enhanced: Any, result: Any) -> None: ...


class TagEngine:
    def __init__(self, tag: Any, store: Any, seam: PlatformSeam):
        self.tag = tag
        self.store = store
        self.seam = seam
        self.pending: dict[str, tuple[float, Any, Any]] = {}

    def preflight_status(self) -> dict[str, Any]:
        chat_metrics = {
            chat_id: {
                "tier0_rows": self.store.count_tier0(chat_id),
                "tier1_memories": self.store.count_tier1(chat_id),
            }
            for chat_id in self.tag.enabled_chats
        }
        return {
            "platform": self.seam.platform_name,
            "capabilities": {"receive_all": self.seam.receive_all, "cron_delivery": self.seam.cron_delivery},
            "metrics": {
                "tier0_rows": self.store.count_tier0(self.tag.pilot_chat_id),
                "tier1_memories": self.store.count_tier1(self.tag.pilot_chat_id),
                "enabled_chat_metrics": chat_metrics,
            },
        }

    async def handle_message(self, event: Any) -> Any:
        chat_id = chat_id_of(event)
        if chat_id not in self.tag.enabled_chats:
            self.store.inc("admission_dropped")
            return None
        if self.seam.receive_all:
            self.seam.store_tier0(event)
            self.store.evict_tier0(chat_id, self.tag.tier0_ttl_seconds, self.tag.tier0_max_count)
        if not self.seam.is_mentioned(event):
            return None
        command_result = self.seam.handle_command(event)
        if command_result is not None:
            try:
                await self.seam.send_to_platform(
                    chat_id,
                    format_command_result(command_result),
                    reply_to=getattr(event, "message_id", None),
                    metadata={"tag_command": True},
                )
            except Exception:
                self.store.inc("command_send_failure")
                raise
            return command_result
        enhanced, orphan_paths = await self.seam.enhance_event(event)
        self._prune_pending()
        key = self.seam.response_correlation_key(enhanced)
        setattr(enhanced, "task_session_id", key)
        self.pending[key] = (time.time(), event, enhanced)
        try:
            return await self.seam.dispatch_to_model(enhanced)
        finally:
            for path in orphan_paths:
                Path(path).unlink(missing_ok=True)

    async def send(self, chat_id: str, content: str, reply_to=None, metadata=None) -> Any:
        result = await self.seam.send_to_platform(chat_id, content, reply_to=reply_to, metadata=metadata)
        key = self.seam.response_correlation_key_for_response(chat_id, reply_to=reply_to, metadata=metadata)
        pending = None
        if key:
            self._prune_pending()
            pending = self.pending.pop(key, None)
        if pending:
            _, event, enhanced = pending
            self.seam.write_tier1_memory(event, enhanced, content)
        return result

    def _prune_pending(self) -> None:
        cutoff = time.time() - self.tag.tier1_pending_ttl_seconds
        for key, (created_at, _, _) in list(self.pending.items()):
            if created_at < cutoff:
                del self.pending[key]


def format_command_result(result: Any) -> str:
    if isinstance(result, str):
        return result
    if not isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False, sort_keys=True)

    error = result.get("error")
    if error:
        return f"error: {error}"
    if result.get("cleared"):
        if result.get("session_reset"):
            return "cleared; session reset"
        if "session_reset" in result:
            reason = result.get("session_reset_reason") or "unavailable"
            return f"cleared; session reset skipped: {reason}"
        return "cleared"
    if result.get("disabled"):
        return "disabled"
    if "help" in result:
        lines = result.get("help") or []
        return "tag commands:\n" + "\n".join(str(line) for line in lines)
    if "status" in result:
        status = result.get("status") or {}
        if isinstance(status, dict):
            capabilities = status.get("capabilities", {}) or {}
            metrics = status.get("metrics", {}) or {}
            capability_text = " ".join(f"{key}={value}" for key, value in sorted(capabilities.items()))
            metric_text = " ".join(f"{key}={value}" for key, value in sorted(metrics.items()))
            platform = status.get("platform") or status.get("adapter") or ""
            return f"status platform={platform} {capability_text}\nmetrics {metric_text}".strip()
        return f"status {status}"
    if {"tier0", "tier1", "standing_jobs"}.issubset(result):
        return f"tier0={result['tier0']} tier1={result['tier1']} standing_jobs={result['standing_jobs']}"
    if result.get("confirmation_required"):
        schedule = result.get("schedule", "")
        return f"confirmation_required schedule={schedule}".strip()
    if result.get("created"):
        return f"created {result['created']} cron_job_id={result.get('cron_job_id', '')}".strip()
    if "jobs" in result:
        jobs = result.get("jobs") or []
        if not jobs:
            return "jobs: none"
        lines = ["jobs:"]
        for job in jobs:
            if isinstance(job, dict):
                lines.append(f"- {job.get('id', '')} {job.get('status', '')} {job.get('schedule', '')} {job.get('description', '')}".rstrip())
            else:
                lines.append(f"- {job}")
        return "\n".join(lines)
    if "cancelled" in result:
        return f"cancelled={bool(result.get('cancelled'))} job_id={result.get('job_id', '')}".strip()
    if "updated" in result:
        return f"updated={bool(result.get('updated'))} status={result.get('status', '')}".strip()
    return json.dumps(result, ensure_ascii=False, sort_keys=True)


def chat_id_of(event: Any) -> str:
    return str(getattr(getattr(event, "source", None), "chat_id", "") or getattr(event, "chat_id", ""))


def author_of(event: Any) -> str:
    source = getattr(event, "source", None)
    return str(getattr(source, "user_id", "") or getattr(source, "user_name", "") or getattr(event, "author", ""))


def thread_id_of(event: Any) -> str | None:
    return getattr(getattr(event, "source", None), "thread_id", None) or getattr(event, "thread_id", None)


def copy_event(event: Any) -> Any:
    cls = type(event)
    if is_dataclass(event):
        values = {f.name: getattr(event, f.name) for f in fields(event)}
        values["media_urls"] = list(values.get("media_urls") or [])
        values["media_types"] = list(values.get("media_types") or [])
        return cls(**values)
    copied = cls.__new__(cls)
    copied.__dict__.update(getattr(event, "__dict__", {}))
    if hasattr(copied, "media_urls"):
        copied.media_urls = list(copied.media_urls or [])
    if hasattr(copied, "media_types"):
        copied.media_types = list(copied.media_types or [])
    return copied


def result_text(result: Any) -> str:
    if hasattr(result, "text"):
        return str(result.text)
    if isinstance(result, dict):
        return str(result.get("reply_text") or result.get("text") or result)
    return str(result)
